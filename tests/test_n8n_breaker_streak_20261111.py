"""LQ-20261107-1891: the breaker streak is per execution mode.

Hermetic: a tmp ledger, a fixed clock; no live ledger, no sockets, no sends.

BEFORE (base `9c21372aa`): ``jsonl-archive-rotate``'s live breaker opened at **2026-11-10T21:45:33Z** with
``consecutive=3`` although the lane held only **two** live dead letters. ``consecutive_dead()`` counted an
unreleased **dry_run** dead letter from 2026-10-29T20:48:02Z (RUN_TIMEOUT ``executor_lost``) into the live
streak, and the threshold is 3. A dry_run slot never runs on the live path, so its failure cannot be one of
the live consecutive failures the breaker guards; the unrelated 13-day-old timeout paused the live lane.

These tests fail on the base (``assert 3 == 2``; the breaker row exists) and pass once the streak counts only
dead slots of the run's own mode. The dry_run-only test is the guard that the fix does not disarm lanes whose
dispatch mode really is dry_run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_retry_policy as rp  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402

POLICY_FILE = ROOT / "config" / "n8n_retry_policies.json"
T0 = 1_791_550_800.0  # fixed fake clock
LANE = "jsonl-archive-rotate"
THRESHOLD = 3
DAY = 86_400.0


@pytest.fixture()
def store(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    yield LedgerRunStore(ledger)
    ledger.close()


@pytest.fixture()
def policies():
    return rp.load_policies(POLICY_FILE)


def _run(store, policies, minute: str, *, mode: str = "live", state: str = "RUN_FAILED", exit_code=1,
         reason: str | None = "exit_1", at: float = T0, policy: str = "transient-2"):
    slot = f"d:{LANE}:{mode}:{minute}"
    store.request(run_id=slot, lane_id=LANE, mode=mode, requested_by="n8n", caller_id="n8n-relay", now=at,
                  slot_key=slot, attempt=1, klass="report", priority=5)
    assert store.claim_next(now=at + 1)["run_id"] == slot
    row = store.finish(slot, state=state, now=at + 2,
                       receipt={"exit_code": exit_code, "reason": reason, "duration_s": 1.0})
    return rp.finalize_outcome(store, row, policies.get(policy), breaker_threshold=THRESHOLD, now=at + 3)


def _dry_run_timeout(store, policies, minute: str, at: float):
    """The 2026-10-29T20:48:02Z row: a dry_run RUN_TIMEOUT (executor_lost) under policy `none`."""
    return _run(store, policies, minute, mode="dry_run", state="RUN_TIMEOUT", exit_code=None,
                reason="executor_lost", at=at, policy="none")


def test_dry_run_dead_letter_does_not_open_the_live_breaker(store, policies):
    """The incident: one 13-day-old dry_run timeout + two live failures must not open the live breaker."""
    dry = _dry_run_timeout(store, policies, "20261029T1645", at=T0 - 12 * DAY)
    assert dry.dead_letter is not None and not dry.breaker_opened
    out1 = _run(store, policies, "20261109T1645", at=T0 - DAY)
    out2 = _run(store, policies, "20261110T1645", at=T0)
    assert out1.consecutive_dead == 1 and not out1.breaker_opened
    assert out2.consecutive_dead == 2, "a dry_run dead letter is not a live consecutive failure"
    assert out2.breaker_opened is False
    assert store.breaker(LANE) is None
    assert store.consecutive_dead(LANE, "live") == 2
    assert store.consecutive_dead(LANE, "dry_run") == 1


def test_three_live_dead_slots_still_open_the_breaker_and_the_count_is_live_only(store, policies):
    """Narrowing the streak must not disarm the breaker for the live path it guards."""
    _dry_run_timeout(store, policies, "20261029T1645", at=T0 - 12 * DAY)
    outs = [_run(store, policies, m, at=T0 + 100 * i)
            for i, m in enumerate(("20261109T1645", "20261110T1645", "20261111T1645"))]
    assert [o.breaker_opened for o in outs] == [False, False, True]
    assert outs[-1].consecutive_dead == 3, "3 live dead slots, not 4: the dry_run one is not live"
    brk = store.breaker(LANE)
    assert brk is not None and brk["open"] and brk["consecutive"] == 3


def test_a_dry_run_lane_still_opens_its_breaker_on_three_dry_run_dead_slots(store, policies):
    """A lane whose dispatch mode is dry_run keeps its breaker: the streak is per mode, not live-only."""
    outs = [_dry_run_timeout(store, policies, m, at=T0 + 100 * i)
            for i, m in enumerate(("20261109T1645", "20261110T1645", "20261111T1645"))]
    assert [o.breaker_opened for o in outs] == [False, False, True]
    assert outs[-1].consecutive_dead == 3
    assert store.breaker(LANE)["open"] is True
    assert store.consecutive_dead(LANE, "dry_run") == 3
    assert store.consecutive_dead(LANE, "live") == 0  # no live dead slots


def test_a_dry_run_success_does_not_reset_the_live_streak(store, policies):
    """LQ-20261107-1333, which the deployed code carries and the base predates: only a live RUN_DONE resets."""
    _run(store, policies, "20261109T1645", at=T0)
    ok = _run(store, policies, "20261109T1700", mode="dry_run", state="RUN_DONE", exit_code=0, reason=None,
              at=T0 + 100, policy="none")
    assert ok.dead_letter is None
    assert store.consecutive_dead(LANE, "live") == 1


def test_a_dry_run_success_cannot_release_an_open_live_breaker(store, policies):
    """LQ-20261107-1896 M1 (LQ-1333's release guard): the reset half alone still lets `released_at` clear it.

    With the streak mode-scoped but the release guard missing, a dry_run RUN_DONE sets ``breakers.released_at``
    — and ``consecutive_dead``'s cutoff is ``max(last live RUN_DONE, released_at)`` — so the live streak goes
    3 -> 0 and the next live failure starts again at 1. This test opens the breaker first, so the release call
    is real; the earlier dry_run test never opens one and therefore passes either way.
    """
    outs = [_run(store, policies, m, at=T0 + 100 * i)
            for i, m in enumerate(("20261109T1645", "20261110T1645", "20261111T1645"))]
    assert [o.breaker_opened for o in outs] == [False, False, True]
    brk = store.breaker(LANE)
    assert brk is not None and brk["open"] is True and brk["consecutive"] == 3

    ok = _run(store, policies, "20261111T1700", mode="dry_run", state="RUN_DONE", exit_code=0, reason=None,
              at=T0 + 1000, policy="none")
    assert ok.dead_letter is None
    assert ok.breaker_closed is False, "a dry_run success must not release a live breaker"
    brk = store.breaker(LANE)
    assert brk is not None and brk["open"] is True
    assert brk["released_at"] is None and brk["released_by"] is None
    assert store.consecutive_dead(LANE, "live") == 3


def test_a_live_run_done_still_releases_an_open_breaker(store, policies):
    """The guard is not a blanket refusal: a live RUN_DONE is what releases, by ``auto:run_done``."""
    outs = [_run(store, policies, m, at=T0 + 100 * i)
            for i, m in enumerate(("20261109T1645", "20261110T1645", "20261111T1645"))]
    assert outs[-1].breaker_opened is True

    ok = _run(store, policies, "20261111T1700", mode="live", state="RUN_DONE", exit_code=0, reason=None,
              at=T0 + 1000, policy="none")
    assert ok.breaker_closed is True
    brk = store.breaker(LANE)
    assert brk is not None and brk["open"] is False and brk["released_by"] == "auto:run_done"
    assert store.consecutive_dead(LANE, "live") == 0


def test_the_streak_scope_must_be_named(store):
    """LQ-20261107-1891 N1: no default scope — omitting it is a TypeError, not a quiet wrong number."""
    with pytest.raises(TypeError):
        store.consecutive_dead(LANE)
    assert store.consecutive_dead(LANE, "live") == 0
    assert store.consecutive_dead(LANE, None) == 0  # the any-mode display count, still available explicitly
