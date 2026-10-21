"""Health admission uses fake DB/processes and explicitly fake host-history readiness."""

import hashlib
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.test_system_health_freshness_identity_20261012 import agent  # noqa: F401

NOW = datetime(2026, 10, 19, 3, tzinfo=timezone.utc)
COMPONENT = "fixture-budget-component"


def reserved(**over):
    row = {
        "schema": "HealthRetryAttempt@v1",
        "namespace": "system_health_retry",
        "component": COMPONENT,
        "ts": (NOW - timedelta(seconds=30)).isoformat(),
        "attempt_id": "a" * 32,
        "command_digest": hashlib.sha256(b"prior fixed action").hexdigest(),
    }
    return {**row, **over}


@pytest.fixture
def harness(agent, monkeypatch):
    state = Path(__import__("os").environ["TRADEAI_STATE_ROOT"])
    journal = state / "data/runtime/health_retry_attempts.jsonl"
    journal.write_text("")  # Fixture history only; production has no initializer.
    model = {"mode": "ok", "calls": [], "events": [], "db_error": False, "barrier": None}
    lock = threading.Lock()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)

    class Cursor:
        def execute(self, sql, args):
            if model["db_error"]:
                raise RuntimeError("fixture DB unavailable")
            assert "SELECT COUNT" in sql
            types = {"RETRY"} if "event_type='RETRY'" in sql else {"RETRY", "RETRY_TIMEOUT", "RETRY_ERROR"}
            with lock:
                self.count = sum(t in types for t in model["events"])
            if model["barrier"] is not None:
                model["barrier"].wait(timeout=5)

        def fetchone(self):
            return (self.count,)

    class Conn:
        def cursor(self):
            return Cursor()

        def commit(self):
            pass

        def rollback(self):
            pass

    class Child:
        returncode = 0
        pid = 123456789

        def communicate(self, **kwargs):
            if model["mode"] == "timeout" and not getattr(self, "timed_out", False):
                self.timed_out = True
                raise subprocess.TimeoutExpired("fixture action", 300)
            return "", ""

    def popen(command, **kwargs):
        assert command == sys.executable + " fixture-budget-only.py"
        with lock:
            model["calls"].append(command)
        if model["mode"] == "error":
            raise OSError("fixture spawn failure")
        if model["mode"] == "crash":
            raise KeyboardInterrupt("fixture crash after admission")
        return Child()

    def event(conn, component, kind, *args, **kwargs):
        with lock:
            model["events"].append(kind)

    monkeypatch.setenv("TRADEAI_HEALTH_AGENT_RETRY", "1")
    monkeypatch.setattr(agent, "datetime", Clock)
    monkeypatch.setattr(agent, "_log_event", event)
    monkeypatch.setattr(agent.subprocess, "Popen", popen)
    monkeypatch.setattr(agent.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(agent.os, "killpg", lambda pid, sig: None)
    # This is a fake authoritative source seam, never an activation flag or raw authority boolean.
    monkeypatch.setattr(agent, "_health_retry_history", lambda path, now: path.read_text(), raising=False)
    model.update(
        agent=agent,
        journal=journal,
        conn=Conn,
        comp={"component": COMPONENT, "retry_cmd": ".venv/bin/python fixture-budget-only.py"},
    )
    return model


@pytest.mark.parametrize("failure", ["timeout", "error"])
def test_timeouts_and_spawn_errors_consume_attempts(harness, failure):
    h = harness
    h["mode"] = failure
    for _ in range(3):
        h["agent"]._attempt_retry(h["comp"], h["conn"]())
    assert len(h["calls"]) == 2, "failed actions still consume the two-attempt window"


def test_concurrent_health_evaluators_reserve_atomically(harness):
    h = harness
    h["barrier"] = threading.Barrier(6)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: h["agent"]._attempt_retry(h["comp"], h["conn"]()), range(6)))
    assert len(h["calls"]) == 2 and sum(results) == 2


