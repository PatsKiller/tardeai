#!/usr/bin/env python3
"""Health-agent monitor + auto-fix for CIO-rated watchlist news/catalyst mismatches."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import health_agent as ha  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_collector_registered():
    assert ha.collect_watchlist_news_guard_health in ha.COLLECTORS


def test_collect_watchlist_news_guard_disabled(monkeypatch):
    monkeypatch.setattr(ha, "_POLICY", {"watchlist_news_guard": {"enabled": False}})
    assert ha.collect_watchlist_news_guard_health() == []


def test_mismatch_finding_emitted():
    audit = {
        "scanned": 80,
        "mismatch_count": 2,
        "mismatches": [{"symbol": "MRLN", "headline": "Pasqal IPO", "reason": "foreign_company:pasqal"}],
    }
    mock_conn = MagicMock()
    with patch.object(ha, "_POLICY", {"watchlist_news_guard": {"enabled": True, "mismatch_warn": 1}}):
        with patch("db_adapter.get_connection", return_value=mock_conn):
            with patch("news_symbol_guard.count_mismatched_watchlist", return_value=audit):
                findings = ha.collect_watchlist_news_guard_health()
    assert len(findings) == 1
    assert findings[0]["type"] == "news_symbol_mismatch"
    assert findings[0]["count"] == 2
    assert findings[0]["severity"] == "warning"


def test_clean_audit_no_finding():
    mock_conn = MagicMock()
    with patch.object(ha, "_POLICY", {"watchlist_news_guard": {"enabled": True}}):
        with patch("db_adapter.get_connection", return_value=mock_conn):
            with patch("news_symbol_guard.count_mismatched_watchlist", return_value={"mismatch_count": 0, "scanned": 50}):
                assert ha.collect_watchlist_news_guard_health() == []


def test_policy_wiring():
    pol = json.loads((ROOT / "config" / "health_agent_policy.json").read_text())
    ft = pol["auto_remediate"]["finding_types"]
    rm = pol["remediation_map"]
    assert "news_symbol_mismatch" in ft
    assert "news_symbol_mismatch" in rm
    assert "remediate_watchlist_news_guard.py" in rm["news_symbol_mismatch"]
    assert pol.get("watchlist_news_guard", {}).get("enabled") is True


def test_remediation_allowlisted():
    # Semantic safety (the old string-assertion checked an inline guard since
    # replaced by the general allowlist): the (destructive) news-guard purge script
    # must be in the canonical allowlist, and auto-remediation must gate on it.
    allowlist = (ROOT / "config" / "claude_escalation_allowlist.yaml").read_text()
    assert "remediate_watchlist_news_guard.py" in allowlist
    src = (ROOT / "scripts" / "health_agent.py").read_text()
    assert "if not any(s in cmd for s in _SAFE_REMEDIATION_SCRIPTS)" in src


def test_remediate_script_exists():
    path = ROOT / "scripts" / "remediate_watchlist_news_guard.py"
    assert path.exists()
    assert "purge_mismatched" in path.read_text()