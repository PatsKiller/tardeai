"""Tests for report_oversight — data packet, fix application, cost gate, graceful degrade."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import report_oversight as ro  # noqa: E402


def _sample_report() -> dict:
    return {
        "meta": {"symbol": "V", "generated_at": "2026-06-24T00:00:00+00:00",
                 "kpis": {"price": 328.48, "recommendation": "ADD", "thesis_status": "Still valid",
                          "unrealized_pnl_pct": 91.5, "portfolio_pct": 8.8}},
        "sections": [
            {"id": "executive_summary", "title": "Executive Summary", "content": "ADD on V.",
             "callouts": [{"label": "Action", "text": "Accumulate on pullbacks."}]},
            {"id": "risk_assessment", "title": "Risk", "content": "Beta 0.76.",
             "metrics": {"beta": 0.76, "realized_vol_pct": 21.0}},
            {"id": "analyst_predictions", "title": "Analyst", "content": "Strong Buy.",
             "metrics": {"consensus_rating": "Strong Buy", "target_mean": 398.83}},
            {"id": "intelligence_view", "title": "Intel", "content": "Mixed panel.",
             "agents": [{"agent": "maria", "recommendation": "BUY", "weight": "Secondary", "accuracy_pct": None}]},
        ],
    }


def test_build_data_packet_extracts_ground_truth():
    packet = ro.build_data_packet(_sample_report())
    assert packet["symbol"] == "V"
    assert packet["price"] == 328.48
    assert packet["recommendation"] == "ADD"
    assert packet["risk_metrics"]["beta"] == 0.76
    assert packet["analyst_metrics"]["consensus_rating"] == "Strong Buy"
    assert packet["agent_panel"][0]["agent"] == "maria"
    assert "note_to_reviewer" in packet


def test_extract_json_tolerates_noise():
    assert ro._extract_json('blah {"verdict":"PUBLISH"} trailing') == {"verdict": "PUBLISH"}
    assert ro._extract_json('{"a":1,}')["a"] == 1  # trailing comma tolerated
    assert ro._extract_json("no json here") == {}


def test_apply_fixes_injects_analyst_note_and_block_warning():
    report = _sample_report()
    oversight = {
        "verdict": "BLOCK",
        "analyst_note": "Senior view: thesis intact but concentration capped.",
        "confidence_check": "Confidence overstated.",
        "fixes": [{"section": "risk_assessment", "action": "clarify", "detail": "label vol"}],
    }
    n = ro.apply_fixes(report, oversight)
    exec_sec = next(s for s in report["sections"] if s["id"] == "executive_summary")
    labels = [c["label"] for c in exec_sec["callouts"]]
    assert any("Senior Analyst Overlay" in l for l in labels)
    assert any("HOLD FOR REVIEW" in l for l in labels)
    risk_sec = next(s for s in report["sections"] if s["id"] == "risk_assessment")
    assert risk_sec["oversight_flags"][0]["action"] == "clarify"
    assert n >= 3


def test_cost_gate_explicit_request():
    run, reason = ro._should_run_claude(_sample_report(), [], requested=True, cadence=None)
    assert run is True and reason == "explicit_request"


def test_cost_gate_explicit_disable():
    run, reason = ro._should_run_claude(_sample_report(), [], requested=False, cadence=None)
    assert run is False and reason == "explicitly_disabled"


def test_cost_gate_env_off_by_default(monkeypatch):
    monkeypatch.delenv("REPORT_CLAUDE_OVERSIGHT", raising=False)
    run, reason = ro._should_run_claude(_sample_report(), [], requested=None, cadence="monthly")
    assert run is False and reason == "env_disabled"


def test_cost_gate_env_on_triggers_on_flag(monkeypatch):
    monkeypatch.setenv("REPORT_CLAUDE_OVERSIGHT", "true")
    flagged = [{"lane": "grok", "available": True, "fabrications": ["x"], "stale_or_contradictory": []}]
    run, reason = ro._should_run_claude(_sample_report(), flagged, requested=None, cadence=None)
    assert run is True and reason == "free_lane_flagged"


def test_cost_gate_env_on_monthly_buy(monkeypatch):
    monkeypatch.setenv("REPORT_CLAUDE_OVERSIGHT", "true")
    run, reason = ro._should_run_claude(_sample_report(), [], requested=None, cadence="monthly")
    assert run is True and reason == "monthly_buy_holding"


def test_oversee_report_degrades_when_lanes_unavailable():
    report = _sample_report()
    with patch.object(ro, "_lane_available", return_value=False), \
         patch.object(ro, "_audit_log", return_value=None):
        out = ro.oversee_report(report, claude_oversight=True)
    stamp = out["meta"]["claude_oversight"]
    # No lanes → never blocks; degrades to a free verdict, report still publishable.
    assert stamp["verdict"] in ("PUBLISH", "PUBLISH_WITH_FIXES")
    assert stamp["fixes_applied"] >= 0


def test_oversee_report_claude_block_applies_overlay():
    report = _sample_report()
    free = [{"lane": "grok", "available": True, "fabrications": [], "stale_or_contradictory": []},
            {"lane": "chatgpt", "available": True, "fabrications": [], "stale_or_contradictory": []}]
    claude = {"verdict": "BLOCK", "available": True, "fixes": [],
              "analyst_note": "Hold for review.", "confidence_check": "Overstated.", "model": "test"}
    with patch.object(ro, "_lane_available", return_value=True), \
         patch.object(ro, "free_lane_critique", side_effect=free), \
         patch.object(ro, "claude_oversight_call", return_value=claude), \
         patch.object(ro, "_audit_log", return_value=None):
        out = ro.oversee_report(report, claude_oversight=True)
    stamp = out["meta"]["claude_oversight"]
    assert stamp["verdict"] == "BLOCK"
    assert stamp["claude_ran"] is True
    exec_sec = next(s for s in out["sections"] if s["id"] == "executive_summary")
    assert any("HOLD FOR REVIEW" in c["label"] for c in exec_sec["callouts"])


def test_claude_model_resolves_from_env(monkeypatch):
    monkeypatch.setenv("REPORT_CLAUDE_MODEL", "claude-test-model")
    assert ro._claude_model() == "claude-test-model"
    monkeypatch.delenv("REPORT_CLAUDE_MODEL", raising=False)
    monkeypatch.setenv("CLAUDE_ESCALATION_MODEL", "claude-fallback")
    assert ro._claude_model() == "claude-fallback"
