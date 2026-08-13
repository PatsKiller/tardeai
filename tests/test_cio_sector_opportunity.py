"""cio_sector_opportunity.py — dry tests for the sector-opportunity synthesis.

Phase 5 increment: Alex's "Sector X is improving…" statement. Pure logic is tested
with no live DB/broker/LLM; the live reader is tested with a fail-soft fake executor.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib import cio_sector_opportunity as so  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Taxonomy / state
# ─────────────────────────────────────────────────────────────────────────────

def test_canonical_sector_aliases():
    assert so.canonical_sector("Communication Services") == "Communications"
    assert so.canonical_sector("Consumer Cyclical") == "Consumer Discretionary"
    assert so.canonical_sector("Consumer Defensive") == "Consumer Staples"
    assert so.canonical_sector("Basic Materials") == "Materials"
    assert so.canonical_sector("Financial Services") == "Financials"
    assert so.canonical_sector("technology") == "Technology"
    assert so.canonical_sector("") == ""
    # unknown passes through title-cased (never silently collapsed)
    assert so.canonical_sector("Space Stuff") == "Space Stuff"


def test_classify_state_replicates_momentum():
    assert so.classify_state(5, 1) == "LEADING"
    assert so.classify_state(5, -1) == "WEAKENING"
    assert so.classify_state(-5, 1) == "IMPROVING"
    assert so.classify_state(-5, -1) == "LAGGING"
    assert so.classify_state(None, 1) is None
    assert so.classify_state(1, None) is None


def test_opportunity_states():
    assert so.is_opportunity_state("LEADING")
    assert so.is_opportunity_state("IMPROVING")
    assert not so.is_opportunity_state("LAGGING")
    assert not so.is_opportunity_state("WEAKENING")
    assert not so.is_opportunity_state(None)


def test_thematic_sleeves_are_not_sector_targets():
    # rotation_sector_targets.json themes are sleeves, not GICS sectors; the
    # target-map guard must skip them (only canonical sectors contribute a target).
    for theme in ("Magnificent 7", "AI mega-cap", "Semiconductors",
                  "AI datacenter & power", "Defense / Aerospace",
                  "Nuclear / power gen", "Cybersecurity", "China / EM"):
        assert so.canonical_sector(theme) not in so.CANONICAL_SECTORS, theme
    # but Energy IS a canonical sector and does contribute
    assert so.canonical_sector("Energy") in so.CANONICAL_SECTORS


# ─────────────────────────────────────────────────────────────────────────────
# Normalization
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_sector_row_momentum():
    row = so.normalize_sector_row({
        "etf": "XLK", "sector": "Technology", "state": "LEADING",
        "rs20": 4.2, "slope": 1.1, "rs5": 2.0, "book_pct": "22.5", "book_dollars": "50000",
    })
    assert row["sector"] == "Technology"
    assert row["state"] == "LEADING"
    assert row["rs20"] == 4.2
    assert row["book_pct"] == 22.5
    assert row["book_dollars"] == 50000.0


def test_normalize_sector_row_rotation_ladder():
    row = so.normalize_sector_row({
        "etf": "XLE", "name": "Energy", "rs_score": 82,
    })
    assert row["sector"] == "Energy"
    assert row["rs_score"] == 82.0
    assert row["state"] == "LEADING"  # rs_score >= 70


def test_normalize_sector_row_requires_sector():
    assert so.normalize_sector_row({"etf": "XLK", "state": "LEADING"}) is None


def test_normalize_candidate():
    c = so.normalize_candidate({
        "symbol": "nvda", "sector": "Technology", "status": "researched",
        "rsi": 62, "price": "100", "hermes_research_score": 55,
    })
    assert c["symbol"] == "NVDA"
    assert c["sector"] == "Technology"
    assert c["price"] == 100.0
    assert c["research_score"] == 55.0
    assert so.normalize_candidate({"symbol": ""}) is None


# ─────────────────────────────────────────────────────────────────────────────
# Readiness classification
# ─────────────────────────────────────────────────────────────────────────────

def test_readiness_explicit_override_wins():
    assert so.classify_candidate_readiness(
        {"symbol": "A", "readiness": "WATCH_READY", "rsi": 90}) == "WATCH_READY"


def test_readiness_too_extended_rsi():
    assert so.classify_candidate_readiness(
        {"symbol": "A", "status": "researched", "rsi": 71}) == "TOO_EXTENDED"


def test_readiness_too_extended_vwap():
    assert so.classify_candidate_readiness(
        {"symbol": "A", "status": "researched", "price": 103, "vwap": 100}) == "TOO_EXTENDED"


def test_readiness_watch_ready_researched():
    assert so.classify_candidate_readiness(
        {"symbol": "A", "status": "researched", "rsi": 55}) == "WATCH_READY"


def test_readiness_watch_ready_research_score():
    assert so.classify_candidate_readiness(
        {"symbol": "A", "status": "active", "hermes_research_score": 40}) == "WATCH_READY"


def test_readiness_needs_research_default():
    assert so.classify_candidate_readiness(
        {"symbol": "A", "status": "active"}) == "NEEDS_RESEARCH"


def test_readiness_unknown():
    assert so.classify_candidate_readiness({}) == "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────────
# Deployment recommendation
# ─────────────────────────────────────────────────────────────────────────────

def test_recommendation_over_target_no_deploy():
    assert so.deployment_recommendation("LEADING", 25.0, 18.0, 10000, 2) == "NO_DEPLOYMENT"


def test_recommendation_no_capital_no_deploy():
    assert so.deployment_recommendation("IMPROVING", 5.0, 18.0, 0, 2) == "NO_DEPLOYMENT"


def test_recommendation_ready_and_capital_staged():
    assert so.deployment_recommendation("LEADING", 5.0, 18.0, 10000, 1) == "STAGED_DEPLOYMENT"


def test_recommendation_no_ready_research_first():
    assert so.deployment_recommendation("IMPROVING", 5.0, 18.0, 10000, 0) == "RESEARCH_FIRST"


def test_recommendation_non_opportunity_research_first():
    assert so.deployment_recommendation("LAGGING", 5.0, 18.0, 10000, 3) == "RESEARCH_FIRST"
    assert so.deployment_recommendation(None, 5.0, 18.0, 10000, 3) == "RESEARCH_FIRST"


# ─────────────────────────────────────────────────────────────────────────────
# Synthesis envelope + statement
# ─────────────────────────────────────────────────────────────────────────────

def test_build_sector_opportunity_acceptance_shape():
    opp = so.build_sector_opportunity(
        {"sector": "Energy", "state": "IMPROVING", "rs20": -1.0, "slope": 0.5,
         "book_pct": 4.0, "book_dollars": 8000},
        target_pct=5.0,
        capital_usd=20000,
        candidates=[
            {"symbol": "XOM", "sector": "Energy", "status": "researched", "rsi": 55},
            {"symbol": "CVX", "sector": "Energy", "status": "active"},
            {"symbol": "OXY", "sector": "Energy", "status": "researched", "rsi": 78},
        ],
    )
    assert opp["sector"] == "Energy"
    assert opp["state"] == "IMPROVING"
    assert opp["opportunity"] is True
    assert opp["current_exposure_pct"] == 4.0
    assert opp["target_posture_pct"] == 5.0
    assert opp["potential_capital_usd"] == 20000.0
    assert opp["candidate_counts"] == {"watch_ready": 1, "needs_research": 1, "too_extended": 1}
    # XOM is ready and capital exists and not over target → staged deployment
    assert opp["recommendation"] == "STAGED_DEPLOYMENT"
    assert opp["opportunity_key"]
    # statement follows the acceptance shape
    assert "Sector Energy is improving" in opp["statement"]
    assert "I recommend staged deployment" in opp["statement"]
    assert "XOM is Watch READY" in opp["statement"]
    assert "CVX is needs research" in opp["statement"]
    assert "OXY is too extended" in opp["statement"]


def test_build_sector_opportunity_over_target_no_deploy():
    opp = so.build_sector_opportunity(
        {"sector": "Technology", "state": "LEADING", "book_pct": 25.0},
        target_pct=18.0,
        capital_usd=50000,
        candidates=[{"symbol": "NVDA", "sector": "Technology", "status": "researched"}],
    )
    assert opp["recommendation"] == "NO_DEPLOYMENT"
    assert "no deployment" in opp["statement"]


def test_opportunity_key_deterministic():
    args = dict(
        target_pct=5.0, capital_usd=20000,
        candidates=[{"symbol": "XOM", "sector": "Energy", "status": "researched"}],
    )
    a = so.build_sector_opportunity(
        {"sector": "Energy", "state": "IMPROVING", "book_pct": 4.0}, **args)
    b = so.build_sector_opportunity(
        {"sector": "Energy", "state": "IMPROVING", "book_pct": 4.0}, **args)
    assert a["opportunity_key"] == b["opportunity_key"]


def test_synthesize_orders_and_filters():
    rows = [
        {"sector": "Energy", "state": "IMPROVING", "rs20": -0.5, "slope": 0.3},
        {"sector": "Technology", "state": "LEADING", "rs20": 4.0, "slope": 1.0},
        {"sector": "Materials", "state": "LAGGING", "rs20": -3.0, "slope": -1.0},
    ]
    result = so.synthesize_sector_opportunities(rows, capital_usd=10000)
    assert result["count"] == 2  # LAGGING filtered out
    assert result["opportunity_count"] == 2
    # LEADING (Technology) orders before IMPROVING (Energy)
    assert result["opportunities"][0]["sector"] == "Technology"
    assert result["opportunities"][1]["sector"] == "Energy"
    assert result["digest"]


def test_synthesize_include_non_opportunity():
    rows = [
        {"sector": "Materials", "state": "LAGGING", "rs20": -3.0, "slope": -1.0},
    ]
    result = so.synthesize_sector_opportunities(rows, include_non_opportunity=True)
    assert result["count"] == 1
    assert result["opportunity_count"] == 0


def test_sector_targets_lookup_alias_tolerant():
    result = so.synthesize_sector_opportunities(
        [{"sector": "Energy", "state": "IMPROVING", "rs20": -0.5, "slope": 0.3,
          "book_pct": 8.0}],
        sector_targets={"Energy": 5.0},
        capital_usd=10000,
    )
    assert result["opportunities"][0]["target_posture_pct"] == 5.0


def test_render_statement_non_opportunity_verb():
    opp = so.build_sector_opportunity(
        {"sector": "Materials", "state": "LAGGING", "book_pct": 3.0},
    )
    assert opp["opportunity"] is False
    assert "is lagging" in opp["statement"]


# ─────────────────────────────────────────────────────────────────────────────
# Live reader (fail-soft fake executor)
# ─────────────────────────────────────────────────────────────────────────────

def test_fetch_sector_opportunity_inputs_shape():
    def fake_exec(sql, params=None, fetch=None):
        sql_u = sql.upper()
        if "SECTOR_MOMENTUM_STATE" in sql_u:
            return [{"etf": "XLE", "sector": "Energy", "state": "IMPROVING",
                     "rs5": 1.0, "rs20": -0.5, "rs60": None, "slope": 0.3,
                     "book_pct": 4.0, "book_dollars": 8000.0}]
        if "WATCHLIST_ITEMS" in sql_u:
            return [{"symbol": "XOM", "sector": "Energy", "status": "researched",
                     "rsi": 55, "price": 100.0, "hermes_research_score": 40,
                     "confluence_score": None}]
        return None

    inputs = so.fetch_sector_opportunity_inputs(fake_exec, capital_usd=12345.0)
    assert len(inputs["sector_rows"]) == 1
    assert inputs["sector_rows"][0]["sector"] == "Energy"
    assert len(inputs["candidates"]) == 1
    assert inputs["capital_usd"] == 12345.0


def test_fetch_sector_opportunity_inputs_fails_soft():
    def raising(sql, params=None, fetch=None):
        raise RuntimeError("db down")

    inputs = so.fetch_sector_opportunity_inputs(raising)
    assert inputs["sector_rows"] == []
    assert inputs["candidates"] == []


def test_build_synthesis_from_executor():
    def fake_exec(sql, params=None, fetch=None):
        sql_u = sql.upper()
        if "SECTOR_MOMENTUM_STATE" in sql_u:
            return [{"etf": "XLE", "sector": "Energy", "state": "IMPROVING",
                     "rs5": 1.0, "rs20": -0.5, "rs60": None, "slope": 0.3,
                     "book_pct": 4.0, "book_dollars": 8000.0}]
        if "WATCHLIST_ITEMS" in sql_u:
            return [{"symbol": "XOM", "sector": "Energy", "status": "researched",
                     "rsi": 55, "price": 100.0, "hermes_research_score": 40,
                     "confluence_score": None}]
        return None

    result = so.build_synthesis_from_executor(fake_exec, capital_usd=20000.0)
    assert result["opportunity_count"] == 1
    assert result["opportunities"][0]["sector"] == "Energy"
