"""2026-10-23 09:10 ET false page: "SYSTEM HEALTH: Finviz Screener — OUTPUT_INVALID · Expected: 0 8 * * 1-5 ·
Error: latest_receipt_failed".

Root cause: finviz_screener_runner.py is invoked ~120x/hour 06:00-09:30 ET by two callers (scalp-hot-list */2 and
the momentum-scalp early lane */5, one ``--screener <id>`` call per scalp screener) and every call wrote the
scheduled lane's receipt ``finviz-screener-runner_last.json``. One call killed by its caller's per-call timeout
(13 s left of the hot-list's 85 s budget) left a ``status: failed`` receipt between successes, and the health agent
paged on that single attempt with a stale expected schedule.

Pinned here (hermetic: tmp state roots, fake DB cursors, fake telegram transport, no network, no host state):
  * a failed latest attempt is debounced while a success is no older than the component's window and fewer than N
    consecutive failures are recorded; otherwise it is FAILED exactly as before (knobs default off);
  * the receipt writer records ``consecutive_failures`` (reset on success);
  * ``--screener`` runs write ``finviz-screener-runner-subset``, full runs keep the scheduled lane's receipt;
  * the Finviz component's schedule is the lane registry's (fallback literal pinned equal to it);
  * a recovered note is sent once per escalation, at P2, and only when an escalation is owed one.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib import lane_last_receipt as R
from scripts.lib.system_health_freshness import lane_receipt_freshness

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 23, 13, 10, tzinfo=timezone.utc)
LANE = "finviz-screener-runner"
SCRIPT = "finviz_screener_runner.py"


def receipt(**over):
    finished = (NOW - timedelta(minutes=1)).isoformat()
    return {
        "schema": "LaneRunReceipt@v1",
        "lane_id": LANE,
        "script": SCRIPT,
        "mode": "live",
        "status": "failed",
        "exit": 143,
        "started_at": (NOW - timedelta(minutes=1, seconds=13)).isoformat(),
        "finished_at": finished,
        "ok_at": (NOW - timedelta(minutes=2)).isoformat(),
        **over,
    }


def judge(doc, **kw):
    kw.setdefault("failure_debounce_min", 10)
    kw.setdefault("failure_alert_consecutive", 3)
    return lane_receipt_freshness(doc, lane_id=LANE, script=SCRIPT, now=NOW, max_age_min=1500, **kw)


# ---------------------------------------------------------------- pure debounce projection


def test_one_failed_attempt_between_successes_is_debounced_not_paged():
    report = judge(receipt())
    assert report["status"] == "OK" and report["debounced"] is True
    assert report["reason"] == "latest_receipt_failed_debounced"
    assert report["latest_attempt_status"] == "failed" and report["age_min"] == 2.0
    assert report["debounce_verdict"] == "success_within_window"


def test_no_success_inside_the_window_is_failed():
    report = judge(receipt(ok_at=(NOW - timedelta(minutes=15)).isoformat()))
    assert report["status"] == "FAILED" and report["reason"] == "latest_receipt_failed"
    assert report["debounced"] is False and report["debounce_verdict"] == "no_success_within_window"


def test_n_consecutive_failures_page_even_with_a_recent_success():
    report = judge(receipt(consecutive_failures=3))
    assert report["status"] == "FAILED" and report["debounce_verdict"] == "consecutive_failures_reached"
    assert report["consecutive_failures"] == 3
    assert judge(receipt(consecutive_failures=2))["status"] == "OK"


def test_never_succeeded_is_failed():
    report = judge(receipt(ok_at=None))
    assert report["status"] == "FAILED" and report["debounce_verdict"] == "no_current_success"


@pytest.mark.parametrize("bad", [True, -1, "2", 1.5])
def test_malformed_consecutive_count_is_ignored_not_trusted(bad):
    report = judge(receipt(consecutive_failures=bad))
    assert report["consecutive_failures"] is None and report["status"] == "OK"


def test_knobs_default_off_keep_the_strict_verdict():
    report = lane_receipt_freshness(receipt(), lane_id=LANE, script=SCRIPT, now=NOW, max_age_min=1500)
    assert report["status"] == "FAILED" and report["reason"] == "latest_receipt_failed"
    assert report["debounced"] is False and "debounce_verdict" not in report


# ---------------------------------------------------------------- receipt writer


def test_writer_counts_consecutive_failures_and_resets_on_success(tmp_path):
    path = tmp_path / "data" / "runtime" / "x_last.json"
    path.parent.mkdir(parents=True)

    def write(ok):
        assert R.write_lane_receipt("x", ok=ok, exit_code=0 if ok else 1, path=path) == path
        return json.loads(path.read_text())

    assert write(False)["consecutive_failures"] == 1
    assert write(False)["consecutive_failures"] == 2
    doc = write(True)
    assert doc["consecutive_failures"] == 0 and doc["ok_at"] == doc["finished_at"]
    failed = write(False)
    assert failed["consecutive_failures"] == 1 and failed["ok_at"] == doc["ok_at"]


def test_build_receipt_without_a_previous_count_adds_no_field():
    assert "consecutive_failures" not in R.build_receipt("x", ok=False, exit_code=1)


# ---------------------------------------------------------------- caller runs get their own receipt


def _runner():
    spec = importlib.util.spec_from_file_location("_finviz_runner_under_test", ROOT / "scripts" / SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    return mod


def test_screener_subset_runs_write_their_own_receipt_key():
    tree = ast.parse((ROOT / "scripts" / SCRIPT).read_text())
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "write_lane_receipt"
    ]
    assert len(calls) == 3
    for call in calls:
        first = call.args[0]
        assert isinstance(first, ast.Call) and first.func.id == "receipt_lane_id", ast.unparse(call)
        assert ast.unparse(first.args[0]) == "args.screener"


def test_receipt_lane_id_mapping():
    mod = _runner()
    assert mod.receipt_lane_id(None) == LANE and mod.receipt_lane_id("") == LANE
    assert mod.receipt_lane_id("prime_setups") == "finviz-screener-runner-subset"
    R.receipt_path(mod.SUBSET_LANE_ID)  # a valid lane id (no path separators)


# ---------------------------------------------------------------- agent: schedule, loop, recovered note


@pytest.fixture
def agent(tmp_path, monkeypatch):
    path = ROOT / "scripts" / "system_health_agent.py"
    spec = importlib.util.spec_from_file_location("_system_health_debounce_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    state = tmp_path / "state"
    (state / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    return mod


def component(agent):
    return dict(next(c for c in agent.MONITORED_COMPONENTS if c["component"] == "finviz_screener_runner"))


def test_finviz_literal_schedule_matches_the_lane_registry(agent):
    comp = component(agent)
    registry = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    row = next(r for r in registry["lanes"] if r.get("lane_id") == LANE)
    assert row["state"] == "ACTIVE" and comp["schedule"] == row["scheduler"]["expression"]
    resolved = agent._resolve_component_schedule(comp, registry)
    assert resolved["schedule"] == comp["schedule"] and resolved["schedule_resolved_from"] == "lane_registry"
    assert comp["failure_debounce_min"] == 10 and comp["failure_alert_consecutive"] == 3
    assert comp["max_runtime_sec"] >= 1161  # measured max of the 10:00 full run, 2026-10-15..22


def test_registry_schedule_wins_and_unreadable_registry_falls_back(agent):
    comp = dict(component(agent), schedule="0 8 * * 1-5")
    registry = {
        "schema": "LaneRegistry@v1",
        "lanes": [{"lane_id": LANE, "state": "ACTIVE", "scheduler": {"kind": "cron", "expression": "0 10 * * 1-5"}}],
    }
    assert agent._resolve_component_schedule(comp, registry)["schedule"] == "0 10 * * 1-5"
    fallback = agent._resolve_component_schedule(comp, {"schema": "nope"})
    assert fallback["schedule"] == "0 8 * * 1-5"
    assert fallback["schedule_resolved_from"].startswith("literal_fallback:")
    plain = {"component": "x", "schedule": "0 9 * * 1-5", "monitor_lane_ids": [LANE]}
    assert agent._resolve_component_schedule(plain, registry) is plain


def core_health_loop(agent):
    tree = ast.parse((ROOT / "scripts" / "system_health_agent.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_health_check")
    stop = next(
        i
        for i, n in enumerate(fn.body)
        if isinstance(n, ast.For) and isinstance(n.iter, ast.Name) and n.iter.id == "MONITORED_COMPONENTS"
    )
    fn.body = fn.body[: stop + 1] + [ast.Return(ast.Name("report", ast.Load()))]
    namespace = dict(vars(agent))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), "<loop>", "exec"), namespace)
    return namespace["run_health_check"]


@pytest.fixture
def loop(agent, monkeypatch, tmp_path):
    escalations, notices = [], []

    class Conn:
        closed = 0

        def cursor(self):
            return self

        def execute(self, sql, params):
            pass

        def commit(self):
            pass

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)

    code = tmp_path / "code"
    (code / "config").mkdir(parents=True)
    monkeypatch.setattr(agent, "PROJECT_ROOT", code)  # no registry: the reviewed literal applies
    monkeypatch.setattr(agent, "datetime", Clock)
    monkeypatch.setattr(agent, "MONITORED_COMPONENTS", [component(agent)])
    monkeypatch.setattr(agent, "_get_conn", lambda: Conn())
    monkeypatch.setattr(agent, "_prev_scheduled_fire", lambda *_a: NOW - timedelta(days=1))
    monkeypatch.setattr(agent, "_check_lock_contention", lambda *_a: {"status": "FREE"})
    monkeypatch.setattr(agent, "_escalate", lambda comp, check, conn: escalations.append(dict(check)))
    monkeypatch.setattr(agent, "_notify_recovered", lambda comp, check, conn: notices.append(dict(check)) or "sent")
    monkeypatch.setattr(agent, "_attempt_retry", lambda *_a, **_k: pytest.fail("no retry in this projection"))
    monkeypatch.delenv("TRADEAI_HEALTH_AGENT_RETRY", raising=False)
    pytz = types.ModuleType("pytz")
    pytz.timezone = lambda name: timezone(timedelta(hours=-4))
    monkeypatch.setitem(sys.modules, "pytz", pytz)
    path = Path(os.environ["TRADEAI_STATE_ROOT"]) / "data" / "runtime" / (LANE + "_last.json")
    return {"run": core_health_loop(agent), "path": path, "escalations": escalations, "notices": notices}


def test_incident_shape_is_debounced_in_the_real_loop(loop):
    loop["path"].write_text(json.dumps(receipt()))
    report = loop["run"](dry_run=False)
    check = report["checks"][0]
    assert check["status"] == "OK" and check["output_reason"] == "latest_receipt_failed_debounced"
    assert check["schedule"] == "0 10 * * 1-5"
    assert report["summary"]["debounced"] == 1 and report["summary"]["failed"] == 0
    assert loop["escalations"] == [] and len(loop["notices"]) == 1


def test_sustained_failure_still_escalates_in_the_real_loop(loop):
    loop["path"].write_text(json.dumps(receipt(ok_at=(NOW - timedelta(minutes=30)).isoformat())))
    report = loop["run"](dry_run=False)
    check = report["checks"][0]
    assert check["status"] == "OUTPUT_INVALID" and check["action_taken"] == "retry_disarmed_escalated"
    assert len(loop["escalations"]) == 1 and loop["notices"] == []


def test_dry_run_sends_no_recovered_note(loop):
    loop["path"].write_text(json.dumps(receipt(status="ok", exit=0, ok_at=receipt()["finished_at"])))
    report = loop["run"](dry_run=True)
    assert report["checks"][0]["status"] == "OK" and loop["notices"] == []


class EventsConn:
    rowcount = 0

    def __init__(self, row, resolved=0):
        self.row, self.sql, self.resolved = row, [], resolved

    def cursor(self):
        return self

    def execute(self, sql, params):
        self.sql.append((sql, params))
        self.rowcount = self.resolved if sql.startswith("UPDATE") else -1

    def fetchone(self):
        return self.row

    def commit(self):
        pass


@pytest.mark.parametrize("accepted", [True, False])
def test_recovered_note_is_sent_once_per_escalation_at_p2(agent, monkeypatch, accepted):
    calls, events = [], []
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda message, **kw: calls.append((message, kw)) or accepted
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    monkeypatch.setattr(agent, "_log_event", lambda conn, comp, kind, sev, msg, **kw: events.append((kind, sev, kw)))
    comp = component(agent)
    check = {"status": "OK", "freshness_evidence": {"success_at": NOW.isoformat(), "debounced": True}}
    conn = EventsConn((NOW - timedelta(minutes=20), None))
    assert agent._notify_recovered(comp, check, conn) == ("sent" if accepted else "rejected")
    assert len(calls) == 1
    message, kw = calls[0]
    assert kw == {"priority": "P2", "producer": "system_health_agent", "dedupe_minutes": 120}
    assert message.startswith("✅ SYSTEM HEALTH: Finviz Screener — recovered") and "0 10 * * 1-5" in message
    assert events == [
        (
            "RECOVERY_NOTICE" if accepted else "RECOVERY_NOTICE_REJECTED",
            "INFO",
            {"action": "notification_intent", "success": accepted},
        )
    ]
    sql = conn.sql[0][0]
    assert "event_type='ESCALATION' AND success IS TRUE" in sql and "RECOVERY_NOTICE'" in sql


@pytest.mark.parametrize(
    "row",
    [(None, None), (NOW - timedelta(minutes=20), NOW - timedelta(minutes=5)), None],
)
def test_no_recovered_note_when_none_is_owed(agent, monkeypatch, row):
    monkeypatch.setattr(agent, "_send_alert", lambda *a, **k: pytest.fail("nothing is owed"))
    assert agent._notify_recovered(component(agent), {"status": "OK"}, EventsConn(row)) == "not_owed"


def test_recovered_lookup_failure_sends_nothing(agent, monkeypatch):
    class Broken:
        def cursor(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(agent, "_send_alert", lambda *a, **k: pytest.fail("no send without the ledger"))
    assert agent._notify_recovered(component(agent), {"status": "OK"}, Broken()) == "lookup_failed"


def test_recovery_resolves_open_escalations_so_the_siem_incident_closes(agent, monkeypatch):
    """SIEM P1 "finviz_screener_runner PIPELINE_FAILURE" was the health agent's own ESCALATION rows (message
    "OUTPUT_INVALID") re-read by /api/v2/system/siem for 14 days while lifecycle_state stayed 'active'. An OK poll
    resolves them (lifecycle only, never deleted) even when no recovered note is owed (escalation > 24 h old)."""
    monkeypatch.setattr(agent, "_send_alert", lambda *a, **k: pytest.fail("nothing is owed"))
    conn = EventsConn((None, None), resolved=2)
    assert agent._notify_recovered(component(agent), {"status": "OK"}, conn) == "not_owed; resolved 2"
    sql, params = conn.sql[1]
    assert sql == agent.SQL_RESOLVE_ESCALATIONS and params == ["finviz_screener_runner"]
    assert "lifecycle_state='resolved'" in sql and "event_type='ESCALATION'" in sql and "DELETE" not in sql.upper()


def test_siem_reads_only_unresolved_health_rows_and_classifies_escalations_p1():
    """The SIEM source this PR relies on: resolved rows leave the SIEM view; OUTPUT_INVALID text is P1."""
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    fn = src[src.index("def _system_siem_dashboard") :]
    she = fn[fn.index("FROM system_health_events") :][:200]
    assert "lifecycle_state,'active') <> 'resolved'" in she
    assert '"output_invalid" in t' in fn and '"PIPELINE_FAILURE", "P1"' in fn
