"""Freshness identity and receipt outcomes use isolated files and pure projections."""

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

from scripts.lib.system_health_freshness import freshness_at, lane_receipt_freshness, schedule_intent

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 12, 14, 15, tzinfo=timezone.utc)
LANE = "finviz-screener-runner"
SCRIPT = "finviz_screener_runner.py"
COVERS = ["scripts/system_health_agent.py:799"]


def test_repeated_stale_escalation_keeps_content_when_database_dedupe_fails(agent, monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "_send_alert", lambda message, **kwargs: calls.append((message, kwargs)) or True)
    monkeypatch.setattr(agent, "_log_event", lambda *a, **k: None)
    comp = component(agent)
    comp["critical"] = False
    original = "2026-10-09T13:00:00Z"
    for age in (4249.5, 4254.4):
        agent._escalate(
            comp,
            {
                "status": "STALE",
                "age_min": age,
                "action_taken": "retry_disarmed",
                "freshness_evidence": {"success_at": original},
            },
            None,
        )
    assert calls[0] == calls[1]
    assert original in calls[0][0] and "4249.5" not in calls[0][0]
    assert calls[0][1]["dedupe_minutes"] == 120


@pytest.fixture
def agent(tmp_path, monkeypatch):
    path = ROOT / "scripts" / "system_health_agent.py"
    spec = importlib.util.spec_from_file_location("_system_health_freshness_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert Path(mod.__file__) == path
    code, state = tmp_path / "code", tmp_path / "state"
    (code / "logs").mkdir(parents=True)
    (state / "logs").mkdir(parents=True)
    (state / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setattr(mod, "PROJECT_ROOT", code)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    return mod


def log_file(path, stamp):
    path.write_text("fixture log activity\n", encoding="utf-8")
    os.utime(path, (stamp.timestamp(), stamp.timestamp()))
    return path


def receipt(**over):
    finished = (NOW - timedelta(minutes=5)).isoformat()
    return {
        "schema": "LaneRunReceipt@v1",
        "lane_id": LANE,
        "script": SCRIPT,
        "mode": "live",
        "status": "ok",
        "exit": 0,
        "started_at": (NOW - timedelta(minutes=7)).isoformat(),
        "finished_at": finished,
        "ok_at": finished,
        **over,
    }


def component(agent):
    return dict(next(c for c in agent.MONITORED_COMPONENTS if c["component"] == "finviz_screener_runner"))


def test_governed_log_wins_even_when_code_log_is_newer(agent):
    state = Path(os.environ["TRADEAI_STATE_ROOT"])
    governed = log_file(state / "logs" / "unit.log", NOW - timedelta(hours=2))
    log_file(agent.PROJECT_ROOT / "logs" / "unit.log", NOW - timedelta(minutes=1))
    assert agent._resolve_log("unit.log") == governed
    report = agent._check_log_freshness("unit.log", 30, now=NOW)
    assert report["status"] == "STALE" and report["age_min"] == 120
    assert report["signal_source"] == "governed_state" and report["source_drift"] is None
    assert report["business_output_acceptance"] == "NOT_MEASURED"
    assert report["activity_at"] and "success_at" not in report


def test_stale_code_copy_cannot_mask_fresh_governed_log(agent):
    state = Path(os.environ["TRADEAI_STATE_ROOT"])
    log_file(agent.PROJECT_ROOT / "logs" / "unit.log", NOW - timedelta(days=4))
    expected = log_file(state / "logs" / "unit.log", NOW - timedelta(minutes=2))
    report = agent._check_log_freshness("unit.log", 30, now=NOW)
    assert report["status"] == "OK" and report["age_min"] == 2
    assert report["signal_path"] == str(expected)


def test_legacy_log_fallback_is_explicit_activity_without_acceptance(agent):
    path = log_file(agent.PROJECT_ROOT / "logs" / "unit.log", NOW - timedelta(minutes=1))
    report = agent._check_log_freshness("unit.log", 30, now=NOW)
    assert report["signal_path"] == str(path) and report["status"] == "OK"
    assert report["signal_source"] == "legacy_code_fallback"
    assert report["source_drift"] == "governed_log_absent_legacy_fallback"
    assert report["business_output_acceptance"] == "NOT_MEASURED"


def test_missing_log_retains_governed_identity_and_unknown_age(agent):
    report = agent._check_log_freshness("absent.log", 30, now=NOW)
    assert report["status"] == "MISSING" and report["age_min"] is None
    assert report["signal_path"] == str(Path(os.environ["TRADEAI_STATE_ROOT"]) / "logs" / "absent.log")


def test_supplied_observation_clock_and_timezone_drive_age(agent):
    observed = datetime(2020, 1, 2, 9, 0, tzinfo=timezone(timedelta(hours=-5)))
    log_file(Path(os.environ["TRADEAI_STATE_ROOT"]) / "logs" / "unit.log", observed - timedelta(minutes=10))
    report = agent._check_log_freshness("unit.log", 30, now=observed)
    assert report["status"] == "OK" and report["age_min"] == 10
    assert report["observed_at"] == "2020-01-02T14:00:00+00:00"


def test_future_activity_is_not_coerced_into_fresh_zero_age(agent):
    log_file(Path(os.environ["TRADEAI_STATE_ROOT"]) / "logs" / "unit.log", NOW + timedelta(hours=1))
    report = agent._check_log_freshness("unit.log", 30, now=NOW)
    assert report["status"] == "ERROR" and report["age_min"] is None
    assert report["reason"] == "success_timestamp_in_future"


def test_schedule_grace_and_stale_boundaries_remain_explicit():
    fire = NOW - timedelta(minutes=30)
    old = NOW - timedelta(hours=4)
    assert freshness_at(old, now=NOW, max_age_min=9000, prev_fire=fire)["status"] == "STALE"
    within = freshness_at(old, now=fire + timedelta(minutes=5), max_age_min=1, prev_fire=fire)
    assert within["status"] == "OK" and within["note"] == "within_run_grace"
    assert freshness_at(old.replace(tzinfo=None), now=NOW, max_age_min=1)["status"] == "ERROR"


def test_success_receipt_reports_run_evidence_without_business_acceptance():
    report = lane_receipt_freshness(receipt(), lane_id=LANE, script=SCRIPT, now=NOW, max_age_min=60)
    assert report["status"] == "OK" and report["age_min"] == 5
    assert report["signal_kind"] == "LaneRunReceipt@v1"
    assert report["business_output_acceptance"] == "NOT_MEASURED"


def test_zero_run_metadata_never_qualifies_as_business_output_acceptance():
    doc = receipt(summary={"screeners_run": 0, "total_new_tickers": 0})
    report = lane_receipt_freshness(doc, lane_id=LANE, script=SCRIPT, now=NOW, max_age_min=60)
    assert report["business_output_acceptance"] == "NOT_MEASURED"


def test_registry_schedule_conflict_does_not_override_unmeasured_installed_expectation():
    comp = {"schedule": "0 8 * * 1-5", "monitor_lane_ids": [LANE]}
    registry = {
        "schema": "LaneRegistry@v1",
        "lanes": [{"lane_id": LANE, "state": "ACTIVE", "scheduler": {"kind": "cron", "expression": "0 10 * * 1-5"}}],
    }
    report = schedule_intent(comp, registry)
    assert report["monitor_schedule"] == "0 8 * * 1-5" and report["installed_schedule"] == "NOT_MEASURED"
    assert report["source_intent_status"] == "SOURCE_INTENT_ONLY" and report["declaration_differs"] is True
    assert comp["schedule"] == "0 8 * * 1-5"


def test_retired_source_slot_does_not_suppress_unverified_installed_monitor():
    comp = {"schedule": "0 12,14,16 * * 1-5", "monitor_lane_ids": ["slot"]}
    registry = {
        "schema": "LaneRegistry@v1",
        "lanes": [
            {"lane_id": "slot", "state": "RETIRED", "scheduler": {"kind": "cron", "expression": "0 12,14,16 * * 1-5"}}
        ],
    }
    report = schedule_intent(comp, registry)
    assert report["monitor_schedule"] == comp["schedule"] and report["declaration_differs"] is True
    assert report["installed_schedule"] == "NOT_MEASURED"


@pytest.mark.parametrize(
    "registry",
    [
        None,
        {},
        {"schema": "LaneRegistry@v1", "lanes": []},
        {"schema": "LaneRegistry@v1", "lanes": [{"lane_id": LANE}, {"lane_id": LANE}]},
    ],
)
def test_unmeasured_source_mapping_remains_unknown_with_protective_expectation(registry):
    report = schedule_intent({"schedule": "0 8 * * 1-5", "monitor_lane_ids": [LANE]}, registry)
    assert report["source_intent_status"] == "NOT_MEASURED" and report["declaration_differs"] is None
    assert report["monitor_schedule"] == "0 8 * * 1-5"


@pytest.mark.parametrize("exit_code", [0, 1])
def test_failed_attempt_never_promotes_carried_ok_at_even_within_grace(exit_code):
    doc = receipt(status="failed", exit=exit_code, ok_at=(NOW - timedelta(minutes=10)).isoformat())
    report = lane_receipt_freshness(doc, lane_id=LANE, script=SCRIPT, now=NOW, max_age_min=60, prev_fire=NOW)
    assert report["status"] == "FAILED" and report["age_min"] == 10
    assert report["reason"] == "latest_receipt_failed" and report["latest_attempt_status"] == "failed"


@pytest.mark.parametrize(
    "over",
    [
        {"schema": "wrong"},
        {"lane_id": "another-lane"},
        {"script": "other.py"},
        {"mode": "dry_run"},
        {"status": []},
        {"status": "running"},
        {"exit": None},
        {"exit": False},
        {"exit": 1},
        {"ok_at": None},
        {"ok_at": "2026-10-12T14:10:00"},
        {"started_at": None},
        {"started_at": "2026-10-12T14:12:00+00:00"},
        {"finished_at": "2026-10-12T15:00:00+00:00"},
        {"ok_at": "2026-10-12T14:00:00+00:00"},
    ],
)
def test_receipt_identity_outcome_and_time_refusals_are_typed(over):
    report = lane_receipt_freshness(receipt(**over), lane_id=LANE, script=SCRIPT, now=NOW, max_age_min=60)
    assert report["status"] == "ERROR" and report["business_output_acceptance"] == "NOT_MEASURED"


@pytest.mark.parametrize("document", [None, [], "wrong"])
def test_non_object_receipts_fail_closed(document):
    assert lane_receipt_freshness(document, lane_id=LANE, script=SCRIPT, now=NOW, max_age_min=60)["status"] == "ERROR"


@pytest.mark.parametrize("document", [None, "{bad json", receipt(status="failed", exit=1)])
def test_receipt_missing_unreadable_or_failed_never_falls_back_to_fresh_log(agent, monkeypatch, document):
    state = Path(os.environ["TRADEAI_STATE_ROOT"])
    log_file(state / "logs" / "finviz_screener.log", NOW - timedelta(minutes=1))
    path = state / "data" / "runtime" / (LANE + "_last.json")
    if document is not None:
        path.write_text(document if isinstance(document, str) else json.dumps(document), encoding="utf-8")

    def forbid_log_fallback(*_a, **_k):
        pytest.fail("a declared run receipt must never use log fallback")

    monkeypatch.setattr(agent, "_check_log_freshness", forbid_log_fallback)
    report = agent._check_component_freshness(component(agent), now=NOW)
    assert report["status"] in {"MISSING", "ERROR", "FAILED"} and report["signal_path"] == str(path)


def core_health_loop(agent):
    """Execute the real component loop without subsequent host-wide collectors."""
    tree = ast.parse((ROOT / "scripts" / "system_health_agent.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_health_check")
    stop = next(
        i
        for i, n in enumerate(fn.body)
        if isinstance(n, ast.For) and isinstance(n.iter, ast.Name) and n.iter.id == "MONITORED_COMPONENTS"
    )
    fn.body = fn.body[: stop + 1] + [ast.Return(ast.Name("report", ast.Load()))]
    namespace = dict(vars(agent))
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), "<isolated-health-loop>", "exec"),
        namespace,
    )
    return namespace["run_health_check"]


