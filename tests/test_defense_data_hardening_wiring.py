from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_sector_engine_uses_exact_20_distinct_sessions_and_sample_label():
    text = (ROOT / "scripts/sector_momentum_engine.py").read_text()
    assert "GROUP BY symbol, price_date" in text
    assert "WHERE session_n = 20" in text
    assert "top-movers NH/NL sample" in text
    assert "broad strength" not in text


def test_industry_engine_uses_same_finviz_view_for_spy_and_groups():
    text = (ROOT / "scripts/finviz_industry_groups.py").read_text()
    assert '_finviz_fetch_view(["SPY"], 141' in text
    assert "same_vendor_same_run" in text
    assert "sector_map(cur)" not in text


def test_recommendations_are_risk_and_quality_aware():
    text = (ROOT / "scripts/defense_recommendations.py").read_text()
    for token in ("allocation_decision", "realized_vol_corr", "stock_quality_assessment",
                  "requires_close_confirmed_industry", "directive_reviews"):
        assert token in text


def test_fund_lookthrough_exposes_provenance_and_unmapped_weight():
    text = (ROOT / "scripts/fund_lookthrough.py").read_text()
    for token in ("factsheet_as_of", "refresh_due", "coverage_pct", "unmapped_weight_pct", "_provenance"):
        assert token in text
