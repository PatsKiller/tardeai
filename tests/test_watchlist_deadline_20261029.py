"""Hermetic deadline, ownership and pending-result regression tests."""

from __future__ import annotations

import ast
import importlib.util
import json
import signal
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import watchlist_deadline as deadline


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setenv("LLM_GLOBAL_DAILY_USD_CAP", "1")
    name = "watchlist_worker_deadline_tests"
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/process_watchlist_agent_jobs.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_postgres_driver(monkeypatch):
    """Exercise driver arguments without requiring an installed DB package."""
    driver, extras = ModuleType("psycopg2"), ModuleType("psycopg2.extras")
    driver.__path__ = []
    driver.extras = extras
    driver.connect = lambda **_kw: pytest.fail("unmocked database connection")
    extras.RealDictCursor = object
    monkeypatch.setitem(sys.modules, "psycopg2", driver)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)
    return driver


@pytest.fixture
def fake_alarm(monkeypatch):
    calls = []
    monkeypatch.setattr(deadline.signal, "getitimer", lambda *_: (0, 0))
    monkeypatch.setattr(deadline.signal, "getsignal", lambda *_: signal.SIG_DFL)
    monkeypatch.setattr(deadline.signal, "signal", lambda *args: calls.append(("handler", args)))
    monkeypatch.setattr(deadline.signal, "setitimer", lambda *args: calls.append(("timer", args)))
    return calls


@pytest.mark.parametrize("hard_cap,expected", [(180, 1165), (300, 1285)])
def test_callers_reserve_cleanup_without_extending_inherited_deadline(hard_cap, expected):
    env = {"AGENT_JOBS_P0_CONTAINED": "0", "LLM_GLOBAL_DAILY_USD_CAP": "1"}
    child = deadline.child_environment("python scripts/process_watchlist_agent_jobs.py", hard_cap, env, now=1000)
    assert float(child[deadline.DEADLINE_ENV]) == expected
    assert child["LLM_GLOBAL_DAILY_USD_CAP"] == "1" and deadline.DEADLINE_ENV not in env
    child[deadline.DEADLINE_ENV] = "1004"
    assert (
        deadline.child_environment("process_watchlist_agent_jobs.py", hard_cap, child, now=1000)[deadline.DEADLINE_ENV]
        == "1004.0"
    )
    assert deadline.child_environment("python scripts/other.py", hard_cap, env, now=1000) is None


@pytest.mark.parametrize("value", ["nan", "inf", "invalid"])
def test_invalid_deadlines_fail_closed(value):
    with pytest.raises(ValueError):
        deadline.DrainBudget.from_environment({deadline.DEADLINE_ENV: value})
    with pytest.raises(ValueError):
        deadline.child_environment("process_watchlist_agent_jobs.py", 180, {deadline.DEADLINE_ENV: value})


def test_nested_http_waits_and_explicit_provider_timeouts_share_remaining_budget(monkeypatch, fake_alarm):
    import urllib.request

    waits = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda _url, _data, timeout: waits.append(timeout))
    requests, sessions = ModuleType("requests"), ModuleType("requests.sessions")

    class Session:
        def request(self, *_a, **kw):
            waits.append(kw["timeout"])

    sessions.Session, requests.sessions = Session, sessions
    monkeypatch.setitem(sys.modules, "requests", requests)
    monkeypatch.setitem(sys.modules, "requests.sessions", sessions)
    budget = deadline.DrainBudget(20, clock=lambda: 12)
    assert deadline.bounded_timeout(180) == 180
    with budget.enforce():
        assert deadline.bounded_timeout(180) == 8
        urllib.request.urlopen("https://fixture.invalid")
        Session().request("GET", "https://fixture.invalid", timeout=(30, 3))
    assert waits == [8, (8, 3)]
    assert deadline.bounded_timeout(180) == 180
    assert fake_alarm[-2:] == [("timer", (signal.ITIMER_REAL, 0)), ("handler", (signal.SIGALRM, signal.SIG_DFL))]


