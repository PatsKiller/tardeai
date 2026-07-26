from datetime import date

from scripts.defense_data_quality import (
    canonical_industry_sector, directive_review, exact_session_breadth,
    fund_lookthrough_quality, industry_window_quality, label_market_internals,
    quarantine_stale_rows, stock_quality_gate, target_gap,
)


def test_exact_breadth_dedupes_and_uses_20_sessions():
    rows = []
    for sym in ("A", "B"):
        for i in range(20):
            rows.append((sym, f"2026-06-{i+1:02d}", 100 + i if sym == "A" else 120 - i))
    rows.append(("A", "2026-06-20", 125))
    out = exact_session_breadth(rows, min_members=2)
    assert out["breadth_pct"] == 50
    assert out["duplicate_dates_removed"] == 1
    assert out["sessions"] == 20


def test_capped_internals_are_sample_only():
    out = label_market_internals({"new_high": 15, "new_low": 15, "source": "market_movers latest capture (top-15 caps per signal)"})
    assert out["scope"] == "top_movers_sample"
    assert "sample" in out["display_label"]


def test_mixed_intraday_industry_windows_are_approximate():
    q = industry_window_quality(industry_provider="finviz", benchmark_provider="local_db", industry_as_of="2026-07-24T12:30:00Z", benchmark_as_of="2026-07-23", capture_kind="refresh")
    assert q.state == "approximate_mixed_windows"
    assert "intraday_refresh_not_close_confirmed" in q.reasons


def test_mapping_fails_visible_when_unmapped():
    assert canonical_industry_sector("Unknown", {})["quality"]["state"] == "unmapped"


def test_target_gap_is_bounded_and_advisory():
    out = target_gap(actual_pct=23.4, benchmark_pct=12, active_tilt_cap_pct=5, mandate="capital_preservation")
    assert out["bounded_gap_pct"] == -5
    assert out["advisory_only"] is True


def test_stock_gate_fails_closed_on_missing_features():
    out = stock_quality_gate({"earnings_revision_3m": 1})
    assert out["eligible"] is False
    assert out["missing"]


def test_directive_requires_review_but_never_auto_revokes():
    out = directive_review(set_date="2026-07-18", evidence_as_of="2026-07-24", conflicts=["energy leadership"])
    assert out["review_due"] is True
    assert out["auto_revoke"] is False


def test_fund_lookthrough_requires_provenance():
    out = fund_lookthrough_quality(provider=None, factsheet_date=None, coverage_pct=90, unmapped_pct=10, now=date(2026, 7, 24))
    assert out["quality"]["state"] == "review_required"


def test_stale_rows_are_quarantined():
    out = quarantine_stale_rows([{"etf": "XLRE", "as_of": "2026-07-13"}, {"etf": "XLE", "as_of": "2026-07-23"}], as_of=date(2026, 7, 24))
    assert [r["etf"] for r in out["quarantined"]] == ["XLRE"]
    assert [r["etf"] for r in out["current"]] == ["XLE"]
