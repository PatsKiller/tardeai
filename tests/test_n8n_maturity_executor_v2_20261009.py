"""Executor v2 (n8n maturity B5.5, design 02 §5, §3.4, F4/F10/F19).

Hermetic: tmp_path ledgers and state roots, a fake clock, gated fake runners (threading.Event per lane, so no
wall-clock races) and, for the end-to-end and reaper cases, real tiny subprocesses. Never touches the live
ledger, crontab, token store or Telegram."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import scheduler_operations as SO  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore, aged_priority  # noqa: E402
from scripts.lib.n8n_retry_policy import load_policies  # noqa: E402

T0 = 1_791_500_000.0
POLICIES = load_policies()


class Clock:
    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _wait(pred, timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > end:
            raise AssertionError("condition not reached before deadline")
        time.sleep(0.01)


class Gates:
    """Fake runner: blocks each run until its lane's gate is released, then returns the lane's exit code."""

    def __init__(self) -> None:
        self.events: dict[str, threading.Event] = {}
        self.codes: dict[str, int] = {}
        self.started: list[str] = []
        self.lock = threading.Lock()

    def gate(self, lane: str) -> threading.Event:
        with self.lock:
            return self.events.setdefault(lane, threading.Event())

    def release(self, lane: str) -> None:
        self.gate(lane).set()

    def factory(self, on_spawn, on_beat):
        def run(argv, *, timeout, env, cwd):
            lane = argv[argv.index("--lane") + 1]
            with self.lock:
                self.started.append(lane)
            on_spawn(os.getpid())
            assert self.gate(lane).wait(10), f"gate {lane} never released"
            return SimpleNamespace(returncode=self.codes.get(lane, 0), stdout="", stderr="")

        return run


def _entry(tmp_path: Path, lane: str, timeout_s: int = 60) -> dict:
    return {"lane_id": lane, "command": ["$PY", "scripts/fake.py", "--lane", lane],
            "lock": str(tmp_path / "locks" / f"{lane}.lock"), "timeout_s": timeout_s,
            "dry_run_arg": ["--dry-run"], "live_arg": ["--apply"]}


@pytest.fixture
def rig(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    store = LedgerRunStore(ledger)
    state = tmp_path / "state"
    state.mkdir()
    clock = Clock()
    gates = Gates()

    def make(allowlist: dict, workers: int = 3, **kw):
        return X.ExecutorV2(store, allowlist, env={"TRADEAI_VENV_PYTHON": sys.executable}, state_root=state,
                            code_root=tmp_path, workers=workers, policies=kw.pop("policies", POLICIES),
                            clock=clock, runner_factory=kw.pop("runner_factory", gates.factory),
                            worker_prefix="test", quiet=True, **kw)

    def request(run_id: str, lane: str, *, at: float | None = None, **kw):
        return store.request(run_id=run_id, lane_id=lane, mode="live", requested_by="t", caller_id="n8n-relay",
                             now=clock.t if at is None else at, **kw)

    yield SimpleNamespace(store=store, state=state, clock=clock, gates=gates, make=make, request=request,
                          tmp=tmp_path)
    for ev in gates.events.values():
        ev.set()
    ledger.close()


def _settle(ex) -> None:
    _wait(lambda: not ex.busy())


def _running_lanes(store) -> list[str]:
    return sorted(r["lane_id"] for r in store.list_running())


def _allow(tmp_path, *lanes, heavy=()):
    return {lane: _entry(tmp_path, lane, 1800 if lane in heavy else 60) for lane in lanes}


# ── per-lane lock, global cap, class caps, reserved worker ──────────────────────────────────────────────────────

def test_two_requested_rows_of_one_lane_never_run_together(rig):
    ex = rig.make(_allow(rig.tmp, "lane-a"))
    rig.request("run-a1-000000000001", "lane-a", priority=0)
    rig.request("run-a2-000000000002", "lane-a", priority=0, at=T0 + 1)
    assert ex.step() == 1 and _running_lanes(rig.store) == ["lane-a"]
    assert ex.step() == 0 and len(rig.store.list_running()) == 1
    rig.gates.release("lane-a")
    _settle(ex)
    assert rig.store.get("run-a1-000000000001")["state"] == "RUN_DONE"
    assert ex.step() == 1 and rig.store.get("run-a2-000000000002")["state"] in ("RUNNING", "RUN_DONE")
    _settle(ex)
    assert rig.store.get("run-a2-000000000002")["state"] == "RUN_DONE"


def test_global_cap_is_n_workers(rig):
    lanes = [f"lane-{i}" for i in range(5)]
    ex = rig.make(_allow(rig.tmp, *lanes), workers=3)
    for i, lane in enumerate(lanes):
        rig.request(f"run-g{i}-00000000000{i}", lane, priority=0, at=T0 + i)
    assert ex.step() == 3 and len(rig.store.list_running()) == 3
    st = ex.status(rig.clock())
    assert st["workers_busy"] == 3 and st["queue_total"] == 2
    for lane in lanes:
        rig.gates.release(lane)
    _settle(ex)
    ex.drain_until_idle(poll_s=0.01, deadline_s=10)
    assert all(r["state"] == "RUN_DONE" for r in rig.store.list(limit=10))


def test_two_heavy_lanes_serialize_while_a_report_lane_runs_beside_them(rig):
    ex = rig.make(_allow(rig.tmp, "heavy-1", "heavy-2", "rep-1", heavy=("heavy-1", "heavy-2")), workers=4)
    rig.request("run-h1-000000000001", "heavy-1", priority=0)
    rig.request("run-h2-000000000002", "heavy-2", priority=0, at=T0 + 1)
    rig.request("run-r1-000000000003", "rep-1", priority=0, at=T0 + 2)
    assert ex.step() == 2 and _running_lanes(rig.store) == ["heavy-1", "rep-1"]
    assert {s["class"] for s in ex.busy()} == {"heavy", "report"}
    rig.gates.release("heavy-1")
    _wait(lambda: rig.store.get("run-h1-000000000001")["state"] == "RUN_DONE")
    _wait(lambda: len(ex.busy()) == 1)
    assert ex.step() == 1 and "heavy-2" in _running_lanes(rig.store)
    for lane in ("heavy-2", "rep-1"):
        rig.gates.release(lane)
    _settle(ex)


def test_pipeline_class_cap_is_two_from_runs_class(rig):
    lanes = ["p-1", "p-2", "p-3"]
    ex = rig.make(_allow(rig.tmp, *lanes), workers=5)
    for i, lane in enumerate(lanes):
        rig.request(f"run-p{i}-00000000000{i}", lane, priority=0, klass="pipeline", at=T0 + i)
    assert ex.step() == 2 and _running_lanes(rig.store) == ["p-1", "p-2"]
    for lane in lanes:
        rig.gates.release(lane)
    _settle(ex)


def test_reserved_worker_takes_priority_zero_while_others_run_priority_five(rig):
    ex = rig.make(_allow(rig.tmp, "a", "b", "c", "watch"), workers=3)
    for i, lane in enumerate(("a", "b", "c")):
        rig.request(f"run-{lane}5-00000000000{i}", lane, priority=5, at=T0 + i)
    assert ex.step() == 2 and _running_lanes(rig.store) == ["a", "b"]  # c (p5) may not take the reserved worker
    rig.request("run-watch0-000000001", "watch", priority=0, at=T0 + 10)
    assert ex.step() == 1 and _running_lanes(rig.store) == ["a", "b", "watch"]
    assert rig.store.get("run-c5-000000000002")["state"] == "REQUESTED"
    reserved = [s for s in ex.busy() if s["lane_id"] == "watch"][0]
    assert reserved["priority"] == 0 and reserved["worker_id"] == "test:w2"
    for lane in ("a", "b", "c", "watch"):
        rig.gates.release(lane)
    _settle(ex)


def test_null_priority_defaults_to_five_and_null_class_derives_from_timeout(rig):
    ex = rig.make(_allow(rig.tmp, "big", heavy=("big",)), workers=2)
    rig.request("run-big-000000000001", "big")
    assert ex.step() == 1
    slot = ex.busy()[0]
    assert slot["class"] == "heavy" and slot["priority"] == 5
    rig.gates.release("big")
    _settle(ex)
    assert X.derived_class({"timeout_s": 1799}) == "report" and X.derived_class(None) == "report"


# ── priority aging (ledger) ──────────────────────────────────────────────────────────────────────────────────────

def test_aged_priority_formula():
    iso = datetime.fromtimestamp(T0, timezone.utc).isoformat()
    assert aged_priority(5, iso, T0) == 5
    assert aged_priority(5, iso, T0 + 299) == 5 and aged_priority(5, iso, T0 + 300) == 4
    assert aged_priority(5, iso, T0 + 900) == 2 and aged_priority(5, iso, T0 + 86400) == 2  # capped at 3
    assert aged_priority(5, "garbage", T0) == 5


def test_claim_orders_by_aged_priority_then_requested_at(rig):
    s = rig.store
    rig.request("run-old5-00000000001", "old5", priority=5, at=T0)           # waits 1200 s -> aged 2
    rig.request("run-new2-00000000002", "new2", priority=2, at=T0 + 1190)    # waits 10 s -> 2; younger
    rig.request("run-new1-00000000003", "new1", priority=1, at=T0 + 1195)    # 1: best
    now = T0 + 1200
    got = [s.claim_next_v2(worker_id="w", now=now)["lane_id"] for _ in range(3)]
    assert got == ["new1", "old5", "new2"]
    rig.request("run-x9-0000000000004", "x9", priority=9, at=now)
    rig.request("run-x3-0000000000005", "x3", priority=3, at=now + 1)
    assert s.claim_next_v2(worker_id="w", now=now + 1, max_priority=1) is None
    row = s.claim_next_v2(worker_id="w", now=now + 1, exclude_classes=("report",))
    assert row is None
    row = s.claim_next_v2(worker_id="w-7", now=now + 1)
    assert row["lane_id"] == "x3" and row["worker_id"] == "w-7" and row["heartbeat_at"] == row["started_at"]
    assert row["effective_class"] == "report" and row["effective_priority"] == 3


def test_v1_claim_next_is_unchanged_oldest_first(rig):
    rig.request("run-b-00000000000002", "b", priority=0, at=T0 + 5)
    rig.request("run-a-00000000000001", "a", priority=9, at=T0)
    assert rig.store.claim_next(now=T0 + 10)["lane_id"] == "a"


# ── reaper (F4) ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_reaper_finishes_a_dead_pid_with_stale_heartbeat_as_executor_lost_retryable(rig):
    ex = rig.make(_allow(rig.tmp, "lost"), workers=2)
    rig.request("run-lost-00000000001", "lost", slot_key="d:lost:live:20261009T1000", attempt=1)
    row = rig.store.claim_next_v2(worker_id="previous:w0", now=T0)
    child = subprocess.Popen(["sleep", "30"])
    try:
        assert rig.store.touch_heartbeat(row["run_id"], child.pid, T0 + 1)
        os.kill(child.pid, signal.SIGKILL)
        child.wait(5)
        assert ex.reap(T0 + 60) == []                       # heartbeat 59 s old: not stale yet
        reaped = ex.reap(T0 + 92)
    finally:
        if child.poll() is None:
            child.kill()
    assert [r["run_id"] for r in reaped] == ["run-lost-00000000001"]
    got = rig.store.get("run-lost-00000000001")
    assert got["state"] == "RUN_TIMEOUT" and got["verdict"] == "retryable"
    assert got["receipt"]["reason"] == "executor_lost" and got["receipt"]["schema"] == "RunReceipt@v2"
    assert got["receipt"]["worker_id"] == "previous:w0" and got["receipt"]["lost"]["pid"] == child.pid
    assert rig.store.list_dead_letters() == [] and ex.reaped_total == 1
    assert (rig.state / X.RUNS_REL / "run-lost-00000000001.json").is_file()


def test_reaper_spares_live_pids_until_overdue_and_never_reaps_its_own_workers(rig):
    alive = {"v": True}
    ex = rig.make(_allow(rig.tmp, "slow", "mine"), workers=2, pid_alive=lambda pid: alive["v"])
    rig.request("run-slow-00000000001", "slow")
    rig.store.claim_next_v2(worker_id="previous:w0", now=T0)
    rig.store.touch_heartbeat("run-slow-00000000001", 4242, T0)
    assert ex.reap(T0 + 120) == []                          # stale beat but pid alive, not overdue (60+120)
    assert [r["run_id"] for r in ex.reap(T0 + 181)] == ["run-slow-00000000001"]   # started + timeout + 120 < now
    assert rig.store.get("run-slow-00000000001")["receipt"]["lost"]["overdue"] is True
    alive["v"] = False
    rig.request("run-mine-00000000002", "mine", priority=0, at=T0 + 200)
    rig.clock.t = T0 + 200
    assert ex.step() == 1
    assert ex.reap(T0 + 10_000) == []                       # this process's live worker owns it
    rig.gates.release("mine")
    _settle(ex)
    assert rig.store.get("run-mine-00000000002")["state"] == "RUN_DONE"


def test_reaper_runs_at_start_on_a_v1_orphan_without_pid_or_heartbeat(rig):
    rig.request("run-orph-00000000001", "orph")
    rig.store.claim_next(now=T0)                            # a v1 executor died mid-run: no pid, no heartbeat
    rig.clock.t = T0 + 91
    ex = rig.make(_allow(rig.tmp, "orph"), workers=2)
    ex.step()
    got = rig.store.get("run-orph-00000000001")
    assert got["state"] == "RUN_TIMEOUT" and got["receipt"]["reason"] == "executor_lost"


# ── verdicts, DLQ, breaker ──────────────────────────────────────────────────────────────────────────────────────

def test_three_dead_slots_write_dead_letters_open_the_breaker_and_surface_findings(rig):
    ex = rig.make(_allow(rig.tmp, "poison"), workers=2)
    rig.gates.codes["poison"] = 2                           # exit 2 is terminal under transient-2
    rig.gates.release("poison")
    for i in range(3):
        rig.request(f"run-poison{i}-000000000", "poison", priority=0, slot_key=f"d:poison:live:20261009T10{i}0",
                    attempt=1, at=T0 + i)
        ex.drain_until_idle(poll_s=0.01, deadline_s=10)
    rows = [rig.store.get(f"run-poison{i}-000000000") for i in range(3)]
    assert [r["verdict"] for r in rows] == ["terminal"] * 3
    assert len(rig.store.list_dead_letters(lane_id="poison")) == 3
    assert rig.store.breaker("poison")["open"] is True
    st = json.loads((rig.state / X.LAST_REL).read_text())
    assert st["schema"] == "ExecutorStatus@v1" and st["dlq_24h"] == 3 and st["breakers_open"] == ["poison"]
    assert sorted(f["item"] for f in st["findings"]) == ["breaker:poison", "dlq:poison"]
    assert all(f["source"] == "dlq" and f["severity"] == "P2" for f in st["findings"])
    # release: the findings disappear (the fan-in closes them)
    for d in rig.store.list_dead_letters(lane_id="poison"):
        rig.store.release_dead_letter(d["slot_key"], "op", "fixed", T0 + 50)
    rig.store.release_breaker("poison", "op", T0 + 50)
    assert ex.status(T0 + 60)["findings"] == []


def test_retryable_until_max_attempts_then_dead(rig):
    ex = rig.make(_allow(rig.tmp, "flaky"), workers=2)
    rig.gates.codes["flaky"] = 75
    rig.gates.release("flaky")
    rig.request("run-flaky1-00000000a1", "flaky", priority=0, slot_key="d:flaky:live:20261009T1000", attempt=1)
    ex.drain_until_idle(poll_s=0.01, deadline_s=10)
    assert rig.store.get("run-flaky1-00000000a1")["verdict"] == "retryable" and rig.store.list_dead_letters() == []
    rig.request("run-flaky3-00000000a3", "flaky", priority=0, slot_key="d:flaky:live:20261009T1000", attempt=3,
                parent_run_id="run-flaky1-00000000a1", at=T0 + 1)
    ex.drain_until_idle(poll_s=0.01, deadline_s=10)
    dl = rig.store.get_dead_letter("d:flaky:live:20261009T1000")
    assert dl["attempts"] == 3 and dl["verdict"] == "retryable" and dl["last_run_id"] == "run-flaky3-00000000a3"
    r = rig.store.get("run-flaky3-00000000a3")["receipt"]
    assert r["attempt"] == 3 and r["parent_run_id"] == "run-flaky1-00000000a1" and r["retry_policy"] == "transient-2"


def test_resolve_retry_policy_default_and_registry_dispatch(monkeypatch):
    rows = [{"lane_id": "big", "dispatch": {"retry_policy": "transient-1-slow"}, "watch": {"severity": "P1"}},
            {"lane_id": "odd", "dispatch": {"retry_policy": "no-such-policy"}}]
    monkeypatch.setattr(X, "_dispatch_loader", lambda: None)
    assert X.resolve_retry_policy("big", POLICIES, rows).name == POLICIES.default_policy
    monkeypatch.setattr(X, "_dispatch_loader", lambda: (lambda row: row.get("dispatch")))
    assert X.resolve_retry_policy("big", POLICIES, rows).name == "transient-1-slow"
    assert X.resolve_retry_policy("odd", POLICIES, rows).name == POLICIES.default_policy
    assert X.resolve_retry_policy("absent", POLICIES, rows).name == POLICIES.default_policy
    assert X.resolve_retry_policy("big", POLICIES, None).name == POLICIES.default_policy
    assert X._lane_severity("big", rows) == "P1" and X._lane_severity("odd", rows) is None


# ── receipts, status, end to end with real subprocesses ─────────────────────────────────────────────────────────

@pytest.fixture
def bench(tmp_path, monkeypatch):
    code = tmp_path / "code"
    (code / "scripts").mkdir(parents=True)
    (code / "config").mkdir()
    shutil.copy(ROOT / "scripts" / "safe_flock.sh", code / "scripts" / "safe_flock.sh")
    shutil.copy(ROOT / "config" / "n8n_retry_policies.json", code / "config" / "n8n_retry_policies.json")
    (code / "GIT_SHA").write_text("e" * 40 + "\n")
    (code / "scripts" / "fake_lane.py").write_text(
        "import os, sys, time\n"
        "time.sleep(float(os.environ.get('FAKE_SLEEP', '0')))\n"
        "print('fake ' + ' '.join(sys.argv[1:]))\n"
        "sys.exit(int(os.environ.get('FAKE_EXIT', '0')))\n")
    state = tmp_path / "state"
    state.mkdir()
    (tmp_path / "locks").mkdir()
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setenv("SAFE_FLOCK_LOG_DIR", str(tmp_path / "flock-logs"))
    monkeypatch.setenv("TRADEAI_VENV_PYTHON", sys.executable)
    monkeypatch.delenv(X.WORKERS_ENV, raising=False)
    for k in ("FAKE_EXIT", "FAKE_SLEEP"):
        monkeypatch.delenv(k, raising=False)
    lanes = [{"lane_id": f"e2e-{i}", "command": ["$PY", "scripts/fake_lane.py", f"e2e-{i}"],
              "lock": str(tmp_path / "locks" / f"e2e-{i}.lock"), "timeout_s": 20,
              "dry_run_arg": ["--dry-run"], "live_arg": ["--apply"]} for i in range(3)]
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"schema": "N8nRunAllowlist@v1", "lanes": lanes}))
    yield SimpleNamespace(code=code, state=state, allow=allow, ledger=tmp_path / "ledger.sqlite")


def _main(bench, *extra) -> int:
    return X.main(["--once", "--ledger", str(bench.ledger), "--allowlist", str(bench.allow), "--code-root",
                   str(bench.code), "--state-root", str(bench.state), *extra])


def _req(bench, run_id, lane, **kw):
    ledger = CoordinationLedger(bench.ledger)
    try:
        LedgerRunStore(ledger).request(run_id=run_id, lane_id=lane, mode="live", requested_by="t",
                                       caller_id="n8n-relay", now=time.time() - 2, **kw)
    finally:
        ledger.close()


def _get(bench, run_id):
    ledger = CoordinationLedger(bench.ledger)
    try:
        return LedgerRunStore(ledger).get(run_id)
    finally:
        ledger.close()


def test_run_receipt_v2_end_to_end_with_real_subprocesses(bench):
    _req(bench, "run-e2e0-0000000000a", "e2e-0", slot_key="d:e2e-0:live:20261009T1000", attempt=1, priority=2,
         klass="monitor")
    _req(bench, "run-e2e1-0000000000b", "e2e-1")
    assert _main(bench, "--workers", "3") == 0
    row = _get(bench, "run-e2e0-0000000000a")
    r = row["receipt"]
    assert row["state"] == "RUN_DONE" and row["verdict"] == "ok" and row["pid"] and row["worker_id"]
    v1_fields = {"run_id", "lane_id", "mode", "exit_code", "duration_s", "lock_skipped", "timed_out", "output_signal",
                 "output_signal_mtime_before", "output_signal_mtime_after", "started_at", "finished_at", "code_sha",
                 "state", "reason", "argv", "stdout_tail", "stderr_tail", "authority"}
    v2_fields = {"slot_key", "attempt", "parent_run_id", "class", "priority", "worker_id", "queue_wait_s", "verdict",
                 "retry_policy"}
    assert v1_fields | v2_fields <= set(r) and r["schema"] == "RunReceipt@v2"
    assert (r["slot_key"], r["attempt"], r["class"], r["priority"], r["verdict"], r["retry_policy"]) == (
        "d:e2e-0:live:20261009T1000", 1, "monitor", 2, "ok", "transient-2")
    assert r["queue_wait_s"] >= 1.0 and r["worker_id"] == row["worker_id"] and "fake e2e-0 --apply" in r["stdout_tail"]
    per_run = json.loads((bench.state / X.RUNS_REL / "run-e2e0-0000000000a.json").read_text())
    assert per_run == r
    r1 = _get(bench, "run-e2e1-0000000000b")["receipt"]
    assert (r1["class"], r1["priority"], r1["attempt"], r1["slot_key"]) == ("report", 5, 1, None)
    assert SO.receipt_proves_run(_get(bench, "run-e2e1-0000000000b"), datetime.now(timezone.utc))
    st = json.loads((bench.state / X.LAST_REL).read_text())
    for key in ("schema", "as_of", "workers", "workers_busy", "busy", "queue_depth", "queue_total",
                "oldest_requested_age_s", "reaped_total", "dlq_24h", "breakers_open", "findings", "last_receipt"):
        assert key in st, key
    assert st["schema"] == "ExecutorStatus@v1" and st["workers"] == 3 and st["workers_busy"] == 0
    assert st["queue_total"] == 0 and st["oldest_requested_age_s"] is None and st["breakers_open"] == []
    # fan-in / migration board read the freshness as finished_at | as_of | at: as_of must parse and be now-ish
    assert "finished_at" not in st
    assert abs(datetime.fromisoformat(st["as_of"]).timestamp() - time.time()) < 60


def test_lanes_run_concurrently_with_real_subprocesses(bench, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "1.0")
    for i in range(2):
        _req(bench, f"run-par{i}-000000000{i}", f"e2e-{i}", priority=0)
    t = time.monotonic()
    assert _main(bench, "--workers", "3") == 0
    rows = [_get(bench, f"run-par{i}-000000000{i}") for i in range(2)]
    assert all(r["state"] == "RUN_DONE" for r in rows)
    a, b = (r["receipt"] for r in rows)
    assert a["started_at"] < b["finished_at"] and b["started_at"] < a["finished_at"]   # overlapped
    assert time.monotonic() - t < 10


# ── workers == 1 is the v1 serial path (rollback flag) ──────────────────────────────────────────────────────────

def test_workers_one_is_the_v1_path_with_run_receipt_v1(bench, monkeypatch):
    monkeypatch.setenv(X.WORKERS_ENV, "1")
    called = {"v1": 0}
    real = X.drain

    def spy(*a, **kw):
        called["v1"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(X, "drain", spy)
    monkeypatch.setattr(X, "ExecutorV2", lambda *a, **kw: pytest.fail("v2 must not start under workers=1"))
    _req(bench, "run-v1-00000000000a", "e2e-0", slot_key="d:e2e-0:live:20261009T1000", priority=0)
    assert _main(bench) == 0 and called["v1"] == 1
    row = _get(bench, "run-v1-00000000000a")
    r = row["receipt"]
    assert r["schema"] == "RunReceipt@v1" and "verdict" not in r and row["verdict"] is None and row["worker_id"] is None
    last = json.loads((bench.state / X.LAST_REL).read_text())
    assert last == r                                        # v1: the last file IS the last receipt


def test_bad_retry_policies_fall_back_to_the_v1_path(bench, capsys):
    (bench.code / "config" / "n8n_retry_policies.json").write_text("{}")
    _req(bench, "run-fb-00000000000a", "e2e-0")
    assert _main(bench, "--workers", "4") == 0
    assert _get(bench, "run-fb-00000000000a")["receipt"]["schema"] == "RunReceipt@v1"
    assert "v2_unavailable" in capsys.readouterr().out


def test_resolve_workers_flag_env_default_and_clamp():
    assert X.resolve_workers(None, {}) == 3
    assert X.resolve_workers(None, {X.WORKERS_ENV: "1"}) == 1
    assert X.resolve_workers(None, {X.WORKERS_ENV: "5"}) == 5
    assert X.resolve_workers(2, {X.WORKERS_ENV: "5"}) == 2
    assert X.resolve_workers(None, {X.WORKERS_ENV: "99"}) == 8 and X.resolve_workers(0, {}) == 1
    assert X.resolve_workers(None, {X.WORKERS_ENV: "three"}) == 3 and X.resolve_workers(None, {X.WORKERS_ENV: ""}) == 3
    with pytest.raises(ValueError):
        X.ExecutorV2(None, {}, env={}, state_root=Path("."), code_root=Path("."), workers=1, policies=POLICIES)


def test_workers_env_is_stripped_from_the_child_env():
    assert X.WORKERS_ENV not in X.child_env({X.WORKERS_ENV: "3", "PATH": "/bin"}, "any-lane")


def test_heartbeat_runner_reports_pid_and_beats_and_enforces_the_deadline(tmp_path):
    spawned, beats = [], []
    run = X.heartbeat_runner(spawned.append, beats.append, heartbeat_s=0.05)
    res = run([sys.executable, "-c", "import time; time.sleep(0.3); print('hi')"], timeout=10, env=dict(os.environ),
              cwd=tmp_path)
    assert res.returncode == 0 and res.stdout.strip() == "hi" and len(spawned) == 1 and beats
    assert set(beats) == set(spawned)
    with pytest.raises(subprocess.TimeoutExpired):
        run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.2, env=dict(os.environ), cwd=tmp_path)