def test_deadline_interrupt_bypasses_legacy_fallbacks_and_restores_scope(fake_alarm):
    swallowed = False
    with pytest.raises(deadline.DrainDeadlineExpired):
        with deadline.DrainBudget(20, clock=lambda: 12).enforce():
            handler = next(args[1] for kind, args in fake_alarm if kind == "handler")
            try:
                handler(signal.SIGALRM, None)
            except Exception:
                swallowed = True
    assert not swallowed
    assert deadline.bounded_timeout(180) == 180


def test_existing_alarm_is_not_overwritten(monkeypatch):
    monkeypatch.setattr(deadline.signal, "getitimer", lambda *_: (10, 0))
    with pytest.raises(ValueError, match="active timer"):
        with deadline.DrainBudget(20, clock=lambda: 12).enforce():
            pytest.fail("must fail before entering")


def test_outer_pending_receipt_survives_nested_service_json():
    payload = {"ok": False, "accepted": True, "outcome": "PENDING", "service": {"accepted": True}}
    assert deadline.last_json_object("diagnostic {broken\n" + json.dumps(payload) + "\ntrailing log") == payload


class FakeConnection:
    def __init__(self, *, owns_claim=True, jobs=()):
        self.queries, self.rollbacks, self.commits, self.closed = [], 0, 0, False
        self.owns_claim, self.jobs = owns_claim, list(jobs)
        self.last_sql = ""

    def cursor(self, **_kw):
        return self

    def execute(self, sql, params=None):
        self.last_sql = sql
        self.queries.append((sql, params))

    def fetchone(self):
        return {"id": "job-1"} if self.owns_claim else None

    def fetchall(self):
        return self.jobs if "SELECT * FROM watchlist_agent_jobs" in self.last_sql else []

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def test_expired_budget_touches_no_database_or_queue(worker, monkeypatch, fake_alarm):
    monkeypatch.setattr(worker.DrainBudget, "from_environment", lambda: deadline.DrainBudget(0, clock=lambda: 1))
    monkeypatch.setattr(worker, "_get_conn", lambda: pytest.fail("no database permitted"))
    monkeypatch.setattr(worker, "_auto_queue_new_symbols", lambda: pytest.fail("no new jobs permitted"))
    assert worker.process_jobs(auto_queue=True) == 0
    result = worker.process_jobs.last_outcome
    assert result["outcome"] == "DEFERRED" and result["exit_code"] == 75 and result["ok"] is False
    assert result["selected"] is None and result["deferred"] is None


@pytest.mark.parametrize("owns_claim", [True, False])
def test_interrupted_job_requeues_only_the_same_owned_claim(worker, monkeypatch, fake_alarm, owns_claim):
    conn, maturities = FakeConnection(owns_claim=owns_claim), []
    monkeypatch.setattr(worker.DrainBudget, "from_environment", lambda: deadline.DrainBudget(20, clock=lambda: 1))
    monkeypatch.setattr(worker, "_update_maturity", lambda *_a: maturities.append(_a))

    def interrupted(_limit, *, _progress, _budget):
        _progress.update(
            connection=conn,
            selected=3,
            next_index=1,
            completed=1,
            active_job={"id": "job-1", "symbol": "FAKE", "requested_agent": "maria", "_drain_started_at": "own-token"},
        )
        raise deadline.DrainDeadlineExpired()

    monkeypatch.setattr(worker, "_process_jobs_impl", interrupted)
    assert worker.process_jobs() == 1
    result = worker.process_jobs.last_outcome
    assert result["completed"] == 1 and result["deferred"] == 2 and result["exit_code"] == 75
    update = next((sql, p) for sql, p in conn.queries if "UPDATE watchlist_agent_jobs" in sql)
    assert "started_at=%s" in update[0] and "status='processing'" in update[0]
    assert update[1] == ("job-1", "own-token")
    assert len(maturities) == int(owns_claim)
    assert conn.closed and conn.rollbacks == 1


