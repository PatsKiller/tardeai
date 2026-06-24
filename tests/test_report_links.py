"""Tests for report link eligibility and verified URL map."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from reporting_engine import (  # noqa: E402
    _holding_symbols_set,
    eligible_holding_symbols,
    recommendation_actionable,
    report_links_map,
    validate_report_coverage,
    verified_export_urls,
    watchlist_manually_added,
    watchlist_report_eligible,
)


def test_recommendation_actionable_add_and_pullback():
    assert recommendation_actionable("ADD")
    assert recommendation_actionable("ADD_ON_PULLBACK")
    assert recommendation_actionable("WAIT FOR PULLBACK")
    assert recommendation_actionable("STRONG BUY")
    assert not recommendation_actionable("EXIT")
    assert not recommendation_actionable("REBALANCE_TRIM")


def test_watchlist_report_eligible_manual_and_buy_side():
    assert watchlist_manually_added(source="operator")
    assert watchlist_manually_added(source="personal_watchlist")
    assert watchlist_manually_added(source="ai_discovered", origin_system="operator")
    assert watchlist_report_eligible(source="operator")
    assert watchlist_report_eligible(source="personal_watchlist")
    assert watchlist_report_eligible(origin_system="operator")
    assert watchlist_report_eligible(latest_recommendation="STRONG_BUY")
    assert watchlist_report_eligible(synthesis_rec="ADD_ON_PULLBACK")
    assert watchlist_report_eligible(source="ai_discovered", latest_recommendation="WAIT FOR PULLBACK")
    assert not watchlist_report_eligible(source="ai_discovered", latest_recommendation="HOLD")
    assert not watchlist_manually_added(source="paper_proposal", origin_system="trade_ai_screener")


def test_eligible_holdings_covers_portfolio():
    rows = eligible_holding_symbols()
    syms = {r["symbol"] for r in rows}
    book = _holding_symbols_set()
    # Every held symbol above min MV should be eligible
    assert syms.issubset(book)
    assert len(syms) == len(book)


def test_report_links_map_returns_verified_files_only():
    links = report_links_map(limit=50).get("links") or {}
    for sym, entry in links.items():
        assert entry.get("docx") or entry.get("pdf")
        if entry.get("docx"):
            p = PROJECT_ROOT / str(entry["docx"]).lstrip("/")
            assert p.exists(), f"missing docx for {sym}"


def test_verified_export_urls_none_when_missing():
    assert verified_export_urls("ZZZZNOTAREAL") is None


def test_validate_report_coverage_shape():
    cov = validate_report_coverage()
    assert "holdings_eligible" in cov
    assert "holdings_missing" in cov
    assert "watchlist_eligible" in cov
    assert cov["holdings_eligible"] >= cov["holdings_with_links"]


def test_watchlist_eligible_prioritizes_operator():
    from reporting_engine import eligible_watchlist_symbols
    rows = eligible_watchlist_symbols(limit=50)
    if not rows:
        return
    manual = [r for r in rows if r.get("operator_added")]
    if manual:
        assert rows[0].get("operator_added") is True