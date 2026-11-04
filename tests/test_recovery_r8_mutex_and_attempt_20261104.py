"""R8-F1 / R8-F2 — the two regressions the R7 settlement fix introduced (cx-openai-3, 2026-11-04).

R8-F1: `recovery_t1_release` stood down whenever the **global** reclaim mutex was busy. That mutex is
shared by every case, so contention from an unrelated case abandoned THIS case's release, the claim
survived, and the corrected retry was deduped for the whole 600 s lease — a recovery case existed and
nothing could page again.

R8-F2: `_RECOVERY_CLAIM_OWNERS` is keyed by case/day only, so a reclaimed attempt overwrote the token.
A stale attempt's settle then popped the NEWEST token, matched the lock, and released a page another
attempt was delivering. The mutex serialises filesystem operations; it cannot establish which attempt
a callback belongs to.

Both controls fail at 630014a98 and pass after the fix.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import recovery_notify as rn  # noqa: E402
import telegram_alert_router as router  # noqa: E402


def _case(**kw):
    base = {
        "symbol": "SPCX", "price": 141.65, "exit_price": 137.19, "pct_vs_exit": 3.3,
        "realized_loss_usd": -12770, "pre_exit_weight_pct": 2.25, "state": "RECOVERING",
        "next_trigger": "reclaims 151.62 20-day mean", "eligibility": "IRA now; taxable 11-27",
        "plan": "restore 800 shares in two tranches",
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "_RECOVERY_T1_PAGE_PATH", tmp_path / "recovery_t1_pages.jsonl")
    monkeypatch.setattr(router, "_RECOVERY_CLAIM_OWNERS", {}, raising=False)
    # The attempt token does not exist at the pre-fix head; the controls must run there too so they
    # can fail on behaviour rather than on an import-time attribute.
    attempt = getattr(router, "_RECOVERY_ATTEMPT", None)
    if attempt is not None:
        attempt.set(None)


def _hold_global_mutex():
    """Hold the reclaim mutex the way another case's settlement would."""
    status, fd = router._recovery_reclaim_guard()
    assert status == "ok", status
    return fd


def test_an_unrelated_holders_mutex_does_not_abandon_this_release(monkeypatch):
    """R8-F1: busy must not mean abandon — the claim is released and the retry can page again."""
    monkeypatch.setenv("TRADEAI_RECOVERY_MUTEX_WAIT_S", "0.2")
    msg = rn.build_message(_case(case_id="spcx-unrelated-holder"))
    assert router.recovery_t1_claim(msg) is True
    lock = router._recovery_claim_lock(router._budget_day(), router._recovery_case_key(msg))
    assert lock.exists()

    fd = _hold_global_mutex()
    try:
        router.recovery_t1_release(msg)          # the transport failed; the claim must go
    finally:
        os.close(fd)

    assert not lock.exists(), "the release was abandoned because an UNRELATED case held the mutex"
    assert router.recovery_t1_state(msg) == "released"
    assert router.recovery_t1_claim(msg) is True, "the corrected retry must be able to page again"


def test_an_unrelated_holders_mutex_does_not_strand_a_delivery(monkeypatch):
    """The same busy branch in recovery_t1_mark_delivered: delivery stays terminal and the lock frees."""
    monkeypatch.setenv("TRADEAI_RECOVERY_MUTEX_WAIT_S", "0.2")
    msg = rn.build_message(_case(case_id="spcx-unrelated-delivery"))
    assert router.recovery_t1_claim(msg) is True
    lock = router._recovery_claim_lock(router._budget_day(), router._recovery_case_key(msg))

    fd = _hold_global_mutex()
    try:
        router.recovery_t1_mark_delivered(msg)
    finally:
        os.close(fd)

    assert router.recovery_t1_state(msg) == "delivered"
    assert not lock.exists(), "the delivered page must free its lock even when the mutex is held elsewhere"


def test_a_stale_attempt_cannot_release_a_newer_claim():
    """R8-F2: the settle is bound to the attempt that owns it, not to whichever token is newest."""
    msg = rn.build_message(_case(case_id="spcx-stale-attempt"))
    assert router.recovery_t1_claim(msg) is True          # attempt A, token = A
    key = f"{router._budget_day()}\x00{router._recovery_case_key(msg)}"
    lock = router._recovery_claim_lock(router._budget_day(), router._recovery_case_key(msg))

    # Attempt B reclaimed the stale lock: the map now holds B's token, and A is still running.
    router._RECOVERY_CLAIM_OWNERS[key] = "attempt-b-token"

    router.recovery_t1_release(msg)                        # A's stale settle

    assert lock.exists(), "a stale attempt freed the lock of the attempt that now owns the case"
    assert router._RECOVERY_CLAIM_OWNERS.get(key) == "attempt-b-token", "the newer attempt lost its owner"
    assert router.recovery_t1_state(msg) != "released"


def test_the_owning_attempt_still_settles():
    """The control in the other direction: the attempt that owns the claim must still release it."""
    msg = rn.build_message(_case(case_id="spcx-owning-attempt"))
    assert router.recovery_t1_claim(msg) is True
    lock = router._recovery_claim_lock(router._budget_day(), router._recovery_case_key(msg))
    router.recovery_t1_release(msg)
    assert not lock.exists()
    assert router.recovery_t1_state(msg) == "released"


def test_the_mutex_wait_is_bounded(monkeypatch):
    """A held mutex must not block forever: the wait is bounded and returns busy."""
    import time as _time
    monkeypatch.setenv("TRADEAI_RECOVERY_MUTEX_WAIT_S", "0.2")
    fd = _hold_global_mutex()
    try:
        started = _time.monotonic()
        status, guard = router._recovery_reclaim_guard()
        elapsed = _time.monotonic() - started
    finally:
        os.close(fd)
    assert status == "busy" and guard is None
    assert elapsed < 2.0, f"the wait was not bounded ({elapsed:.2f}s)"

    # And it succeeds once the holder lets go, so contention is not a permanent failure.
    status, fd2 = router._recovery_reclaim_guard()
    assert status == "ok"
    os.close(fd2)


def test_two_threads_serialise_their_settles(tmp_path):
    """Two attempts settling concurrently: exactly one releases, and the map ends consistent."""
    msg = rn.build_message(_case(case_id="spcx-two-threads"))
    assert router.recovery_t1_claim(msg) is True
    results = []

    def settle():
        try:
            router.recovery_t1_release(msg)
            results.append("released")
        except Exception as exc:  # noqa: BLE001
            results.append(f"error:{type(exc).__name__}")

    threads = [threading.Thread(target=settle) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert len(results) == 2
    key = f"{router._budget_day()}\x00{router._recovery_case_key(msg)}"
    assert key not in router._RECOVERY_CLAIM_OWNERS or router._RECOVERY_CLAIM_OWNERS[key] is None