def test_cleanup_failure_is_never_a_clean_defer(worker, monkeypatch, fake_alarm):
    conn = FakeConnection()
    monkeypatch.setattr(worker.DrainBudget, "from_environment", lambda: deadline.DrainBudget(20, clock=lambda: 1))

    def interrupted(_limit, *, _progress, _budget):
        _progress.update(connection=conn, selected=1)
        raise deadline.DrainDeadlineExpired()

    monkeypatch.setattr(worker, "_process_jobs_impl", interrupted)
    monkeypatch.setattr(conn, "rollback", lambda: (_ for _ in ()).throw(RuntimeError("fake disconnect")))
    monkeypatch.setattr(worker, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("fake reconnect failure")))
    worker.process_jobs()
    assert worker.process_jobs.last_outcome["cleanup_error"] == "RuntimeError"
    assert worker.process_jobs.last_outcome["exit_code"] == 1 and conn.closed


def test_dead_connection_reconnects_within_cleanup_budget_and_preserves_claim(worker, monkeypatch, fake_alarm):
    stale, fresh = FakeConnection(), FakeConnection()
    monkeypatch.setattr(stale, "rollback", lambda: (_ for _ in ()).throw(RuntimeError("fake closed connection")))
    waits = []

    def reconnect():
        waits.append(deadline.bounded_timeout(180))
        return fresh

    monkeypatch.setattr(worker, "_get_conn", reconnect)
    monkeypatch.setattr(worker, "_update_maturity", lambda *_: None)
    progress = {
        "connection": stale,
        "active_job": {"id": "job-1", "symbol": "FAKE", "requested_agent": "maria", "_drain_started_at": "own-token"},
    }
    worker._resume_deadline_claim(progress)
    assert stale.closed and progress["connection"] is fresh
    assert 0 < waits[0] <= 10
    assert next(params for sql, params in fresh.queries if "UPDATE watchlist_agent_jobs" in sql) == (
        "job-1",
        "own-token",
    )


def test_database_connection_waits_clamp_without_opening_real_database(
    worker, monkeypatch, fake_alarm, fake_postgres_driver
):
    import psycopg2

    monkeypatch.setenv("DB_PASSWORD", "synthetic-test-only")
    captured = []
    monkeypatch.setattr(psycopg2, "connect", lambda **kw: captured.append(kw))
    with deadline.DrainBudget(20, clock=lambda: 12).enforce():
        worker._get_conn()
    assert captured[0]["connect_timeout"] == 8
    assert "options" not in captured[0], "the role/session statement cap must not be overwritten"


@pytest.mark.parametrize("claim_time", [None, "own-synthesis-token"])
def test_synthesis_cleanup_requires_own_timestamp(worker, monkeypatch, claim_time):
    conn = FakeConnection()
    worker._resume_deadline_claim({"connection": conn, "synthesis_symbol": "FAKE", "synthesis_claimed_at": claim_time})
    updates = [(sql, params) for sql, params in conn.queries if "UPDATE watchlist_analysis_maturity" in sql]
    assert len(updates) == int(claim_time is not None)
    if updates:
        assert "updated_at=%s" in updates[0][0] and updates[0][1] == ("FAKE", claim_time)


def test_unbounded_empty_drain_retains_integer_return_and_no_deferral(worker, monkeypatch):
    monkeypatch.setattr(worker.DrainBudget, "from_environment", lambda: deadline.DrainBudget())

    def empty(_limit, *, _progress, _budget):
        assert _budget.deadline is None
        _progress["selected"] = 0

    monkeypatch.setattr(worker, "_process_jobs_impl", empty)
    assert worker.process_jobs() == 0
    assert worker.process_jobs.last_outcome["outcome"] == "DRAINED"
    assert worker.process_jobs.last_outcome["deferred"] == 0 and worker.process_jobs.last_outcome["exit_code"] == 0


def test_bridge_provider_receives_remaining_timeout_without_changing_route(worker, monkeypatch, fake_alarm):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "lib.llm_bridge_route",
        SimpleNamespace(require_text_via_bridge=lambda *args, **kw: calls.append((args, kw)) or "fixture"),
    )
    with deadline.DrainBudget(20, clock=lambda: 12).enforce():
        assert worker._bridge_text("unchanged-process-id", "fixture prompt", 200) == "fixture"
    assert calls[0][0][0] == "unchanged-process-id"
    assert calls[0][1] == {"timeout_s": 8, "max_tokens": 200}