def test_failed_receipt_is_actionable_and_disarm_reason_survives_core_loop(agent, monkeypatch):
    state = Path(os.environ["TRADEAI_STATE_ROOT"])
    (state / "data" / "runtime" / (LANE + "_last.json")).write_text(json.dumps(receipt(status="failed", exit=1)))
    escalations = []
    statements = []

    class Conn:
        closed = 0

        def cursor(self):
            return self

        def execute(self, sql, params):
            statements.append((sql, params))

        def commit(self):
            pass

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(agent, "datetime", Clock)
    monkeypatch.setattr(agent, "MONITORED_COMPONENTS", [component(agent)])
    monkeypatch.setattr(agent, "_get_conn", lambda: Conn())
    monkeypatch.setattr(agent, "_prev_scheduled_fire", lambda *_a: NOW)
    monkeypatch.setattr(agent, "_check_lock_contention", lambda *_a: {"status": "FREE"})
    monkeypatch.setattr(agent, "_escalate", lambda comp, check, conn: escalations.append(dict(check)))
    pytz = types.ModuleType("pytz")

    def fixture_zone(name):
        assert name == "US/Eastern"
        # This fixed October fixture needs UTC-4; no live timezone database or
        # optional dependency is needed to exercise the isolated component loop.
        return timezone(timedelta(hours=-4))

    pytz.timezone = fixture_zone
    monkeypatch.setitem(sys.modules, "pytz", pytz)
    monkeypatch.delenv("TRADEAI_HEALTH_AGENT_RETRY", raising=False)

    def forbid_retry(*_a, **_k):
        pytest.fail("retry execution is outside this isolated health projection")

    monkeypatch.setattr(agent, "_attempt_retry", forbid_retry)
    report = core_health_loop(agent)(dry_run=False)
    check = report["checks"][0]
    assert check["status"] == "OUTPUT_INVALID" and check["freshness_evidence"]["status"] == "FAILED"
    assert check["action_taken"] == "retry_disarmed_escalated"
    assert "TRADEAI_HEALTH_AGENT_RETRY" in check["recovery_reason"]
    assert report["summary"]["retried"] == 0 and report["summary"]["retry_disarmed"] == 1
    assert len(escalations) == 1 and statements


