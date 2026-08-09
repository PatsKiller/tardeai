"""Validate escalation verify-after-fix + timeout budgets (issues 1–5)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load_handler():
    path = SCRIPTS / "claude_escalation_handler.py"
    spec = importlib.util.spec_from_file_location("claude_escalation_handler", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Avoid running main side effects
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def esc():
    return _load_handler()


def test_finding_type_from_component(esc):
    assert esc._finding_type_from_component("health:execution_health:agent_jobs_stuck") == "agent_jobs_stuck"
    assert esc._finding_type_from_component("health:data_quality:agent::test_x") == "agent::test_x"


def test_cmd_timeout_budgets(esc):
    al = {"max_runtime_seconds": 300}
    assert esc._cmd_timeout_seconds(
        ".venv/bin/python scripts/process_watchlist_agent_jobs.py --limit 40", al
    ) >= 300
    # Market data fails fast (does not block full batch for 300s)
    assert esc._cmd_timeout_seconds(
        ".venv/bin/python scripts/external_market_data_ingest.py --quotes", al
    ) <= 90
    assert esc._cmd_timeout_seconds(
        "bash linux_launchers/run_pg_backup.sh", al
    ) >= 900
    assert esc._cmd_timeout_seconds(
        ".venv/bin/python scripts/cleanup_stale_proposals.py --pipeline-sweep --apply", al
    ) <= 60


def test_agent_jobs_verify_sql_no_job_type_column(esc):
    """Regression: verify must not reference non-existent job_type column."""
    item = {
        "component": "health:execution_health:agent_jobs_stuck",
        "detail": "246 decision-feeding agent jobs queued >2h",
    }
    cleared, note = esc._verify_remediation(item)
    # Must not be a SQL error about job_type
    assert "job_type" not in note.lower() or "does not exist" not in note.lower()
    assert "verify_error" not in note or "job_type" not in note
    # Either cleared or still backlog — both OK if SQL works
    assert note.startswith("jobs_sla_backlog_") or note.startswith("jobs_sla_backlog_still_")
    assert isinstance(cleared, bool)


def test_paper_stuck_verify_runs(esc):
    item = {"component": "health:execution_health:approved_paper_test_stuck"}
    cleared, note = esc._verify_remediation(item)
    assert "verify_error" not in note
    assert note.startswith("paper_stuck_")


def test_scalp_verify_fail_closed_on_zero_go(esc):
    item = {"component": "health:intelligence_quality:scalp_catalyst_verification_dead"}
    cleared, note = esc._verify_remediation(item)
    # Live data has 0 GO — must not report cleared
    if note == "scalp_go_still_zero":
        assert cleared is False
    else:
        # If GO exists or table missing, still no SQL thrash
        assert "job_type" not in note


def test_time_sensitive_includes_go_signal(esc):
    assert "go_signal_review" in esc._TIME_SENSITIVE_REQUEST_TYPES
    assert "proposal_review" in esc._TIME_SENSITIVE_REQUEST_TYPES