def test_later_job_is_not_claimed_when_remaining_time_is_too_short(
    worker, monkeypatch, fake_alarm, fake_postgres_driver
):
    clock = [0]
    jobs = [
        {"id": f"job-{n}", "symbol": f"FAKE{n}", "requested_agent": "maria", "request_type": "full_analysis"}
        for n in range(2)
    ]
    conn = FakeConnection(jobs=jobs)
    monkeypatch.setattr(
        worker.DrainBudget, "from_environment", lambda: deadline.DrainBudget(10, clock=lambda: clock[0])
    )
    monkeypatch.setattr(worker, "_get_conn", lambda: conn)
    monkeypatch.setattr(worker, "holdings_list", lambda *_: [])
    monkeypatch.setattr(worker, "is_off_hours_et", lambda: False)
    monkeypatch.setattr(worker, "job_priority_params", lambda *_: [])
    monkeypatch.setattr(worker, "sql_job_priority_case", lambda *_: "0")
    monkeypatch.setattr(worker, "request_type_sla_params", lambda: [])
    monkeypatch.setattr(worker, "sql_request_type_sla_case", lambda *_: "0")
    monkeypatch.setattr(worker, "_portfolio_symbol_set", lambda: set())
    monkeypatch.setattr(worker, "_wait_setup_symbol_set", lambda *_: set())
    monkeypatch.setitem(
        sys.modules, "lib.agent_job_enqueue_governance", SimpleNamespace(govern_existing_queued=lambda *_: {})
    )

    def reject(_symbol, **_kw):
        clock[0] = 6
        return False, "synthetic invalid symbol"

    monkeypatch.setattr(worker, "gate_watchlist_symbol", reject)
    worker.process_jobs()
    assert not any("SET status='processing'" in sql for sql, _ in conn.queries)
    assert worker.process_jobs.last_outcome["deferred"] == 1


def test_deferred_cli_exits_inside_pipeline_context(worker, monkeypatch):
    import pipeline_registry

    receipts = []
    monkeypatch.setattr(pipeline_registry, "run_start", lambda *_: "fake-run")
    monkeypatch.setattr(pipeline_registry, "_install_termination_handlers", lambda: {})
    monkeypatch.setattr(pipeline_registry, "_restore_handlers", lambda *_: None)
    monkeypatch.setattr(pipeline_registry, "run_fail", lambda *args: receipts.append(("failed", args)))
    monkeypatch.setattr(pipeline_registry, "run_complete", lambda *args: receipts.append(("completed", args)))
    tree = ast.parse((ROOT / "scripts/process_watchlist_agent_jobs.py").read_text())
    block = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.With)
        and isinstance(node.items[0].context_expr, ast.Call)
        and isinstance(node.items[0].context_expr.func, ast.Name)
        and node.items[0].context_expr.func.id == "PipelineRun"
    )

    def drain(*_a, **_kw):
        drain.last_outcome = {"deadline_reached": True, "exit_code": 75}

    with pytest.raises(SystemExit) as exc:
        exec(
            compile(ast.Module(body=[block], type_ignores=[]), "<worker-entrypoint>", "exec"),
            {
                "PipelineRun": pipeline_registry.PipelineRun,
                "process_jobs": drain,
                "args": SimpleNamespace(limit=10),
                "_sys": sys,
            },
        )
    assert exc.value.code == 75 and receipts == [("failed", ("fake-run", "75"))]


