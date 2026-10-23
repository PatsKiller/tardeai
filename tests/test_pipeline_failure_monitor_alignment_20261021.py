"""Focused, hermetic tests for pipeline remediation/health counter alignment."""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ha = _load("health_agent_pipeline_alignment", SCRIPTS / "health_agent.py")
rp = _load("remediate_pipeline_failures_alignment", SCRIPTS / "remediate_pipeline_failures.py")
esc = _load("escalation_handler_pipeline_alignment", SCRIPTS / "claude_escalation_handler.py")


def test_health_and_remediator_share_empty_errors_filter(monkeypatch):
    from lib.pipeline_failure_counts import SUBSTANTIVE_FAILURE_FILTER

    health_queries = []
    monkeypatch.setattr(
        ha, "_db", lambda sql, **kw: health_queries.append(sql) or [{"pipeline_key": "symbol_enrichment", "c": 3}]
    )
    assert ha._count_real_pipeline_failures() == 3
    assert SUBSTANTIVE_FAILURE_FILTER in health_queries[0]

    remediation_queries = []

    def db(sql, params=None, fetch="one"):
        remediation_queries.append(sql)
        if "FROM pipeline_runs f" in sql:
            return [] if fetch == "all" else {"c": 0}
        return {"c": 0}

    monkeypatch.setattr(rp, "_db", db)
    monkeypatch.setattr(rp, "_count_circuit_open_logs", lambda _hours: 0)
    monkeypatch.setattr(rp, "_count_rate_limit_log_hits", lambda _hours: 0)
    monkeypatch.setattr(rp, "_orchestrator_process_alive", lambda: False)
    rp.diagnose()
    assert SUBSTANTIVE_FAILURE_FILTER in remediation_queries[0]


def test_escalation_verifier_shares_empty_errors_filter(monkeypatch):
    from lib.pipeline_failure_counts import SUBSTANTIVE_FAILURE_FILTER

    queries = []
    monkeypatch.setattr(esc, "_db_verify", lambda sql, params=None: queries.append(sql) or (True, 0, "ok"))
    cleared, note = esc._verify_remediation({"component": "health:execution_health:pipeline_failures"})
    assert cleared is True
    assert note.startswith("pipeline_ok unrecovered=0")
    assert SUBSTANTIVE_FAILURE_FILTER in queries[0]


