"""Tests for report_narrative — v3 analyst voice and synthesis."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from report_narrative import (  # noqa: E402
    action_recommendation_line,
    compose_executive,
    polish_sections,
    synthesize_agent_collective,
    thesis_rationale,
)


def test_compose_executive_has_callouts():
    block = compose_executive(
        company="Leidos Holdings",
        sym="LDOS",
        sector="Industrials",
        price=106.0,
        day_pct=-1.2,
        rec="ADD",
        conf_label="Medium",
        thesis="At risk",
        thesis_why="Thesis under pressure because material personal drawdown.",
        action_line="Add on pullbacks to $95.00–$106.00 only.",
        synthesis={"synthesis_narrative": "Defense contractor with stable cash flows and contract backlog."},
        enrich={"pe": 18, "rsi": 42},
        gl_pct=-40.9,
        continuity=None,
    )
    assert block.get("callouts")
    labels = [c["label"] for c in block["callouts"]]
    assert "Action Recommendation" in labels
    assert "Thesis Status" in labels
    assert "ADD" in block["content"] or "Defense" in block["content"]


def test_synthesize_agent_collective_no_verbatim_dump():
    agents = [
        {"agent": "risk_agent", "recommendation": "HOLD", "summary": "x" * 50},
        {"agent": "steph", "recommendation": "ADD", "summary": "y" * 50},
        {"agent": "macro", "recommendation": "ADD", "summary": "z" * 50},
    ]
    intel = synthesize_agent_collective(
        agents,
        {"recommendation": "ADD"},
        {"final_decision": "block", "final_score": 4.2, "final_confidence": 0.55},
        None,
    )
    assert "Across 3 agent notes" in intel["narrative"]
    assert len(intel["agents"]) == 3
    assert all("summary" not in ag for ag in intel["agents"])
    assert intel["agents"][0].get("weight") in ("Primary", "Secondary", "Low")


def test_action_recommendation_line_add_with_stop():
    line = action_recommendation_line(
        "ADD",
        price=106.0,
        proposal={"proposed_stop": 95.0},
        pro=None,
        thesis="Still valid",
    )
    assert "pullbacks" in line.lower()
    assert "$95" in line


def test_thesis_rationale_broken():
    assert "invalidated" in thesis_rationale("Broken", synthesis=None, proposal=None, enrich={}, gl_pct=None, ensemble=None).lower()


def test_polish_sections_dedupes_legacy_agent_blocks():
    sections = [
        {"id": "intelligence_view", "content": "Synthesized view.", "agents": []},
        {"id": "agent_performance_note", "content": "Prior note.", "bullets": ["x"]},
        {"id": "ensemble_validation", "content": "Ensemble block.", "bullets": []},
        {"id": "technical_analysis", "content": "RSI neutral.", "bullets": []},
    ]
    out = polish_sections(sections)
    ids = [s["id"] for s in out]
    assert "intelligence_view" in ids
    assert "agent_performance_note" not in ids
    assert "ensemble_validation" not in ids