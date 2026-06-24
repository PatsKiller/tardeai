"""Tests for report_render — HTML/CSS render model, formatting, md-strip, integrity enforcement."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import report_render as rr  # noqa: E402
import report_oversight as ro  # noqa: E402


def _report() -> dict:
    return {
        "meta": {"symbol": "V", "company": "Visa Inc", "sector": "Financial", "version": "4.0",
                 "generated_at": "2026-06-24T09:00:00+00:00", "document_class": "summary_prospectus",
                 "kpis": {"recommendation": "ADD", "price": 328.48, "day_change_pct": 0.15,
                          "confidence_label": "Medium", "thesis_status": "Still valid",
                          "unrealized_pnl_pct": 91.87, "portfolio_pct": 8.79},
                 "claude_oversight": {"verdict": "PUBLISH_WITH_FIXES", "fixes_applied": 2, "model": "test"}},
        "sections": [
            {"id": "executive_summary", "title": "Executive Summary", "content": "Our stance is **ADD**.",
             "callouts": [{"label": "Senior Analyst Overlay", "text": "Hold quality."},
                          {"label": "Senior Analyst Overlay", "text": "dup"}],
             "metrics": {"recommendation": "ADD", "confidence_label": "Medium"}},
            {"id": "technical_analysis", "title": "Technical", "content": "Uptrend.",
             "figures": [{"chart_path": "/nonexistent/x.png", "caption": "cap"}]},
            {"id": "intelligence_view", "title": "Intel", "content": "panel",
             "agents": [{"agent": "maria", "recommendation": "BUY", "relevance": "Aligned"},
                        {"agent": "maria", "recommendation": "BUY", "relevance": "Aligned"},
                        {"agent": "risk agent", "recommendation": "AVOID", "relevance": "Divergent"}]},
            {"id": "peer_comparison", "title": "Peer", "content": "premium to the 8-peer median of 21.1×.",
             "bullets": ["MA: +0.5% · PE 28.35 · 1M -1%", "PYPL: +1% · PE 7.95 · 1M +2%",
                         "FIS: +0.1% · PE 7.39 · 1M -3%"]},
        ],
        "sources": [{"id": "x", "label": "Enrichment"}],
    }


def test_fmt_numbers():
    assert rr._fmt("price", 328.48) == "$328.48"
    assert rr._fmt("day_change_pct", 0.15) == "+0.15%"
    assert rr._fmt("confidence", 0.56) == "56%"
    assert rr._fmt("analysts", 36) == "36"
    assert rr._fmt("pe", 28.87) == "28.9×"
    assert rr._fmt("anything", None) == "—"


def test_md_strip():
    assert rr._md("Our stance is **ADD**.") == "Our stance is ADD."
    assert rr._md("a *b* c") == "a b c"
    assert "**" not in rr._md("**x** and **y**")


def test_prepare_dedupes_callouts_and_strips_md():
    ctx = rr._prepare(_report())
    exec_sec = next(s for s in ctx["sections"] if s["id"] == "executive_summary")
    assert exec_sec["content"] == "Our stance is ADD."
    # duplicate overlay label collapsed to one
    assert len([c for c in exec_sec["callouts"] if c["label"] == "Senior Analyst Overlay"]) == 1


def test_prepare_cover_tiles():
    ctx = rr._prepare(_report())
    labels = {t["label"]: t["value"] for t in ctx["cover_tiles"]}
    assert labels["REC"] == "ADD"
    assert labels["PRICE"] == "$328.48"
    assert labels["UNREALIZED"] == "+91.87%"


def test_render_html_inlines_and_paginates():
    html = rr.render_html(_report())
    assert "<html" in html and "Visa Inc" in html
    assert "Trade AI v12" in html
    # bad chart path is skipped (no data uri), html still renders
    assert "Executive Summary" in html


def test_enforce_integrity_dedupes_agents_and_reconciles_median():
    rep = _report()
    applied = ro.enforce_integrity(rep)
    intel = next(s for s in rep["sections"] if s["id"] == "intelligence_view")
    keys = [(a["agent"], a["recommendation"]) for a in intel["agents"]]
    assert len(keys) == len(set(keys))  # no duplicate (agent, rec) rows
    assert any("deduped agent panel" in a for a in applied)
    # peer median recomputed from listed PEs (28.35, 7.95, 7.39 → median 7.95)
    peer = next(s for s in rep["sections"] if s["id"] == "peer_comparison")
    assert "median of 8.0×" in peer["content"] or "median of 7.9×" in peer["content"] or "21.1" not in peer["content"]


def test_unresolved_blocks_when_dupes_remain():
    rep = _report()
    # do NOT enforce → duplicates present → re-validation flags it
    issues = ro._unresolved_after_apply(rep)
    assert any("duplicate agent" in i for i in issues)
    ro.enforce_integrity(rep)
    assert ro._unresolved_after_apply(rep) == []