@pytest.mark.parametrize(
    "ftype,cmd,rc,payload",
    [
        (
            "pipeline_failures",
            "python scripts/remediate_pipeline_failures.py",
            0,
            {"ok": False, "accepted": True, "outcome": "PENDING", "service": {"accepted": True}},
        ),
        (
            "agent_jobs_stale",
            "python scripts/process_watchlist_agent_jobs.py",
            75,
            {"schema": "WatchlistDrain@v1", "ok": False, "outcome": "DEFERRED", "completed": 1, "deferred": 2},
        ),
    ],
)
def test_health_pending_does_not_verify_recover_or_reset_streak(monkeypatch, tmp_path, ftype, cmd, rc, payload):
    import health_agent as health

    state = tmp_path / "state.json"
    state.write_text(json.dumps({ftype: {"fail_streak": 2, "ineffective_streak": 1}}))
    monkeypatch.setattr(health, "REMEDIATION_STATE", state)
    monkeypatch.setattr(health, "REMEDIATION_LOG", tmp_path / "attempts.jsonl")
    monkeypatch.setattr(health, "_remediation_cwd", lambda: tmp_path)
    monkeypatch.setattr(health, "_rewrite_remediation_cmd", lambda cmd: cmd)
    monkeypatch.setattr(health, "_lane_state_for_cmd", lambda *_: {"state": "ACTIVE"})
    monkeypatch.setattr(health, "_SAFE_REMEDIATION_SCRIPTS", (cmd.split("/")[-1],))
    monkeypatch.setattr(health, "compute", lambda *_: pytest.fail("pending is not a recovered condition"))
    monkeypatch.setitem(
        sys.modules,
        "lib.agent_jobs_containment",
        SimpleNamespace(guard_agent_jobs_execution=lambda *_a, **_kw: {"blocked": False}),
    )
    launched = []

    def popen(*_args, **kwargs):
        launched.append(kwargs)
        return SimpleNamespace(returncode=rc, communicate=lambda **_kw: (json.dumps(payload), ""))

    monkeypatch.setattr(health.subprocess, "Popen", popen)
    policy = {
        "auto_remediate": {"enabled": True, "finding_types": [ftype], "cooldown_minutes": 0},
        "remediation_map": {ftype: cmd},
    }
    results = health.run_auto_remediation(policy, [{"type": ftype, "severity": "critical", "message": "fake backlog"}])
    assert len(results) == 1 and results[0]["pending"] is True and results[0]["ok"] is False
    assert not results[0].get("verified_by_recheck")
    stored = json.loads(state.read_text())[ftype]
    assert stored["fail_streak"] == 2 and stored["ineffective_streak"] == 1
    if "process_watchlist" in cmd:
        assert deadline.DEADLINE_ENV in launched[0]["env"]


def test_escalation_caller_keeps_hard_cap_and_reports_deferred(monkeypatch):
    import claude_escalation_handler as escalation

    launched, waits, logs = [], [], []
    monkeypatch.setattr(escalation, "_check_allowlist", lambda *_: (True, "synthetic allowlist"))
    monkeypatch.setitem(
        sys.modules,
        "lib.agent_jobs_containment",
        SimpleNamespace(guard_agent_jobs_execution=lambda *_a, **_kw: {"blocked": False}),
    )
    monkeypatch.setattr(escalation, "_log_retry", lambda *args, **kw: logs.append((args, kw)))

    def communicate(timeout=None):
        waits.append(timeout)
        return json.dumps({"schema": "WatchlistDrain@v1", "ok": False, "outcome": "DEFERRED"}), ""

    def popen(*_a, **kw):
        launched.append(kw)
        return SimpleNamespace(returncode=75, communicate=communicate)

    monkeypatch.setattr(escalation.subprocess, "Popen", popen)
    executed, success, output = escalation._execute_retry_cmd(
        {"retry_cmd": "python scripts/process_watchlist_agent_jobs.py"}, {"max_runtime_seconds": 120}, dry_run=False
    )
    assert executed and not success and "DEFERRED" in output
    assert waits == [300] and deadline.DEADLINE_ENV in launched[0]["env"]
    assert logs[-1][0][4] == "retry_cmd_deferred"


