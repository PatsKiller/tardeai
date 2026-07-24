from datetime import date

from scripts.defense_data_quality import (
    allocation_decision,
    canonical_industry_sector,
    directive_review_status,
    snapshot_hash,
    staleness,
    stock_quality_assessment,
)


def test_snapshot_hash_is_order_independent():
    assert snapshot_hash({"b": 2, "a": 1}) == snapshot_hash({"a": 1, "b": 2})


def test_staleness_quarantines_old_rows():
    assert staleness("2026-07-13", "2026-07-24", 4)["stale"] is True
    assert staleness("2026-07-23", "2026-07-24", 4)["stale"] is False


def test_versioned_industry_mapping_never_uses_database_mode():
    exact = canonical_industry_sector("Aerospace & Defense")
    assert exact["sector"] == "Industrials"
    assert exact["mapping_quality"] == "exact"
    rule = canonical_industry_sector("Copper Miners - Emerging")
    assert rule["sector"] == "Materials"
    unknown = canonical_industry_sector("Unclassified Experimental Group")
    assert unknown["sector"] is None
    assert unknown["mapping_quality"] == "unmapped"


def test_allocation_capacity_respects_book_and_risk():
    cfg = {
        "neutral_sector_weight_pct": 9.1,
        "allocation_policy": {
            "default_benchmark": "equal_sector",
            "benchmarks": {"equal_sector": {"Energy": 9.1}},
            "account_mandates": {"ira": "retirement_income"},
            "mandates": {"retirement_income": {"sector_tilts_pct": {"Energy": -1.0}}},
            "target_annualized_vol_pct": 22,
            "vol_scalar_floor": 0.45,
            "vol_scalar_cap": 1.2,
            "correlation_soft_limit": 0.85,
            "correlation_penalty": 0.75,
            "max_active_tilt_pct": 4,
            "sector_cap_pct": 25,
            "min_capacity_pct": 1,
        },
    }
    d = allocation_decision(cfg, sector="Energy", current_weight_pct=3.6,
                            risk_context={"quality": "ok", "annualized_vol_pct": 30,
                                          "correlation": 0.75, "sessions": 60},
                            account="ira")
    assert d["eligible"] is True
    assert 0 < d["capacity_pct"] < 21.4
    full = allocation_decision(cfg, sector="Energy", current_weight_pct=24.5,
                               risk_context={"quality": "ok", "annualized_vol_pct": 30,
                                             "correlation": 0.75, "sessions": 60},
                               account="ira")
    assert full["eligible"] is False


def test_stock_quality_requires_coverage_and_quality():
    cfg = {"stock_quality": {"min_coverage": 0.6, "min_score": 60,
                              "min_roic_pct": 8, "max_debt_equity": 2,
                              "hard_fail_debt_equity": 4, "max_short_float_pct": 12,
                              "hard_fail_short_float_pct": 25, "max_beta": 1.7,
                              "max_above_sma50_pct": 12}}
    good = {
        "forward_pe": 18, "pfcf": 20, "eps_next_y": 12, "eps_qoq": 8,
        "sales_qoq": 6, "roic_pct": 16, "profit_margin_pct": 15,
        "total_debt_equity": 0.8, "short_float_pct": 3, "beta": 1.1,
        "sma50_pct": 4,
    }
    result = stock_quality_assessment(good, {"forward_pe": 20, "pfcf": 22}, cfg)
    assert result["passed"] is True
    weak = {"forward_pe": 60, "total_debt_equity": 6, "short_float_pct": 30}
    result = stock_quality_assessment(weak, {"forward_pe": 20, "pfcf": 22}, cfg)
    assert result["passed"] is False
    assert "excess_leverage" in result["hard_fail"]


def test_defensive_lean_requires_dated_review_but_is_not_auto_revoked():
    lean = {"enabled": True, "set_at": "2026-07-18", "review_after_days": 5,
            "defensive_sectors": ["Utilities", "Consumer Staples", "Healthcare"]}
    status = directive_review_status(
        lean,
        [{"sector": "Energy", "state": "LEADING", "quarantined": False}],
        now=date(2026, 7, 24),
    )
    assert status["enabled"] is True
    assert status["requires_review"] is True
    assert "Energy" in status["conflicting_sectors"]
    assert "never auto-revoke" in status["instruction"]