def test_escalation_notify_failure_is_durably_recorded(monkeypatch, tmp_path):
    import types

    monkeypatch.setattr(esc, "LOG_DIR", tmp_path)
    monkeypatch.setattr(esc, "_ensure_scripts_path", lambda: None)
    monkeypatch.setitem(
        sys.modules,
        "telegram_alert",
        types.SimpleNamespace(send_telegram=lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("delivery down"))),
    )

    assert esc._notify("operator review") is False
    rows = [
        json.loads(line)
        for line in (tmp_path / "claude_escalation_notification_failures.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["error_type"] == "RuntimeError"
    assert rows[0]["error"] == "Telegram delivery failed; exception details omitted to avoid credential leakage."
    assert "operator review" not in json.dumps(rows[0])
    assert stat.S_IMODE((tmp_path / "claude_escalation_notification_failures.jsonl").stat().st_mode) == 0o600


def test_escalation_notify_rejected_return_is_durably_recorded(monkeypatch, tmp_path):
    import types

    monkeypatch.setattr(esc, "LOG_DIR", tmp_path)
    monkeypatch.setattr(esc, "_ensure_scripts_path", lambda: None)
    monkeypatch.setitem(sys.modules, "telegram_alert", types.SimpleNamespace(send_telegram=lambda *_a, **_kw: False))

    assert esc._notify("held for review") is False
    rows = [
        json.loads(line)
        for line in (tmp_path / "claude_escalation_notification_failures.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 1 and rows[0]["error_type"] == "RuntimeError"
    assert "held for review" not in json.dumps(rows[0])


def test_component_only_failures_are_not_classified_as_master_orchestrator_failure(monkeypatch):
    db_calls = 0

    def db(sql, params=None, fetch="one"):
        nonlocal db_calls
        db_calls += 1
        if "FROM pipeline_runs f" in sql:
            return [
                {"pipeline_key": "symbol_enrichment", "c": 1, "last_sum": "x"},
                {"pipeline_key": "a1a_compliance", "c": 1, "last_sum": "y"},
                {"pipeline_key": "indicator_engine", "c": 1, "last_sum": "z"},
            ]
        return {"c": 0}

    monkeypatch.setattr(rp, "_db", db)
    monkeypatch.setattr(rp, "_count_circuit_open_logs", lambda _hours: 0)
    monkeypatch.setattr(rp, "_count_rate_limit_log_hits", lambda _hours: 0)
    monkeypatch.setattr(rp, "_orchestrator_process_alive", lambda: False)
    diagnosis = rp.diagnose()
    assert diagnosis["unrecovered_keys"] == ["symbol_enrichment", "a1a_compliance", "indicator_engine"]
    assert diagnosis["root_cause"] == "component_stage_fail"
    assert db_calls >= 4
    assert rp._component_stage_failures_only(diagnosis["unrecovered_keys"])
    assert not rp._component_stage_failures_only([])
    assert not rp._component_stage_failures_only(["trade_ai_orchestrator"])
    assert not rp._component_stage_failures_only(["symbol_enrichment", "trade_ai_orchestrator"])


def test_unrelated_failure_beyond_top_15_component_keys_is_not_hidden(monkeypatch):
    # Reproduce the old SQL LIMIT 15 behavior: the unrelated master failure sorts
    # below many component keys and must still reach root-cause classification.
    rows = [
        {"pipeline_key": name, "c": 1, "last_sum": "x"}
        for name in ["symbol_enrichment", "a1a_compliance", "indicator_engine"]
        + [f"component_{i:02d}" for i in range(13)]
        + ["trade_ai_orchestrator"]
    ]

    def db(sql, params=None, fetch="one"):
        if "FROM pipeline_runs f" in sql:
            assert "LIMIT 15" not in sql
            return rows
        return {"c": 0}

    monkeypatch.setattr(rp, "_db", db)
    monkeypatch.setattr(rp, "_count_circuit_open_logs", lambda _hours: 0)
    monkeypatch.setattr(rp, "_count_rate_limit_log_hits", lambda _hours: 0)
    monkeypatch.setattr(rp, "_orchestrator_process_alive", lambda: False)

    diagnosis = rp.diagnose()

    assert len(diagnosis["unrecovered_keys"]) == 17
    assert diagnosis["root_cause"] == "orchestrator_stage_fail"


def test_component_only_failure_holds_for_owner_review_without_running_orchestrator(monkeypatch):
    outcomes = []
    diagnosis = {
        "root_cause": "component_stage_fail",
        "unrecovered_keys": ["symbol_enrichment"],
        "unrecovered_count": 1,
        "zombie_running": 0,
        "sla_backlog": 0,
    }
    monkeypatch.setattr(rp, "diagnose", lambda: diagnosis)
    monkeypatch.setattr(rp.rcmem, "record_error", lambda *a, **kw: None)
    monkeypatch.setattr(rp.rcmem, "select_next_strategy", lambda *_a, **_kw: {"id": "diagnose_only"})
    monkeypatch.setattr(
        rp.rcmem, "record_outcome", lambda *a, **kw: outcomes.append((a, kw)) or {"hold_until": "2030-01-01T00:00:00Z"}
    )
    monkeypatch.setattr(rp.rcmem, "summary_for", lambda *_a, **_kw: {"hold_until": "2030-01-01T00:00:00Z"})
    monkeypatch.setattr(
        rp,
        "_spawn_detached",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("must not run master orchestrator")),
    )

    result = rp.run()
    assert result["held"] is True and result["ok"] is False
    assert result["outcome"] == "HELD" and result["operator_action_required"] is True
    assert result["hold_until"]
    assert result["strategy_id"] == "operator_review_component_failures"
    assert len(outcomes) == 1 and outcomes[0][1]["hold_minutes"] == 60


def test_underfilled_monitor_queries_latest_receipt_per_distinct_run_date(monkeypatch):
    monkeypatch.setattr(ha, "_POLICY", {"lane_ownership": {"enabled": True, "underfilled_streak": 3}})
    queries = []

    def db(sql, params=None, fetch="one"):
        queries.append((sql, params, fetch))
        if len(queries) == 1:
            return [{"run_label": "0700"}]
        # One latest receipt per date, ordered newest first. The earlier same-day
        # retry is intentionally absent from this DISTINCT ON query result.
        return [
            {"run_date": "2026-10-21", "status": "RUN_UNDERFILLED", "reason_codes": ["UNIVERSE_TOO_SMALL"]},
            {"run_date": "2026-10-20", "status": "RUN_HEALTHY", "reason_codes": []},
            {"run_date": "2026-10-19", "status": "RUN_UNDERFILLED", "reason_codes": ["UNIVERSE_TOO_SMALL"]},
        ]

    monkeypatch.setattr(ha, "_db", db)
    assert ha.collect_underfilled_streak() == []
    sql, params, fetch = queries[1]
    assert "DISTINCT ON (run_date)" in sql
    assert "status <> 'RUNNING'" in sql  # unfinished start rows cannot mask completed daily outcomes
    assert "ORDER BY run_date DESC, finished_at DESC NULLS LAST, id DESC" in sql
    assert params == ("0700", 6) and fetch == "all"


def test_health_pipeline_component_failures_are_owner_action(monkeypatch):
    monkeypatch.setattr(
        ha,
        "_db",
        lambda sql, **kw: [
            {"pipeline_key": "symbol_enrichment", "c": 2},
            {"pipeline_key": "indicator_engine", "c": 1},
        ],
    )
    findings = ha.collect_execution_health()
    pipeline = next(f for f in findings if f["type"] == "pipeline_failures")
    assert pipeline["held"] is True
    assert pipeline["operator_action"] is True
    assert pipeline["owner"] == "Pipeline Operations"
    assert "owner review required" in pipeline["message"]
    assert (
        ha.run_auto_remediation(
            {"auto_remediate": {"enabled": True, "finding_types": ["pipeline_failures"]}},
            [pipeline],
        )
        == []
    )


def test_escalation_held_payload_is_detected_before_exit_status():
    from scripts import claude_escalation_handler as eh

    payload = eh._held_retry_outcome(
        'exit_code=1: diagnostic log\n{"outcome":"HELD","held":true,"hold_until":"2030-01-01T00:00:00Z"}'
    )
    assert payload["outcome"] == "HELD"
    assert payload["hold_until"] == "2030-01-01T00:00:00Z"
    assert eh._held_retry_outcome('{"component":"unrelated","held":true}') is None
    assert eh._held_retry_outcome('{"outcome":"FAILED","ok":false}') is None
    assert eh._held_retry_outcome('{"outcome":"CLEARED","ok":true}') is None


def test_executor_preserves_held_json_after_long_status_zero_stdout(monkeypatch):
    from scripts import claude_escalation_handler as eh

    payload = {"outcome": "HELD", "held": True, "hold_until": "2030-01-01T00:00:00Z", "note": "diagnosis " + "x" * 1200}

    class FakeProcess:
        returncode = 0

        def __init__(self, *_args, **_kwargs):
            pass

        def communicate(self, timeout=None):
            return "diagnostic-prefix " + __import__("json").dumps(payload), ""

    monkeypatch.setattr(eh, "_check_allowlist", lambda *_a: (True, "test"))
    monkeypatch.setattr(eh.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(eh, "_cmd_timeout_seconds", lambda *_a: 1)
    monkeypatch.setattr(eh, "_log_retry", lambda *_a, **_kw: None)
    executed, success, output = eh._execute_retry_cmd(
        {"retry_cmd": "python scripts/remediate_pipeline_failures.py"}, {}, dry_run=False
    )

    assert executed is True and success is True
    parsed = eh._held_retry_outcome(output)
    assert parsed["hold_until"] == payload["hold_until"]
    assert parsed["note"] == payload["note"]


def test_escalation_handler_defers_held_result_without_verification_or_llm(monkeypatch, tmp_path):
    import json
    from scripts import claude_escalation_handler as eh

    queue = tmp_path / "queue.json"
    stale = tmp_path / "stale.json"
    queue.write_text(
        json.dumps(
            [
                {
                    "component": "health:execution_health:pipeline_failures",
                    "detail": "component stage failed",
                    "fixable": True,
                    "retry_cmd": "python scripts/remediate_pipeline_failures.py",
                }
            ]
        )
    )
    stale.write_text("[]")
    monkeypatch.setattr(eh, "QUEUE_FILE", queue)
    monkeypatch.setattr(eh, "STALENESS_QUEUE_FILE", stale)
    monkeypatch.setattr(eh, "_get_conn", lambda: None)
    monkeypatch.setattr(eh, "_load_allowlist", lambda: {})
    monkeypatch.setattr(
        eh,
        "_execute_retry_cmd",
        lambda *_a, **_kw: (
            True,
            False,
            'exit_code=0 {"outcome":"HELD","held":true,'
            '"hold_until":"2030-01-01T00:00:00Z","note":"owner review required"}',
        ),
    )
    monkeypatch.setattr(
        eh, "_verify_remediation", lambda *_a: (_ for _ in ()).throw(AssertionError("HELD must bypass verification"))
    )
    monkeypatch.setattr(eh, "_notify", lambda msg: (alerts.append(msg), True)[1])
    monkeypatch.setattr(eh.time, "sleep", lambda *_a: None)
    alerts = []

    eh.process_queue(tier1_only=True)

    assert len(alerts) == 1 and "OPERATOR REVIEW REQUIRED" in alerts[0]
    assert "2030-01-01T00:00:00Z" in alerts[0]
    held_item = json.loads(queue.read_text())[0]
    assert held_item["outcome"] == "HELD"
    assert held_item["hold_until"] == "2030-01-01T00:00:00Z"
    assert held_item["_operator_review_notified"] is True
