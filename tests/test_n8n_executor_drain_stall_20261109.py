"""LQ-20261107-1685: one in-flight run must not halt every new run start for an hour.

ANCHOR: EXECUTOR_DRAIN_STALL_LQ1685_20261109

Measured 2026-11-09, live ledger (``runs.started_at``) and the executor journal:

* 14:22:22 ET a deploy wrote ExecutorDrainRequest -> 60433ef3e. The executor stopped claiming
  (``started = 0 if draining else fill()``), and no run started until 15:10:18 (gap 2894 s,
  disk-hygiene in flight since 14:19).
* 14:57:16 ET a second promote (21143c85d) rewrote the same request file with a fresh
  ``requested_at``, which moved ``deadline_at`` from 15:03:43 to 15:37:16, so the backstop never
  fired.
* 15:36 ET the next promote repeated it: 15:23:51 -> 15:52:41 (gap 1730 s).

The pin (operator-approved design A + D + E):

A. While draining the old executor keeps claiming (rolling intake) and enters a FINAL drain
   (intake off) only when every in-flight run is predicted to end within 150 s. The final drain
   is hard-capped at 180 s and re-opens intake when the prediction misses, so the executor
   never forces and never reaps ``executor_lost``.
D. A rewritten request keeps the earliest ``requested_at`` and the largest ``deadline_s``; the
   deadline covers the longest in-flight lane timeout plus ``lost_grace_s`` (floor 2400 s).
E. The deploy helper refuses to ask for a drain in market hours (09:30-16:15 ET, trading day)
   while a run older than 300 s is in flight; the deploy never falls back to a plain restart.

Hermetic: temporary ledgers, release dirs and state roots, a fake clock, fake runners. Never
touches the live ledger, systemd, Telegram or a release tree. AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import n8n_executor_drain as D  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402
from scripts.lib.n8n_retry_policy import load_policies  # noqa: E402

T0 = 1_791_600_000.0
POLICIES = load_policies()
ET = timezone(timedelta(hours=-5))

SHORT = ("sweep", "enrich", "audit", "refresh", "digest", "probe")
DISK = "disk-hygiene"
#: history the executor's predictor reads: disk-hygiene p95 3000 s; the incident run took 3114 s.
DISK_HISTORY_S = 3000.0
DISK_RUN_S = 3114.0


class Clock:
    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class Scripted:
    """A runner that holds each run until the fake clock reaches its scripted end."""

    def __init__(self, clock: Clock, durations: dict[str, float]) -> None:
        self.clock, self.durations = clock, durations
        self.starts: list[tuple[float, str]] = []
        self.ends: list[tuple[float, str]] = []
        self.lock = threading.Lock()

    def factory(self, on_spawn, on_beat):
        def run(argv, *, timeout, env, cwd):
            lane = argv[argv.index("--lane") + 1]
            end = self.clock.t + float(self.durations.get(lane, 5.0))
            with self.lock:
                self.starts.append((self.clock.t, lane))
            on_spawn(os.getpid())
            while self.clock.t < end:
                on_beat(os.getpid())  # fake-clock heartbeat: the reaper must never see a stale row
                time.sleep(0.0005)
            with self.lock:
                self.ends.append((self.clock.t, lane))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        return run


def _entry(tmp: Path, lane: str, timeout_s: float) -> dict:
    return {
        "lane_id": lane,
        "command": ["$PY", "scripts/fake.py", "--lane", lane],
        "lock": str(tmp / "locks" / f"{lane}.lock"),
        "timeout_s": timeout_s,
        "dry_run_arg": ["--dry-run"],
        "live_arg": ["--apply"],
        "market_gate": False,
    }


@pytest.fixture
def rig(tmp_path):
    old, new = tmp_path / "rel-old", tmp_path / "rel-new"
    old.mkdir()
    new.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    store = LedgerRunStore(ledger)
    clock = Clock()
    allow = {lane: _entry(tmp_path, lane, 60) for lane in SHORT}
    allow[DISK] = _entry(tmp_path, DISK, 3600)
    yield SimpleNamespace(
        tmp=tmp_path, rel_old=old, rel_new=new, state=state, ledger=ledger, store=store, clock=clock, allow=allow
    )
    ledger.close()


def _seed_history(store: LedgerRunStore, clock: Clock, lane: str, duration_s: float, n: int = 10) -> None:
    """Completed runs the predictor reads (7-day window), one per hour going back."""
    for i in range(1, n + 1):
        at = clock.t - i * 3600.0
        run_id = f"seed-{lane}-{i:04d}"
        store.request(run_id=run_id, lane_id=lane, mode="live", requested_by="seed", caller_id="n8n-relay", now=at)
        store.claim_next(now=at)
        store.finish(
            run_id,
            state="RUN_DONE",
            receipt={"duration_s": duration_s, "finished_at": datetime.fromtimestamp(at + duration_s, timezone.utc).isoformat()},
            now=at + duration_s,
        )


def _executor(rig, *, code_root: Path, runner: Scripted, config: dict | None = None) -> X.ExecutorV2:
    return X.ExecutorV2(
        rig.store,
        rig.allow,
        env={"TRADEAI_VENV_PYTHON": sys.executable},
        state_root=rig.state,
        code_root=code_root,
        workers=4,
        policies=POLICIES,
        clock=rig.clock,
        runner_factory=runner.factory,
        worker_prefix="test",
        quiet=True,
        registry_rows=[{"lane_id": lane, "dispatch": {"retry_policy": "transient-2"}} for lane in rig.allow],
        sleeper=lambda s: None,
        config=config,
    )


def _simulate_drain_stall(rig, *, end_s: float = 4000.0) -> dict:
    """The 14:22 incident, replayed: cron traffic + one 3114 s disk-hygiene run + four promotes.

    Deterministic lockstep: the fake clock advances 5 s per tick and the executor is stepped by
    this loop (``serve()`` only adds a real sleep). On ``drained`` the next executor is a fresh
    process on the last target 10 s later, exactly as Restart=always does.
    """
    dt = 5.0
    for lane in SHORT:
        _seed_history(rig.store, rig.clock, lane, 3.0)
    _seed_history(rig.store, rig.clock, DISK, DISK_HISTORY_S)

    runner = Scripted(rig.clock, {DISK: DISK_RUN_S})
    targets = {
        60.0: rig.tmp / "rel-a",
        1000.0: rig.tmp / "rel-b",
        2100.0: rig.tmp / "rel-c",
        2140.0: rig.tmp / "rel-d",
    }
    for t in targets.values():
        t.mkdir()
    code_root = rig.rel_old
    ex = _executor(rig, code_root=code_root, runner=runner)
    generations = [code_root]

    # the incident run starts at T0
    rig.store.request(run_id="run-disk-000001", lane_id=DISK, mode="live", requested_by="cron",
                      caller_id="n8n-relay", now=rig.clock.t)
    next_slot = 0.0
    fired: set[float] = set()
    drained_at: list[float] = []
    restart_at: float | None = None
    drained_result: list[str] = []

    while rig.clock.t < T0 + end_s:
        rig.clock.t += dt
        now_rel = rig.clock.t - T0
        while next_slot <= now_rel:  # cron-shaped: every short lane every 60 s
            for lane in SHORT:
                rig.store.request(run_id=f"run-{lane}-{int(next_slot):06d}", lane_id=lane, mode="live",
                                  requested_by="cron", caller_id="n8n-relay", now=rig.clock.t)
            next_slot += 60.0
        for at, target in targets.items():
            if now_rel >= at and at not in fired:
                fired.add(at)
                D.write_request(rig.state, target, now=rig.clock.t, deadline_s=D.DEFAULT_DEADLINE_S)
        ex.step()
        done = ex.drain_done()
        if done:
            drained_at.append(rig.clock.t)
            drained_result.append(done)
            restart_at = rig.clock.t + 10.0  # RestartSec
            code_root = targets[max(fired)] if fired else rig.rel_old  # CURRENT at restart
            generations.append(code_root)
            ex = _executor(rig, code_root=code_root, runner=runner)
            rig.clock.t = restart_at
        time.sleep(0.0002)

    starts = [t for t, _ in runner.starts]
    gaps = [(b - a, a, b) for a, b in zip(starts, starts[1:])]
    return {
        "starts": starts,
        "gaps": gaps,
        "generations": generations,
        "drained_at": drained_at,
        "drained_result": drained_result,
        "store": rig.store,
        "runner": runner,
    }


def _replay(tmp: Path) -> dict:
    """One hermetic replay of the incident; shared by the four assertions below (it costs ~12 s)."""
    old, new = tmp / "rel-old", tmp / "rel-new"
    old.mkdir()
    new.mkdir()
    state = tmp / "state"
    state.mkdir()
    ledger = CoordinationLedger(tmp / "ledger.sqlite")
    store = LedgerRunStore(ledger)
    allow = {lane: _entry(tmp, lane, 60) for lane in SHORT}
    allow[DISK] = _entry(tmp, DISK, 3600)
    rig = SimpleNamespace(
        tmp=tmp, rel_old=old, rel_new=new, state=state, ledger=ledger, store=store, clock=Clock(), allow=allow
    )
    sim = _simulate_drain_stall(rig)
    sim["ledger"] = ledger
    return sim


@pytest.fixture(scope="module")
def sim(tmp_path_factory):
    out = _replay(tmp_path_factory.mktemp("lq1685-replay"))
    yield out
    out["ledger"].close()


def test_a_drain_never_halts_new_run_starts_for_more_than_the_final_drain(sim):
    gap, before, after = max(sim["gaps"], key=lambda g: g[0])
    # the cap is checked on the executor's own tick, so a gap is at most the cap plus one tick (and the
    # 10 s restart after a hand-over); anything larger means intake was off while a long run was in flight.
    assert gap <= X.FINAL_DRAIN_CAP_S + 20.0, (
        f"longest start gap {gap:.0f} s (T0+{before - T0:.0f} -> T0+{after - T0:.0f}); "
        f"targets fired: {[t - T0 for t in sim['drained_at']]}"
    )


def test_a_the_incident_run_finishes_and_nothing_is_reaped_as_lost(sim):
    assert sim["store"].get("run-disk-000001")["state"] == "RUN_DONE"
    for state in ("RUN_TIMEOUT", "RUN_FAILED"):
        for row in sim["store"].list(state=state):
            receipt = row.get("receipt") or {}
            assert receipt.get("reason") != "executor_lost", row
    assert sim["store"].list(state="RUNNING") == []


def test_a_the_p95_miss_reopens_intake_before_the_long_run_ends(sim):
    """A run longer than its p95 must not freeze starts for the rest of its life (the cap re-opens)."""
    ends = [t for t, lane in sim["runner"].ends if lane == DISK]
    assert ends, "the disk-hygiene run never finished"
    disk_end = ends[0]
    reopened = [t for t in sim["starts"] if T0 + DISK_HISTORY_S < t < disk_end]
    assert reopened, f"no run started between the p95 ({T0 + DISK_HISTORY_S:.0f}) and the end ({disk_end:.0f})"


def test_a_the_final_executor_runs_the_last_promoted_release(sim):
    assert sim["generations"][-1].name == "rel-d"
    assert len(sim["generations"]) >= 2, "the executor never handed over"
    assert sim["drained_result"][0] == "drained"


# ── D: a rewritten request never moves the deadline later ────────────────────────────────────────────────────


def test_d_a_rewritten_request_keeps_the_earliest_requested_at(rig):
    first = rig.tmp / "rel-a"
    second = rig.tmp / "rel-b"
    first.mkdir()
    second.mkdir()
    D.write_request(rig.state, first, now=T0, deadline_s=2400)
    D.write_request(rig.state, second, now=T0 + 2000, deadline_s=2400)
    req = D.read_request(rig.state)
    assert req["requested_at"] == T0, "a rewrite moved the deadline later (the 14:57 defect)"
    assert req["target"] == str(second.resolve()), "the rewrite must retarget the drain"
    assert D.drain_state(rig.state, rig.rel_old, T0 + 2399)["forced"] is False
    assert D.drain_state(rig.state, rig.rel_old, T0 + 2400)["forced"] is True


def test_d_a_rewrite_never_shortens_the_backstop(rig):
    target = rig.tmp / "rel-a"
    target.mkdir()
    D.write_request(rig.state, target, now=T0, deadline_s=5000)
    D.write_request(rig.state, target, now=T0 + 10, deadline_s=100)
    req = D.read_request(rig.state)
    assert req["deadline_s"] == 5000 and req["requested_at"] == T0


def test_d_an_expired_request_starts_a_fresh_epoch(rig):
    old, new = rig.tmp / "rel-a", rig.tmp / "rel-b"
    old.mkdir()
    new.mkdir()
    D.write_request(rig.state, old, now=T0)
    D.write_request(rig.state, new, now=T0 + D.MAX_AGE_S + 1)
    req = D.read_request(rig.state)
    assert req["requested_at"] == T0 + D.MAX_AGE_S + 1 and req["target"] == str(new.resolve())


def test_d_the_deadline_covers_the_longest_in_flight_timeout():
    doc = {"lanes": [{"lane_id": DISK, "timeout_s": 3600}, {"lane_id": "sweep", "timeout_s": 60}]}
    busy = [{"lane_id": DISK}, {"lane_id": "sweep"}]
    assert D.deadline_for(busy, doc, lost_grace_s=120) == 3720.0
    assert D.deadline_for([], doc, lost_grace_s=120) == D.DEFAULT_DEADLINE_S
    assert D.deadline_for([{"lane_id": "unknown"}], doc, lost_grace_s=120) == 3720.0


def _wait(pred, timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > end:
            raise AssertionError("condition not reached before deadline")
        time.sleep(0.01)


def test_d_a_run_that_outlived_its_p95_still_postpones_the_force(rig):
    """LQ-20261107-1685 (D): the p95 predicts the final drain; it never decides a forced exit.

    disk-hygiene's 7-day p95 is 2947 s and the 2026-11-09 run took 3114 s. A backstop judged against the p95
    would have declared it finished and forced, killing a live child — the executor_lost the whole item is
    about. The extension runs to the lane's own timeout (its worker's kill switch), never to the p95."""
    _seed_history(rig.store, rig.clock, "sweep", 20.0)  # p95 20 s, allowlist timeout_s 60 s
    runner = Scripted(rig.clock, {"sweep": 50.0})
    ex = _executor(rig, code_root=rig.rel_old, runner=runner)
    rig.store.request(run_id="run-sweep-00000000009", lane_id="sweep", mode="live", requested_by="cron",
                      caller_id="n8n-relay", now=rig.clock.t)
    ex.step()
    _wait(lambda: runner.starts)
    rig.clock.t += 31.0  # past the p95, inside the timeout
    D.write_request(rig.state, rig.rel_new, now=rig.clock.t - 30.0, deadline_s=30)  # deadline passed at +31
    ex.step()
    draining = ex.status(rig.clock.t)["draining"]
    assert draining["forced"] is False and draining.get("deadline_extended") is True
    assert draining["deadline_at"] >= rig.clock.t + 20.0, "the extension must outlive the run's own timeout"
    rig.clock.t += 60.0
    assert ex.serve(poll_s=0.01) == "drained"
    assert rig.store.get("run-sweep-00000000009")["state"] == "RUN_DONE"


# ── E: activation guard ──────────────────────────────────────────────────────────────────────────────────────


def _status_with_busy(state: Path, lane: str, age_s: float, now: float) -> None:
    p = state / D.STATUS_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.fromtimestamp(now - age_s, timezone.utc).isoformat()
    p.write_text(json.dumps({"busy": [{"lane_id": lane, "started_at": started, "run_id": "r1"}], "draining": None}))


def _trading_day(_d) -> bool:
    return True


def test_e_the_guard_refuses_while_a_long_run_is_in_flight_in_market_hours(rig):
    now = datetime(2026, 11, 9, 10, 0, tzinfo=ET).timestamp()  # a Monday, 10:00 ET
    _status_with_busy(rig.state, DISK, 400.0, now)
    doc = {"lanes": [{"lane_id": DISK, "timeout_s": 3600}]}
    refusal = D.market_guard(D.read_status(rig.state), now=now, allowlist=doc, trading_day=_trading_day)
    assert refusal is not None
    assert refusal["lane_id"] == DISK and refusal["age_s"] == pytest.approx(400.0, abs=1.0)
    assert refusal["predicted_end_s"] == pytest.approx(3200.0, abs=2.0)


@pytest.mark.parametrize("hour_et", [8, 17, 20])
def test_e_the_guard_allows_a_drain_outside_market_hours(rig, hour_et):
    now = datetime(2026, 11, 9, hour_et, 0, tzinfo=ET).timestamp()
    _status_with_busy(rig.state, DISK, 400.0, now)
    doc = {"lanes": [{"lane_id": DISK, "timeout_s": 3600}]}
    assert D.market_guard(D.read_status(rig.state), now=now, allowlist=doc, trading_day=_trading_day) is None


def test_e_the_guard_allows_a_drain_when_nothing_is_long_in_flight(rig):
    now = datetime(2026, 11, 9, 10, 0, tzinfo=ET).timestamp()
    _status_with_busy(rig.state, "sweep", 120.0, now)
    doc = {"lanes": [{"lane_id": "sweep", "timeout_s": 60}]}
    assert D.market_guard(D.read_status(rig.state), now=now, allowlist=doc, trading_day=_trading_day) is None


def test_e_the_guard_allows_a_drain_on_a_non_trading_day(rig):
    now = datetime(2026, 11, 14, 10, 0, tzinfo=ET).timestamp()  # a Saturday
    _status_with_busy(rig.state, DISK, 400.0, now)
    doc = {"lanes": [{"lane_id": DISK, "timeout_s": 3600}]}
    assert D.market_guard(D.read_status(rig.state), now=now, allowlist=doc, trading_day=lambda d: False) is None


def test_e_the_helper_exits_three_and_names_the_run(rig):
    now = datetime(2026, 11, 9, 10, 0, tzinfo=ET).timestamp()
    _status_with_busy(rig.state, DISK, 400.0, now)
    (rig.tmp / "rel-new").mkdir(exist_ok=True)
    allow_path = rig.tmp / "allow.json"
    allow_path.write_text(json.dumps({"lanes": [{"lane_id": DISK, "timeout_s": 3600}]}))
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "n8n_executor_drain.py"), "request",
         "--target", str(rig.tmp / "rel-new"), "--state-root", str(rig.state),
         "--allowlist", str(allow_path), "--no-systemd", "--now", str(now), "--wait-s", "0", "--ack-s", "0"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 3, r.stdout + r.stderr
    assert "DRAIN_RESULT=refused_market_busy" in r.stdout
    assert DISK in r.stdout
    assert not D.request_path(rig.state).exists(), "a refused activation must not write a drain request"


def test_e_the_deploy_refuses_without_falling_back_to_a_restart():
    body = (ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh").read_text()
    fn = body[body.index("restart_root_frozen_units() {") :]
    fn = fn[: fn.index("\n}\n")]
    arm = fn[fn.index("refused_market_busy)") : fn.index("refused_market_busy)") + 600]
    assert "continue" in arm.split(";;")[0], "the refused arm must skip the restart"
    assert "--refused" in fn
    assert fn.index("refused_market_busy)") < fn.index('systemctl --user restart "$u"')
