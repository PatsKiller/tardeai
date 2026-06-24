"""Tests for analyst_report_builder — schema-safe composition."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from analyst_report_builder import (  # noqa: E402
    EVENT_FILTERS,
    SECTION_IDS,
    _ensemble,
    _synthesis,
    _synthesis_narrative,
    _watchlist_rating,
    _watchlist_row,
    build_daily_digest,
    build_report,
    build_symbol_report,
    list_report_types,
)


def test_list_report_types_includes_core_templates():
    keys = {t["key"] for t in list_report_types()}
    assert "symbol_watchlist" in keys
    assert "daily_digest" in keys
    assert "sector_theme" in keys
    assert "intelligence_deep" in keys
    assert "event_driven" in keys
    assert "all" in EVENT_FILTERS


def test_synthesis_narrative_prefers_narrative_over_raw():
    assert _synthesis_narrative({"synthesis_narrative": "Narrative text", "raw_response": "Raw"}) == "Narrative text"
    assert _synthesis_narrative({"raw_response": "Raw only"}) == "Raw only"
    assert _synthesis_narrative(None) == ""


def test_watchlist_rating_priority():
    assert _watchlist_rating(None, {"recommendation": "BUY"}) == "BUY"
    assert _watchlist_rating({"holdings_llm_action": "TRIM"}, None) == "TRIM"
    assert _watchlist_rating(None, None) == "Review"


def test_watchlist_row_query_uses_live_columns():
    """SQL must not reference removed columns (rating, notes, sector on watchlist_items)."""
    with patch("analyst_report_builder._db_query", return_value=None) as mock_q:
        _watchlist_row("RKLB")
    sql = mock_q.call_args[0][0]
    assert "rating" not in sql
    assert "notes" not in sql
    assert "holdings_llm_action" in sql
    assert "symbol_profiles" in sql


def test_synthesis_query_uses_narrative_columns():
    with patch("analyst_report_builder._db_query", return_value=None) as mock_q:
        _synthesis("RKLB")
    sql = mock_q.call_args[0][0]
    assert "synthesis_narrative" in sql
    assert "synthesis_text" not in sql


def test_ensemble_query_uses_target_columns():
    with patch("analyst_report_builder._db_query", return_value=None) as mock_q:
        _ensemble("RKLB")
    sql = mock_q.call_args[0][0]
    assert "final_score" in sql
    assert "final_decision" in sql
    assert "ensemble_score" not in sql


def test_build_symbol_report_structure():
    report = build_symbol_report("RKLB", sections=["executive_summary", "recommendation"])
    assert report["meta"]["symbol"] == "RKLB"
    ids = {s["id"] for s in report["sections"]}
    assert "executive_summary" in ids
    assert "recommendation" in ids
    assert "sources" in report


def test_build_symbol_report_v3_defaults():
    report = build_symbol_report("RKLB", report_type="symbol_holding")
    assert report["meta"]["version"] == "3.0"
    ids = [s["id"] for s in report["sections"]]
    assert ids[0] == "header_context"
    assert "personal_performance" in ids
    assert "action_plan" in ids
    assert "intelligence_view" in ids
    assert "agent_performance_note" not in ids


def test_build_daily_digest_has_sections():
    digest = build_daily_digest(days=1)
    assert digest["meta"]["report_type"] == "daily_digest"
    assert len(digest["sections"]) >= 4


def test_build_aggregate_holding_report_without_symbol():
    report = build_report(report_type="symbol_holding", symbol=None)
    assert report["meta"]["scope"] == "all"
    assert len(report.get("items") or []) >= 1
    assert len(report.get("visuals") or []) >= 1


def test_build_aggregate_watchlist_without_symbol():
    report = build_report(report_type="symbol_watchlist", symbol=None)
    assert report["meta"]["scope"] == "all"


def test_build_all_sectors_without_filter():
    report = build_report(report_type="sector_theme", sector="")
    assert report["meta"]["scope"] == "all"
    assert len(report.get("visuals") or []) >= 1


def test_daily_digest_has_action_items():
    digest = build_daily_digest(days=1)
    assert "action_items" in digest
    assert isinstance(digest["action_items"], list)


def test_weekly_review_has_action_items_and_no_action_wall():
    from analyst_report_builder import build_weekly_review
    weekly = build_weekly_review()
    assert len(weekly.get("action_items") or []) >= 1
    agent_sec = next((s for s in weekly["sections"] if s["id"] == "agent_synthesis"), None)
    assert agent_sec is not None
    assert not agent_sec.get("bullets")
    assert "Action Queue" in (agent_sec.get("content") or "")


def test_section_ids_complete():
    assert "intelligence_view" in SECTION_IDS
    assert "ensemble_validation" in SECTION_IDS  # legacy alias
    assert "health_context" in SECTION_IDS
    assert "header_context" in SECTION_IDS
    assert "action_plan" in SECTION_IDS
    assert "personal_performance" in SECTION_IDS


def test_build_event_driven_report():
    report = build_report(report_type="event_driven", hours=48, event_filter="all")
    assert report["meta"]["report_type"] == "event_driven"
    assert "events" in report
    assert len(report["sections"]) >= 3


def test_pdf_export_reportlab():
    from report_export import export_report
    report = build_symbol_report("RKLB", sections=["executive_summary"])
    result = export_report(report, "pdf", output_stem="RKLB_pdf_test")
    assert result.get("ok"), result.get("error")
    assert result.get("format") == "pdf"
    assert Path(result["path"]).exists()


def test_sector_theme_report_has_charts():
    report = build_report(report_type="sector_theme", sector="Healthcare")
    charts = [v for v in report.get("visuals", []) if v.get("chart_path")]
    assert len(charts) >= 2


def test_intelligence_deep_report_has_charts():
    report = build_report(report_type="intelligence_deep", topic="defense")
    charts = [v for v in report.get("visuals", []) if v.get("chart_path")]
    assert len(charts) >= 2