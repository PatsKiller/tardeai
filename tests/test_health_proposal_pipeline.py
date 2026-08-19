#!/usr/bin/env python3
"""Health-agent coverage for dual-lane proposal pipeline stuck states (P0–P3 parity)."""
import json
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
if "dotenv" not in sys.modules:
    _d = types.ModuleType("dotenv")
    _d.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = _d

import health_agent as ha  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _fake_db(responses: dict):
    def fake(sql, params=None, fetch="one"):
        for key, val in responses.items():
            if key in sql:
                return val
        return {"c": 0, "terminal": 0, "active": 0}
    return fake


def _run_collector(responses: dict | None = None, log_lines: list[str] | None = None):
    old_db, old_log = ha._db, ha.LOG_DIR
    tmp = Path(tempfile.mkdtemp())
    try:
        ha._db = _fake_db(responses or {})
        ha.LOG_DIR = tmp
        if log_lines is not None:
            (tmp / "auto_enrichment.log").write_text("\n".join(log_lines))
        return ha.collect_proposal_pipeline_health()
    finally:
        ha._db, ha.LOG_DIR = old_db, old_log


def test_collector_registered():
    assert ha.collect_proposal_pipeline_health in ha.COLLECTORS


def test_clean_pipeline_no_findings():
    assert _run_collector() == []


def test_enrichment_import_failure_detected():
    findings = _run_collector(
        {"enrichment_log": {"c": 5}, "enrichment_last_error": {"c": 0}},
        log_lines=["cannot import name 'fetch_proposals'"],
    )
    f = [x for x in findings if x["type"] == "enrichment_pipeline_failure"]
    assert len(f) == 1
    assert f[0]["severity"] in ("warning", "critical")


def test_approved_paper_test_stuck_detected():
    findings = _run_collector({"APPROVED_FOR_PAPER_TEST": {"c": 2}})
    f = [x for x in findings if x["type"] == "approved_paper_test_stuck"]
    assert len(f) == 1
    assert f[0]["count"] == 2


def test_in_progress_stale_detected():
    findings = _run_collector({"enrichment_status = 'IN_PROGRESS'": {"terminal": 2, "active": 4}})
    f = [x for x in findings if x["type"] == "enrichment_status_in_progress_stale"]
    assert len(f) == 1
    assert f[0]["count"] == 6


def test_collector_never_raises_without_db():
    old = ha._db
    try:
        ha._db = lambda *a, **k: None
        out = ha.collect_proposal_pipeline_health()
        assert isinstance(out, list)
    finally:
        ha._db = old


def test_policy_wiring():
    pol = json.loads((ROOT / "config" / "health_agent_policy.json").read_text())
    ft = pol["auto_remediate"]["finding_types"]
    rm = pol["remediation_map"]
    for t in (
        "enrichment_pipeline_failure",
        "enrichment_failures_high",
        "approved_paper_test_stuck",
        "enrichment_status_in_progress_stale",
    ):
        assert t in ft, t
        assert t in rm, t
    assert "auto_enrichment_runner.py" in rm["enrichment_pipeline_failure"]
    assert "cleanup_stale_proposals.py" in rm["approved_paper_test_stuck"]
    assert "--pipeline-sweep" in rm["enrichment_status_in_progress_stale"]
    assert pol.get("proposal_pipeline", {}).get("enabled") is True


def test_remediation_allowlisted():
    # Semantic safety (the old string-assertions checked inline guards since replaced
    # by the general allowlist): both proposal remediators must be allowlisted and
    # auto-remediation must gate on the allowlist.
    allowlist = (ROOT / "config" / "claude_escalation_allowlist.yaml").read_text()
    assert "auto_enrichment_runner.py" in allowlist
    assert "cleanup_stale_proposals.py" in allowlist
    src = (ROOT / "scripts" / "health_agent.py").read_text()
    assert "if not any(s in cmd for s in _SAFE_REMEDIATION_SCRIPTS)" in src
    cleanup = (ROOT / "scripts" / "cleanup_stale_proposals.py").read_text()
    assert "def run_pipeline_sweep" in cleanup
    assert "--pipeline-sweep" in cleanup