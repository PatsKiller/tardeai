"""LQ-20261107-137: a release promote drains the n8n run executor instead of killing its in-flight runs.

Hermetic: tmp_path ledgers, release dirs and state roots, a fake clock, gated fake runners. Never touches the
live ledger, systemd, the release tree or Telegram.

AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import n8n_executor_drain as D  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402
from scripts.lib.n8n_retry_policy import load_policies  # noqa: E402

T0 = 1_791_500_000.0
POLICIES = load_policies()


# ── the request file ────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def releases(tmp_path):
    old, new = tmp_path / "rel-old", tmp_path / "rel-new"
    old.mkdir()
    new.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    return SimpleNamespace(old=old, new=new, state=state, tmp=tmp_path)


def test_no_request_means_no_drain(releases):
    assert D.drain_state(releases.state, releases.old, T0) is None


def test_request_for_another_release_drains_the_old_executor(releases):
    D.write_request(releases.state, releases.new, now=T0, deadline_s=100)
    d = D.drain_state(releases.state, releases.old, T0 + 5)
    assert d is not None and d["target"] == str(releases.new.resolve()) and d["forced"] is False
    assert D.drain_state(releases.state, releases.old, T0 + 100)["forced"] is True


def test_request_is_inert_for_the_executor_already_on_target(releases):
    D.write_request(releases.state, releases.new, now=T0)
    assert D.drain_state(releases.state, releases.new, T0 + 5) is None


@pytest.mark.parametrize(
    "body",
    ["not json", json.dumps({"schema": "Other@v1"}), json.dumps({"schema": D.SCHEMA, "target": "x"}), "[]"],
)
def test_unreadable_or_malformed_request_fails_open(releases, body):
    p = D.request_path(releases.state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    assert D.drain_state(releases.state, releases.old, T0) is None


def test_old_or_pointless_request_is_ignored(releases):
    D.write_request(releases.state, releases.new, now=T0)
    assert D.drain_state(releases.state, releases.old, T0 + D.MAX_AGE_S + 1) is None
    D.write_request(releases.state, releases.tmp / "retired-release", now=T0)
    assert D.drain_state(releases.state, releases.old, T0 + 1) is None


# ── the deploy-side wait ──────────────────────────────────────────────────────────────────────────────────────


class Tick:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def test_wait_returns_re_resolved_when_the_executor_restarts_itself(releases):
    tick = Tick()
    seen = iter([False, False, True])
    draining = {"draining": {"target": str(releases.new.resolve())}}
    r = D.wait_for_drain(
        releases.state,
        releases.new,
        on_target=lambda: next(seen),
        clock=tick,
        sleeper=tick.sleep,
        status_reader=lambda: draining,
    )
    assert r == D.RESULT_RE_RESOLVED


def test_wait_reports_not_acknowledged_for_an_executor_that_predates_the_drain(releases):
    tick = Tick()
    r = D.wait_for_drain(
        releases.state,
        releases.new,
        on_target=lambda: False,
        ack_s=10,
        wait_s=90,
        clock=tick,
        sleeper=tick.sleep,
        status_reader=lambda: {"workers_busy": 1},
    )
    assert r == D.RESULT_NOT_ACKED and tick.t < 20


def test_wait_defers_while_a_long_run_is_still_in_flight(releases):
    tick = Tick()
    draining = {"draining": {"target": str(releases.new.resolve())}}
    r = D.wait_for_drain(
        releases.state,
        releases.new,
        on_target=lambda: False,
        ack_s=10,
        wait_s=60,
        clock=tick,
        sleeper=tick.sleep,
        status_reader=lambda: draining,
    )
    assert r == D.RESULT_DEFERRED


# ── executor v2: stop claiming, finish in-flight, exit ─────────────────────────────────────────────────────────


class Clock:
    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class Gates:
    def __init__(self) -> None:
        self.events: dict[str, threading.Event] = {}
        self.started: list[str] = []
        self.lock = threading.Lock()

    def gate(self, lane: str) -> threading.Event:
        with self.lock:
            return self.events.setdefault(lane, threading.Event())

    def factory(self, on_spawn, on_beat):
        def run(argv, *, timeout, env, cwd):
            lane = argv[argv.index("--lane") + 1]
            with self.lock:
                self.started.append(lane)
            on_spawn(os.getpid())
            assert self.gate(lane).wait(10), f"gate {lane} never released"
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        return run


def _entry(tmp: Path, lane: str) -> dict:
    return {
        "lane_id": lane,
        "command": ["$PY", "scripts/fake.py", "--lane", lane],
        "lock": str(tmp / "locks" / f"{lane}.lock"),
        "timeout_s": 60,
        "dry_run_arg": ["--dry-run"],
        "live_arg": ["--apply"],
    }


def _wait(pred, timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > end:
            raise AssertionError("condition not reached before deadline")
        time.sleep(0.01)


@pytest.fixture
def rig(releases):
    ledger = CoordinationLedger(releases.tmp / "ledger.sqlite")
    store = LedgerRunStore(ledger)
    clock = Clock()
    gates = Gates()
    allow = {lane: _entry(releases.tmp, lane) for lane in ("sweep", "other")}
    ex = X.ExecutorV2(
        store,
        allow,
        env={"TRADEAI_VENV_PYTHON": sys.executable},
        state_root=releases.state,
        code_root=releases.old,
        workers=3,
        policies=POLICIES,
        clock=clock,
        runner_factory=gates.factory,
        worker_prefix="test",
        quiet=True,
        registry_rows=[{"lane_id": lane, "dispatch": {"retry_policy": "transient-2"}} for lane in allow],
        sleeper=lambda s: None,
    )

    def request(run_id, lane):
        return store.request(
            run_id=run_id, lane_id=lane, mode="live", requested_by="t", caller_id="n8n-relay", now=clock.t
        )

    yield SimpleNamespace(ex=ex, store=store, clock=clock, gates=gates, request=request, rel=releases)
    for ev in gates.events.values():
        ev.set()
    ledger.close()


def test_drain_finishes_the_in_flight_run_and_claims_nothing_new(rig):
    rig.request("run-sweep-00000000001", "sweep")
    rig.ex.step()
    _wait(lambda: rig.gates.started == ["sweep"])
    D.write_request(rig.rel.state, rig.rel.new, now=rig.clock.t)
    rig.request("run-other-00000000001", "other")

    done = threading.Event()
    result: dict = {}

    def serve():
        result["r"] = rig.ex.serve(poll_s=0.01)
        done.set()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    time.sleep(0.2)
    assert not done.is_set(), "executor exited while a run was still in flight"
    assert rig.gates.started == ["sweep"], "a new run was claimed during the drain"
    status = json.loads((rig.rel.state / D.STATUS_REL).read_text())
    assert D.acknowledged(status, rig.rel.new)

    rig.gates.gate("sweep").set()
    assert done.wait(10), "executor did not exit after the in-flight run finished"
    assert result["r"] == "drained"
    assert rig.store.get("run-sweep-00000000001")["state"] == "RUN_DONE"
    assert rig.store.get("run-other-00000000001")["state"] == "REQUESTED"


def test_forced_drain_exits_after_the_deadline(rig):
    rig.request("run-sweep-00000000002", "sweep")
    rig.ex.step()
    _wait(lambda: rig.gates.started == ["sweep"])
    D.write_request(rig.rel.state, rig.rel.new, now=rig.clock.t, deadline_s=30)
    rig.clock.t += 31
    assert rig.ex.serve(poll_s=0.01) == "drain_forced"


def test_no_request_keeps_the_executor_claiming(rig):
    rig.request("run-sweep-00000000003", "sweep")
    rig.request("run-other-00000000003", "other")
    rig.ex.step()
    _wait(lambda: sorted(rig.gates.started) == ["other", "sweep"])


# ── executor v1 (serial) ─────────────────────────────────────────────────────────────────────────────────────


def test_v1_drain_stops_before_claiming_when_told_to(rig):
    rig.request("run-sweep-00000000004", "sweep")
    out = X.drain(
        rig.store,
        {"sweep": _entry(rig.rel.tmp, "sweep")},
        env={},
        state_root=rig.rel.state,
        code_root=rig.rel.old,
        should_stop=lambda: True,
    )
    assert out == [] and rig.store.get("run-sweep-00000000004")["state"] == "REQUESTED"


# ── deploy: verify records a deferred unit instead of paging it stale ─────────────────────────────────────────


def test_verify_records_deferred_executor_without_paging(monkeypatch, tmp_path):
    import scripts.current_bound_units as cli

    unit = D.EXECUTOR_UNIT
    stale = SimpleNamespace(name=unit, cwd="/old", stale=True, action="restart", reason="")
    monkeypatch.setattr(cli.cbu, "plan", lambda cur, **kw: SimpleNamespace(units=[stale]))
    monkeypatch.setattr(cli.cbu, "verify", lambda cur, names, **kw: {})
    sent: list = []
    monkeypatch.setattr(cli, "deliver", lambda msg: (sent.append(msg) or True, None))
    rc = cli.main(["verify", "--current", "/new", "--deferred", unit, "--state-root", str(tmp_path)])
    rec = json.loads((tmp_path / "data/runtime/current_bound_units_last.json").read_text())
    assert rc == 0 and sent == []
    assert rec["deferred_draining"] == [unit] and rec["stale_page_only"] == []


def test_deploy_drains_the_executor_before_any_restart():
    body = (ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh").read_text()
    fn = body[body.index("restart_root_frozen_units() {") :]
    fn = fn[: fn.index("\n}\n")]
    assert "n8n_executor_drain.py" in fn and "DRAIN_RESULT=" in fn
    assert fn.index("n8n_executor_drain.py") < fn.index('systemctl --user restart "$u"')
    assert '--deferred "${deferred[*]}"' in fn


def test_helper_cli_prints_a_result_token(tmp_path):
    state, old, new = tmp_path / "s", tmp_path / "o", tmp_path / "n"
    for p in (state, old, new):
        p.mkdir()
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "n8n_executor_drain.py"),
            "request",
            "--target",
            str(new),
            "--state-root",
            str(state),
            "--wait-s",
            "0",
            "--ack-s",
            "0",
            "--no-systemd",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "DRAIN_RESULT=not_acknowledged" in r.stdout, r.stdout + r.stderr
    assert json.loads(D.request_path(state).read_text())["target"] == str(new.resolve())