def test_prior_reservation_plus_same_cycle_attempts_never_exceeds_cap(harness):
    h = harness
    h["journal"].write_text(json.dumps(reserved()) + "\n")
    for _ in range(2):
        h["agent"]._attempt_retry(h["comp"], h["conn"]())
    assert len(h["calls"]) == 1


def test_crash_after_admission_keeps_attempt_reserved(harness):
    h = harness
    h["mode"] = "crash"
    with pytest.raises(KeyboardInterrupt):
        h["agent"]._attempt_retry(h["comp"], h["conn"]())
    h["mode"] = "ok"
    for _ in range(2):
        h["agent"]._attempt_retry(h["comp"], h["conn"]())
    assert len(h["calls"]) == 2


@pytest.mark.parametrize(
    "failure", ["db", "missing", "uninitialized", "malformed", "future", "boolean_source", "write_failure"]
)
def test_unknown_health_budget_never_reaches_popen(harness, monkeypatch, failure):
    h = harness
    if failure == "db":
        h["db_error"] = True
    elif failure == "missing":
        h["journal"].unlink()
    elif failure == "uninitialized":
        monkeypatch.setattr(h["agent"], "_health_retry_history", lambda *a: None)
    elif failure == "malformed":
        h["journal"].write_text('{"initialized":true}\n')
    elif failure == "future":
        h["journal"].write_text(json.dumps(reserved(ts="2099-01-01T00:00:00+00:00")) + "\n")
    elif failure == "boolean_source":
        monkeypatch.setattr(h["agent"], "_health_retry_history", lambda *a: True)
    elif failure == "write_failure":
        monkeypatch.setattr(h["agent"].os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fixture fsync failed")))
    assert h["agent"]._attempt_retry(h["comp"], h["conn"]()) is False
    assert h["calls"] == []


@pytest.mark.parametrize("cap", [None, True, float("nan")])
def test_invalid_health_cap_fails_closed(harness, monkeypatch, cap):
    h = harness
    monkeypatch.setattr(h["agent"], "MAX_RETRIES", cap)
    assert h["agent"]._attempt_retry(h["comp"], h["conn"]()) is False
    assert not h["calls"]


def test_known_fixture_history_allows_one_attempt_without_claiming_recovery(harness):
    h = harness
    assert h["agent"]._attempt_retry(h["comp"], h["conn"]()) is True
    assert len(h["calls"]) == 1
    assert "RECOVERED" not in h["events"]


def test_disarmed_path_never_reads_history_or_launches(harness, monkeypatch):
    h = harness
    monkeypatch.delenv("TRADEAI_HEALTH_AGENT_RETRY", raising=False)
    monkeypatch.setattr(h["agent"], "_health_retry_history", lambda *a: pytest.fail("disarmed history access"))
    assert h["agent"]._attempt_retry(h["comp"], h["conn"]()) is False
    assert not h["calls"]


@pytest.mark.parametrize(
    "bad_history",
    [
        lambda: json.dumps(reserved()) + "\n" + json.dumps(reserved()),
        lambda: json.dumps(reserved()) + "\n" + json.dumps(reserved(component="other-component")),
        lambda: json.dumps(reserved(schema="Recovery@v1")),
        lambda: json.dumps(reserved(namespace="supervisor_recovery")),
        lambda: json.dumps(reserved(extra="authority")),
        lambda: json.dumps(reserved(ts="2026-10-19T02:00:00")),
        lambda: json.dumps(reserved(attempt_id="A" * 32)),
        lambda: json.dumps(reserved(command_digest="not-a-digest")),
        lambda: json.dumps(reserved())[:-1] + ',"component":"other-component"}',
    ],
)
def test_malformed_or_duplicate_health_identities_hold_before_effect(harness, bad_history):
    h = harness
    h["journal"].write_text(bad_history() + "\n")
    assert h["agent"]._attempt_retry(h["comp"], h["conn"]()) is False
    assert not h["calls"]


def test_lock_contention_is_bounded_by_health_absolute_deadline(harness):
    import fcntl
    import time

    h = harness
    h["comp"]["max_runtime_sec"] = 0.03
    with h["journal"].with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        started = time.monotonic()
        state = {}
        assert h["agent"]._attempt_retry(h["comp"], h["conn"](), attempt_state=state) is False
        assert time.monotonic() - started < 0.5
    assert not h["calls"] and h["journal"].read_text() == ""
    assert state == {"attempted": False, "budget_status": "unavailable"}


def test_unbound_history_snapshot_cannot_ignore_existing_reservations(harness, monkeypatch):
    h = harness
    h["journal"].write_text(json.dumps(reserved()) + "\n")
    monkeypatch.setattr(h["agent"], "_health_retry_history", lambda *a: "")
    assert h["agent"]._attempt_retry(h["comp"], h["conn"]()) is False
    assert not h["calls"]


def test_server_minted_identity_collision_holds_before_effect(harness, monkeypatch):
    from types import SimpleNamespace
    from lib import recovery_attempt_budget as budget

    h = harness
    h["journal"].write_text(json.dumps(reserved()) + "\n")
    monkeypatch.setattr(budget.uuid, "uuid4", lambda: SimpleNamespace(hex="a" * 32))
    assert h["agent"]._attempt_retry(h["comp"], h["conn"]()) is False
    assert not h["calls"]


def test_prior_known_db_attempts_are_a_conservative_lower_bound(harness):
    h = harness
    h["events"].extend(["RETRY_TIMEOUT", "RETRY_ERROR"])
    assert h["agent"]._attempt_retry(h["comp"], h["conn"]()) is False
    assert not h["calls"] and h["journal"].read_text() == ""


def test_rolling_24h_window_and_component_scope_preserve_known_limits(harness):
    h = harness
    h["journal"].write_text(
        json.dumps(reserved(ts=(NOW - timedelta(hours=25)).isoformat()))
        + "\n"
        + json.dumps(reserved(component="another-component", attempt_id="b" * 32))
        + "\n"
    )
    for _ in range(3):
        h["agent"]._attempt_retry(h["comp"], h["conn"]())
    assert len(h["calls"]) == 2


def test_source_hook_has_no_production_initializer(agent, tmp_path):
    path = tmp_path / "plausible-history.jsonl"
    path.write_text("")
    assert agent._health_retry_history(path, NOW) is None


@pytest.mark.parametrize("count", [None, True, -1, float("nan")])
def test_invalid_db_count_is_unknown_not_zero(harness, count):
    from types import SimpleNamespace

    h = harness
    conn = SimpleNamespace(
        cursor=lambda: SimpleNamespace(execute=lambda *a: None, fetchone=lambda: (count,)),
        commit=lambda: None,
        rollback=lambda: None,
    )
    assert h["agent"]._attempt_retry(h["comp"], conn) is False
    assert not h["calls"]


def test_supervisor_lock_wait_is_bounded_without_changing_v1_history(tmp_path, monkeypatch):
    import fcntl
    import time
    from lib import recovery_attempt_budget as budget
    from scripts import supervisor_breach_detector as supervisor

    path = tmp_path / "supervisor_recoveries.jsonl"
    path.write_text("")
    monkeypatch.setattr(budget, "LOCK_WAIT_S", 0.03)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        started = time.monotonic()
        assert supervisor._reserve_recovery(path, {}, NOW, live=True) == (False, "unavailable")
        assert time.monotonic() - started < 0.5
    assert path.read_text() == ""


def test_unavailable_host_history_source_is_a_hold(harness, monkeypatch):
    h = harness

    def unavailable(*args):
        raise RuntimeError("fixture host history unavailable")

    monkeypatch.setattr(h["agent"], "_health_retry_history", unavailable)
    assert h["agent"]._attempt_retry(h["comp"], h["conn"]()) is False
    assert h["calls"] == [] and h["journal"].read_text() == ""


@pytest.mark.parametrize("timeout", [None, True, float("nan"), float("inf"), 10**1000])
def test_invalid_absolute_runtime_budget_refuses_before_admission(harness, timeout):
    h = harness
    h["comp"]["max_runtime_sec"] = timeout
    assert h["agent"]._attempt_retry(h["comp"], h["conn"]()) is False
    assert h["calls"] == [] and h["journal"].read_text() == ""