@pytest.mark.parametrize(
    "payload",
    [
        {"outcome": "PENDING", "ok": False, "accepted": True, "service": {"accepted": True}, "note": "x" * 3000},
        {
            "outcome": "DEFERRED",
            "schema": "WatchlistDrain@v1",
            "ok": False,
            "exit_code": 75,
            "completed": 1,
            "deferred": 3,
        },
    ],
)
def test_escalation_preserves_pending_queue_without_verification_or_llm(monkeypatch, tmp_path, payload):
    import claude_escalation_handler as escalation

    now = [1000]
    monkeypatch.setattr(escalation.time, "time", lambda: now[0])
    queue, stale = tmp_path / "queue.json", tmp_path / "stale.json"
    queue.write_text(
        json.dumps(
            [
                {
                    "id": f"existing-{index}",
                    "component": "health:execution_health:pipeline_failures",
                    "detail": f"synthetic failure {index}",
                    "fixable": True,
                    "retry_cmd": "python scripts/remediate_pipeline_failures.py",
                    "_attempts": 2,
                }
                for index in range(2)
            ]
        )
    )
    stale.write_text("[]")
    monkeypatch.setattr(escalation, "QUEUE_FILE", queue)
    monkeypatch.setattr(escalation, "STALENESS_QUEUE_FILE", stale)
    monkeypatch.setattr(escalation, "load_remediation_types", lambda: {"pipeline_failures"})
    monkeypatch.setattr(escalation, "_get_conn", lambda: None)
    monkeypatch.setattr(escalation, "_load_allowlist", lambda: {})
    monkeypatch.setattr(escalation, "_verify_remediation", lambda *_: pytest.fail("pending must not verify"))
    monkeypatch.setattr(escalation, "_notify", lambda *_: pytest.fail("pending is not recovery or operator hold"))
    output = escalation._retry_output(json.dumps(payload), rc=0 if payload["outcome"] == "PENDING" else 75)
    assert output.startswith("PENDING_JSON:")
    assert escalation._pending_retry_outcome(output) == payload
    monkeypatch.setattr(escalation, "_execute_retry_cmd", lambda *_a, **_kw: (True, False, output))
    escalation.process_queue()
    stored = json.loads(queue.read_text())
    assert [row["id"] for row in stored] == ["existing-0", "existing-1"]
    assert all(row["_attempts"] == 2 and row["outcome"] == payload["outcome"] for row in stored)
    # A second tick is inside the ordinary backoff window. An in-flight item
    # must stay queued without slipping past Tier1 into LLM diagnosis.
    monkeypatch.setattr(escalation, "_execute_retry_cmd", lambda *_a, **_kw: pytest.fail("cooldown must not retry"))
    for tick in (1060, 1120):
        now[0] = tick
        escalation.process_queue()
        stored = json.loads(queue.read_text())
        assert all(row["_attempts"] == 2 and row["outcome"] == payload["outcome"] for row in stored)
        assert all(row["_last_attempt_ts"] == 1000 for row in stored)
    # A subsequent real failed retry must clear old pending state and retain
    # normal failure handling, rather than becoming an indefinite pending hold.
    now[0] = 1301
    monkeypatch.setattr(escalation, "_execute_retry_cmd", lambda *_a, **_kw: (True, False, "exit_code=1: failed"))
    monkeypatch.setattr(escalation.time, "sleep", lambda *_: None)
    escalation.process_queue(tier1_only=True)
    failed = json.loads(queue.read_text())
    assert all("_pending_retry" not in row and "outcome" not in row for row in failed)
    assert all(row["_last_attempt_ts"] == 1301 for row in failed)


def test_failed_cleanup_and_nonzero_acceptance_cannot_bypass_failure_handling():
    import claude_escalation_handler as escalation

    payload = {
        "outcome": "DEFERRED",
        "schema": "WatchlistDrain@v1",
        "ok": False,
        "exit_code": 1,
        "cleanup_error": "RuntimeError",
    }
    assert escalation._pending_retry_outcome(json.dumps(payload)) is None
    pending = {"outcome": "PENDING", "ok": False, "accepted": True}
    assert escalation._pending_retry_outcome(json.dumps(pending), exit_code=1) is None
    assert not escalation._retry_output(json.dumps(pending), rc=1).startswith("PENDING_JSON:")
