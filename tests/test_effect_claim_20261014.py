"""Semantic effect key + owner-epoch fence (n8n fabric Phase 1, 2026-10-14; REFACTOR_PLAN addendum items 1-2).

The case a flock cannot stop: cron fires the 07:30 slot, finishes and drops its lock; ownership moves to n8n in the
same slot; n8n fires the 07:30 slot again. Both schedulers claim fx:<process>:<slot>:<version> in one durable table,
so the second live effect is refused (whichever came first), and the owner-epoch fence refuses a scheduler that is
not the owner, a stale epoch, and a run admitted before the current epoch. Hermetic: tmp_path ledgers, fake runners,
the CLI called in-process or as a child against a tmp ledger; never the live ledger, crontab or executor."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import effect_claim as E  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402
from scripts.lib.n8n_fabric_store import RunOutcomeStore  # noqa: E402

T0 = datetime(2026, 10, 14, 11, 30, tzinfo=timezone.utc).timestamp()  # 07:30 America/New_York
SLOT = "20261014T0730"
PROCESS = "morning-brief"
KEY = f"fx:{PROCESS}:{SLOT}:v1"
LANE = "fake-lane"
RUN_ID = f"d:{LANE}:live:{SLOT}"


@pytest.fixture
def led(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    yield SimpleNamespace(
        ledger=ledger,
        fx=E.EffectClaimStore(ledger),
        runs=LedgerRunStore(ledger),
        outcomes=RunOutcomeStore(ledger),
        path=tmp_path / "ledger.sqlite",
        tmp=tmp_path,
    )
    ledger.close()


def _entry(tmp_path: Path) -> dict:
    return {
        "lane_id": LANE,
        "command": ["$PY", "scripts/fake.py"],
        "lock": str(tmp_path / "fake.lock"),
        "timeout_s": 60,
        "dry_run_arg": ["--dry-run"],
        "live_arg": ["--apply"],
    }


class Runner:
    def __init__(self, code: int = 0, stderr: str = "") -> None:
        self.calls = 0
        self.code, self.stderr = code, stderr

    def __call__(self, argv, *, timeout, env, cwd):
        self.calls += 1
        return SimpleNamespace(returncode=self.code, stdout="", stderr=self.stderr)


def _gate(led, config=None, error=None, clock=lambda: T0 + 60):
    return X.EffectGate(
        led.fx,
        {LANE: {"process": PROCESS, "input_version": "v1"}} if config is None else config,
        config_error=error,
        clock=clock,
    )


def _n8n_run(led, run_id=RUN_ID, *, mode="live", requested_at=T0 + 30, runner=None, gate="default"):
    led.runs.request(run_id=run_id, lane_id=LANE, mode=mode, requested_by="t", caller_id="n8n-relay", now=requested_at)
    runner = runner or Runner()
    out = X.drain(
        led.runs,
        {LANE: _entry(led.tmp)},
        env={},
        state_root=led.tmp / "state",
        code_root=led.tmp,
        runner=runner,
        outcomes=led.outcomes,
        effects=_gate(led) if gate == "default" else gate,
    )
    return out[-1], runner


def _cli(led, *args) -> int:
    return E.main(["--ledger", str(led.path), *args])


# ── the key ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_effect_key_shape_and_validation():
    assert E.effect_key(PROCESS, SLOT, "v1") == KEY
    assert E.parse_effect_key(KEY) == (PROCESS, SLOT, "v1")
    for bad in (("Morning", SLOT, "v1"), (PROCESS, "07:30", "v1"), (PROCESS, SLOT, "v 1"), (PROCESS, "", "v1")):
        with pytest.raises(E.EffectKeyError):
            E.effect_key(*bad)
    assert E.parse_effect_key("fx:morning-brief:07:30:v1") is None


def test_slot_now_is_the_new_york_minute_of_a_d_key():
    assert E.slot_now(T0) == SLOT
    assert E.slot_now(datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc).timestamp()) == "20260105T0700"  # EST


# ── owner + fence ───────────────────────────────────────────────────────────────────────────────────────────────


def test_no_owner_row_fails_closed(led):
    res = led.fx.claim(KEY, scheduler="cron", now=T0)
    assert not res.ok and res.reason == "effect_no_owner"


def test_set_owner_is_a_compare_and_swap_on_the_epoch(led):
    row = led.fx.set_owner(PROCESS, "cron", expect_epoch=None, by="op", now=T0)
    assert row["owner"] == "cron" and row["epoch"] == 1
    with pytest.raises(E.EffectKeyError, match="epoch_conflict"):
        led.fx.set_owner(PROCESS, "n8n", expect_epoch=None, by="op", now=T0 + 1)
    with pytest.raises(E.EffectKeyError, match="epoch_conflict"):
        led.fx.set_owner(PROCESS, "n8n", expect_epoch=7, by="op", now=T0 + 1)
    assert led.fx.set_owner(PROCESS, "n8n", expect_epoch=1, by="op", now=T0 + 1)["epoch"] == 2


def test_fence_refuses_non_owner_stale_epoch_and_stale_admission(led):
    led.fx.set_owner(PROCESS, "n8n", expect_epoch=None, by="op", now=T0 + 10)
    assert led.fx.claim(KEY, scheduler="cron", now=T0 + 20).reason == "effect_fenced_owner"
    assert led.fx.claim(KEY, scheduler="n8n", now=T0 + 20, expect_epoch=2).reason == "effect_fenced_epoch"
    late = led.fx.claim(KEY, scheduler="n8n", now=T0 + 20, admitted_at=T0)  # admitted before epoch 1 began
    assert not late.ok and late.reason == "effect_fenced_stale_admission"
    assert led.fx.get(KEY) is None  # a fenced claim writes nothing
    assert led.fx.claim(KEY, scheduler="n8n", now=T0 + 20, admitted_at=T0 + 15, expect_epoch=1).ok


def test_owner_none_fences_admission_for_both_schedulers(led):
    led.fx.set_owner(PROCESS, "none", expect_epoch=None, by="op", now=T0)
    assert led.fx.claim(KEY, scheduler="cron", now=T0).reason == "effect_fenced_owner"
    assert led.fx.claim(KEY, scheduler="n8n", now=T0).reason == "effect_fenced_owner"


# ── claim lifecycle ─────────────────────────────────────────────────────────────────────────────────────────────


def test_failed_is_reclaimable_unknown_and_done_are_not(led):
    led.fx.set_owner(PROCESS, "cron", expect_epoch=None, by="op", now=T0)
    first = led.fx.claim(KEY, scheduler="cron", now=T0, run_id="r1")
    assert first.ok and first.attempt == 1
    assert led.fx.claim(KEY, scheduler="cron", now=T0, run_id="r2").reason == "effect_already_claimed"
    assert led.fx.finish(KEY, state="FAILED", now=T0 + 1, run_id="other") is None  # only the holder finishes
    assert led.fx.finish(KEY, state="FAILED", now=T0 + 1, run_id="r1")["state"] == "FAILED"
    # 2026-10-15 (audit DD05): a FAILED finish WITHOUT proof that it preceded the effect is held like UNKNOWN.
    unproven = led.fx.claim(KEY, scheduler="cron", now=T0 + 2, run_id="r2")
    assert unproven.reason == "effect_already_claimed" and unproven.holder["state"] == "FAILED"
    assert led.fx.release(KEY, by="op", now=T0 + 2, note="checked: no digest went out")["state"] == "RELEASED"
    second = led.fx.claim(KEY, scheduler="cron", now=T0 + 2, run_id="r2")
    assert second.ok and second.attempt == 2
    led.fx.finish(KEY, state="UNKNOWN", now=T0 + 3, run_id="r2")
    held = led.fx.claim(KEY, scheduler="cron", now=T0 + 4, run_id="r3")
    assert held.reason == "effect_already_claimed" and held.holder["state"] == "UNKNOWN"
    assert led.fx.release(KEY, by="op", now=T0 + 5, note="checked: no digest went out")["state"] == "RELEASED"
    third = led.fx.claim(KEY, scheduler="cron", now=T0 + 6, run_id="r3")
    assert third.ok and third.attempt == 3
    led.fx.finish(KEY, state="DONE", now=T0 + 7, run_id="r3")
    assert led.fx.release(KEY, by="op", now=T0 + 8, note="x") is None  # DONE is never released
    assert led.fx.claim(KEY, scheduler="cron", now=T0 + 9).reason == "effect_already_claimed"


def test_finish_marks_fenced_late_when_the_epoch_moved_during_the_run(led):
    led.fx.set_owner(PROCESS, "cron", expect_epoch=None, by="op", now=T0)
    led.fx.claim(KEY, scheduler="cron", now=T0, run_id="r1")
    led.fx.set_owner(PROCESS, "n8n", expect_epoch=1, by="op", now=T0 + 1)
    assert led.fx.finish(KEY, state="DONE", now=T0 + 2, run_id="r1")["fenced_late"] == 1


def test_concurrent_claims_of_one_key_admit_exactly_one(tmp_path):
    path = tmp_path / "ledger.sqlite"
    setup = CoordinationLedger(path)
    E.EffectClaimStore(setup).set_owner(PROCESS, "n8n", expect_epoch=None, by="op", now=T0)
    setup.close()
    results: list[bool] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        ledger = CoordinationLedger(path)  # one connection per thread, like separate processes
        try:
            res = E.EffectClaimStore(ledger).claim(KEY, scheduler="n8n", now=T0 + 1, run_id=f"r{i}")
        finally:
            ledger.close()
        with lock:
            results.append(res.ok)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1 and len(results) == 8


# ── the sequential duplicate a flock does not stop ──────────────────────────────────────────────────────────────


def test_sequential_cron_then_n8n_duplicate_is_refused(led, tmp_path):
    marker = tmp_path / "cron_effect.txt"
    assert _cli(led, "set-owner", "--process", PROCESS, "--owner", "cron", "--by", "test") == 0
    # 1. cron fires the 07:30 slot through the wrapper; the command runs and exits 0 (lock released after)
    rc = _cli(
        led,
        "run",
        "--process",
        PROCESS,
        "--slot",
        SLOT,
        "--input-version",
        "v1",
        "--scheduler",
        "cron",
        "--",
        sys.executable,
        "-c",
        f"open({str(marker)!r}, 'a').write('sent\\n')",
    )
    assert rc == 0 and marker.read_text() == "sent\n"
    assert led.fx.get(KEY)["state"] == "DONE" and led.fx.get(KEY)["scheduler"] == "cron"
    # 2. ownership moves to n8n in the same slot (one recorded act, epoch 1 -> 2)
    assert _cli(led, "set-owner", "--process", PROCESS, "--owner", "n8n", "--expect-epoch", "1", "--by", "test") == 0
    switched = led.fx.owner(PROCESS)
    # 3. n8n fires the same slot afterwards: no lock is held any more, but the key is
    receipt, runner = _n8n_run(led, requested_at=datetime.fromisoformat(switched["switched_at"]).timestamp() + 1)
    assert receipt["state"] == "RUN_REFUSED" and receipt["reason"] == "effect:effect_already_claimed"
    assert runner.calls == 0  # nothing spawned
    assert receipt["effect"]["key"] == KEY and receipt["effect"]["holder"]["scheduler"] == "cron"
    assert led.outcomes.get(RUN_ID)["status"] == "refused_policy"  # data for Run Lane, not an n8n error
    assert led.outcomes.get(RUN_ID)["effect_key"] == KEY
    assert marker.read_text() == "sent\n"  # exactly one effect


def test_without_the_effect_gate_the_same_sequence_would_run_twice(led):
    """The control: the run executor alone (lock only) runs the duplicate. This is the gap the key closes."""
    receipt, runner = _n8n_run(led, gate=None)
    assert receipt["state"] == "RUN_DONE" and runner.calls == 1


def test_sequential_n8n_then_cron_duplicate_is_refused(led, tmp_path):
    led.fx.set_owner(PROCESS, "n8n", expect_epoch=None, by="op", now=T0)
    receipt, runner = _n8n_run(led)
    assert receipt["state"] == "RUN_DONE" and runner.calls == 1
    assert receipt["effect"]["final_state"] == "DONE" and led.fx.get(KEY)["state"] == "DONE"
    led.fx.set_owner(PROCESS, "cron", expect_epoch=1, by="op", now=T0 + 120)  # rollback to cron, same slot
    marker = tmp_path / "cron_effect.txt"
    rc = _cli(
        led,
        "run",
        "--process",
        PROCESS,
        "--slot",
        SLOT,
        "--input-version",
        "v1",
        "--scheduler",
        "cron",
        "--",
        sys.executable,
        "-c",
        f"open({str(marker)!r}, 'w').write('x')",
    )
    assert rc == E.REFUSED_EXIT and not marker.exists()


def test_cli_run_finishes_failed_and_a_retry_may_claim_again(led, tmp_path):
    led.fx.set_owner(PROCESS, "cron", expect_epoch=None, by="op", now=T0)
    args = ["run", "--process", PROCESS, "--slot", SLOT, "--input-version", "v1", "--scheduler", "cron", "--"]
    # 2026-10-15 (audit DD05): an unfenced command's non-zero exit is NOT proof of no effect: the key is held.
    assert _cli(led, *args, sys.executable, "-c", "raise SystemExit(3)") == 3
    assert led.fx.get(KEY)["state"] == "FAILED" and led.fx.get(KEY)["pre_effect"] == 0
    assert _cli(led, *args, sys.executable, "-c", "pass") == 75  # held: operator release required
    led.fx.release(KEY, by="op", now=T0 + 1, note="checked the target: nothing written")
    # A --fenced command that exits before passing assert_fence() is proven pre-effect: FAILED stays reclaimable.
    fenced = ["run", "--process", PROCESS, "--slot", SLOT, "--input-version", "v1", "--scheduler", "cron", "--fenced",
              "--"]
    assert _cli(led, *fenced, sys.executable, "-c", "raise SystemExit(3)") == 3
    assert led.fx.get(KEY)["state"] == "FAILED" and led.fx.get(KEY)["pre_effect"] == 1
    assert _cli(led, *args, sys.executable, "-c", "pass") == 0
    assert led.fx.get(KEY)["state"] == "DONE" and led.fx.get(KEY)["attempt"] == 3


def test_cli_as_a_child_process_like_a_cron_line(led, tmp_path):
    led.fx.set_owner(PROCESS, "cron", expect_epoch=None, by="op", now=T0)
    base = [sys.executable, str(ROOT / "scripts" / "lib" / "effect_claim.py"), "--ledger", str(led.path)]
    key = subprocess.run(
        base + ["key", "--process", PROCESS, "--slot", SLOT, "--input-version", "v1"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert key.stdout.strip() == KEY
    first = subprocess.run(
        base + ["claim", "--process", PROCESS, "--slot", SLOT, "--input-version", "v1", "--scheduler", "cron"],
        capture_output=True,
        text=True,
    )
    second = subprocess.run(
        base + ["claim", "--process", PROCESS, "--slot", SLOT, "--input-version", "v1", "--scheduler", "cron"],
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0 and json.loads(first.stdout)["ok"] is True
    assert second.returncode == E.REFUSED_EXIT and json.loads(second.stdout)["reason"] == "effect_already_claimed"
    show = subprocess.run(
        base + ["show", "--process", PROCESS, "--key", KEY], capture_output=True, text=True, check=True
    )
    assert json.loads(show.stdout)["owner"]["owner"] == "cron"


# ── executor gate edges ─────────────────────────────────────────────────────────────────────────────────────────


def test_dry_run_and_unlisted_lanes_are_not_gated(led):
    receipt, runner = _n8n_run(led, run_id=f"d:{LANE}:dry_run:{SLOT}", mode="dry_run")
    assert receipt["state"] == "RUN_DONE" and "effect" not in receipt and runner.calls == 1
    receipt, runner = _n8n_run(led, run_id="d:other-lane:live:20261014T0731", gate=_gate(led, config={}))
    assert "effect" not in receipt


def test_live_run_without_a_slot_key_is_refused(led):
    led.fx.set_owner(PROCESS, "n8n", expect_epoch=None, by="op", now=T0)
    receipt, runner = _n8n_run(led, run_id="n8n-wf-free-form-key-0001")
    assert receipt["state"] == "RUN_REFUSED" and receipt["reason"] == "effect:effect_slot_unknown"
    assert runner.calls == 0


def test_unreadable_effect_config_fails_every_live_run_closed(led, tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "n8n_effect_keys.json").write_text("{not json")
    gate = X.EffectGate.from_ledger(led.ledger, tmp_path)
    assert gate.config_error == "effect_config_unreadable"
    receipt, runner = _n8n_run(led, run_id="d:any-lane:live:20261014T0730", gate=gate)
    assert receipt["state"] == "RUN_REFUSED" and receipt["reason"] == "effect:effect_config_unreadable"
    assert runner.calls == 0


def test_committed_effect_config_changes_no_live_run_at_merge():
    # 2026-10-15: the three hermes-learning process step lanes opted in (n8n fabric process, packet
    # n8n-hermes-learning-flow-20261015). None can run live: allowlist live_arg null and registry stage shadow (the
    # executor clamps to dry_run before the effect gate, which is inert for dry_run); the cron runner claims nothing
    # (cron_claim false). Any other lane opting in is a reviewed cutover PR that updates this pin.
    cfg = E.load_effect_config(ROOT / "config" / "n8n_effect_keys.json")
    assert set(cfg) == {
        "hermes-learning-outcome-grader",
        "hermes-learning-outcome-learning",
        "hermes-learning-config-governor",
        # 2026-10-15 unblock (n8nfab/hermes-learning-unblock-20261015): three more shadow step lanes.
        "hermes-learning-tag-engine",
        "hermes-learning-outcome-feedback-agent",
        "hermes-learning-autonomous-self-tune",
    }
    allow = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
    reg = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]}
    raw = json.loads((ROOT / "config" / "n8n_effect_keys.json").read_text())["lanes"]
    for lane, spec in cfg.items():
        assert spec["process"] == lane and allow[lane]["live_arg"] is None
        assert reg[lane]["scheduler"]["stage"] == "shadow"
        # hermes-learning cutover PR-1 (2026-10-15): the five learn step lanes set cron_claim true (the runner claims
        # only when its cron line also sets PIPELINE_EFFECT_CLAIM=1); the tune lane stays false
        assert raw[lane]["cron_claim"] is (lane != "hermes-learning-autonomous-self-tune")


def test_missing_effect_config_is_an_empty_map(tmp_path):
    assert E.load_effect_config(tmp_path / "absent.json") == {}


@pytest.mark.parametrize(
    "code,stderr,final",
    [
        (124, "", "UNKNOWN"),  # timeout: the effect may have happened
        (0, "safe_flock: skipped (pid 9 running)", "RELEASED"),  # nothing ran
        (2, "", "FAILED"),
    ],
)
def test_attempt_state_maps_to_the_claim_state(led, code, stderr, final):
    led.fx.set_owner(PROCESS, "n8n", expect_epoch=None, by="op", now=T0)
    receipt, _runner = _n8n_run(led, runner=Runner(code, stderr))
    assert receipt["effect"]["final_state"] == final and led.fx.get(KEY)["state"] == final


def test_stale_admission_through_the_executor(led):
    led.fx.set_owner(PROCESS, "cron", expect_epoch=None, by="op", now=T0)
    led.fx.set_owner(PROCESS, "n8n", expect_epoch=1, by="op", now=T0 + 100)
    receipt, runner = _n8n_run(led, requested_at=T0 + 50)  # requested under the old (cron) epoch
    assert receipt["reason"] == "effect:effect_fenced_stale_admission" and runner.calls == 0