@pytest.mark.parametrize("accepted", [True, False])
@pytest.mark.parametrize("requested_dedupe", [None, 120])
def test_urgent_delivery_intent_reaches_transport_with_dedupe_off(agent, monkeypatch, accepted, requested_dedupe):
    calls = []
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda message, **kwargs: calls.append((message, kwargs)) or accepted
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    assert agent._send_alert("fixture operator action", urgent=True, dedupe_minutes=requested_dedupe) is accepted
    assert calls == [
        ("fixture operator action", {"priority": "P1", "producer": "system_health_agent", "dedupe_minutes": 0})
    ]


def test_firing_annotation_names_the_exercised_transport():
    tree = ast.parse((ROOT / "scripts" / "system_health_agent.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_send_alert")
    sites = [
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "send_telegram"
    ]
    assert COVERS == [f"scripts/system_health_agent.py:{line}" for line in sites]


def test_transport_exception_returns_rejected_intent(agent, monkeypatch):
    fake = types.ModuleType("telegram_alert")

    def unavailable(*_a, **_k):
        raise RuntimeError("fixture gateway unavailable")

    fake.send_telegram = unavailable
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    assert agent._send_alert("fixture operator action", urgent=True) is False


@pytest.mark.parametrize("critical", [False, True])
def test_failed_intent_does_not_suppress_next_poll_or_claim_delivery(agent, monkeypatch, critical):
    records, queries, calls = [], [], []
    outcomes = iter([False, True])
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda message, **kwargs: calls.append((message, kwargs)) or next(outcomes)
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)

    class Conn:
        def cursor(self):
            return self

        def execute(self, sql, params):
            queries.append((sql, params))

        def fetchone(self):
            # Match the actual successful-escalation predicate; a failed record
            # would suppress the retry if the production SQL omitted success.
            success_only = "success IS TRUE" in queries[-1][0]
            return [sum(row[0] == "ESCALATION" and (not success_only or row[1]["success"]) for row in records)]

    monkeypatch.setattr(agent, "_log_event", lambda conn, comp, kind, severity, msg, **kw: records.append((kind, kw)))
    comp = {**component(agent), "critical": critical}
    check = {
        "status": "STALE",
        "action_taken": "retry_disarmed",
        "freshness_evidence": {"success_at": "2026-10-09T13:00:00Z"},
    }
    conn = Conn()
    for _ in range(3):
        agent._escalate(comp, check, conn)

    assert len(calls) == 2 and calls[0] == calls[1]
    assert calls[0][1]["priority"] == ("P1" if critical else "P3")
    assert calls[0][1]["dedupe_minutes"] == (0 if critical else 120)
    assert all("success IS TRUE" in sql for sql, _ in queries)
    assert records == [
        ("ESCALATION_REJECTED", {"action": "notification_intent", "success": False}),
        ("ESCALATION", {"action": "notification_intent", "success": True}),
        ("ESCALATION_DEDUPED", {"success": True}),
    ]
