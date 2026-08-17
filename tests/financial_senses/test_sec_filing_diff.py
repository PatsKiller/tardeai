"""Deterministic SEC filing-fact comparison tests (like-for-like semantics)."""
from __future__ import annotations

from financial_senses.sec_filing_diff import (
    COMPARISON_OK,
    COMPARISON_UNAVAILABLE,
    FACT_TAGS,
    compare_filing_facts,
    duration_kind,
)


def d(value, start="2023-01-01", end="2023-12-31", fp="FY", units="USD",
      form="10-K", frame=None, filed="2024-02-15"):
    """Duration (flow) fact with full XBRL context."""
    return {
        "value": value, "units": units, "start": start, "end": end,
        "fp": fp, "form": form, "frame": frame, "filed": filed,
    }


def i(value, end="2023-12-31", units="USD", filed="2024-02-15"):
    """Instantaneous (stock) fact — no start date."""
    return {"value": value, "units": units, "end": end, "filed": filed}


def test_annual_like_for_like_ok():
    a = {"Revenues": d(100.0)}
    b = {"Revenues": d(110.0, start="2024-01-01", end="2024-12-31")}
    r = compare_filing_facts(a, b)
    assert r["comparison_status"] == COMPARISON_OK
    rev = r["comparisons"]["revenue"]
    assert rev["delta"] == 10.0
    assert rev["delta_pct"] == 10.0
    assert rev["comparison_status"] == COMPARISON_OK


def test_annual_vs_quarter_unavailable():
    a = {"Revenues": d(100.0, fp="FY")}
    b = {"Revenues": d(110.0, start="2024-10-01", end="2024-12-31", fp="Q4")}
    r = compare_filing_facts(a, b)
    assert r["comparisons"]["revenue"]["comparison_status"] == COMPARISON_UNAVAILABLE
    assert "duration_context_mismatch" in r["comparisons"]["revenue"]["reason"]


def test_quarter_vs_ytd_same_end_unavailable():
    # Same end date (2024-06-30), different duration: Q2 vs YTD.
    a = {"Revenues": d(100.0, start="2024-04-01", end="2024-06-30", fp="Q2", form="10-Q")}
    b = {"Revenues": d(110.0, start="2024-01-01", end="2024-06-30", fp="Q2", frame="YTD2024", form="10-Q")}
    r = compare_filing_facts(a, b)
    assert r["comparisons"]["revenue"]["comparison_status"] == COMPARISON_UNAVAILABLE
    assert "duration_context_mismatch" in r["comparisons"]["revenue"]["reason"]


def test_quarter_q1_vs_q2_mismatch_unavailable():
    a = {"Revenues": d(100.0, start="2024-01-01", end="2024-03-31", fp="Q1", form="10-Q")}
    b = {"Revenues": d(110.0, start="2024-04-01", end="2024-06-30", fp="Q2", form="10-Q")}
    r = compare_filing_facts(a, b)
    assert r["comparisons"]["revenue"]["comparison_status"] == COMPARISON_UNAVAILABLE
    assert "fiscal_period_mismatch" in r["comparisons"]["revenue"]["reason"]


def test_duration_context_unavailable_is_unavailable():
    # Simplified facts (no start/fp/frame) cannot establish equivalence.
    a = {"Revenues": {"value": 100.0, "units": "USD"}}
    b = {"Revenues": {"value": 110.0, "units": "USD"}}
    r = compare_filing_facts(a, b)
    assert r["comparisons"]["revenue"]["comparison_status"] == COMPARISON_UNAVAILABLE


def test_instantaneous_point_in_time_ok():
    a = {"CashAndCashEquivalentsAtCarryingValue": i(20.0)}
    b = {"CashAndCashEquivalentsAtCarryingValue": i(25.0, end="2024-12-31")}
    r = compare_filing_facts(a, b)
    cash = r["comparisons"]["cash"]
    assert cash["comparison_status"] == COMPARISON_OK
    assert cash["delta"] == 5.0


def test_unit_mismatch_is_unavailable():
    a = {"Revenues": d(100.0, units="USD")}
    b = {"Revenues": d(100.0, units="EUR")}
    r = compare_filing_facts(a, b)
    assert r["comparisons"]["revenue"]["comparison_status"] == COMPARISON_UNAVAILABLE
    assert "unit_mismatch" in r["comparisons"]["revenue"]["reason"]


def test_missing_period_is_unavailable():
    a = {"Revenues": d(100.0)}
    b = {}
    r = compare_filing_facts(a, b)
    assert r["comparisons"]["revenue"]["comparison_status"] == COMPARISON_UNAVAILABLE


def test_net_income_sign_flip_material():
    a = {"NetIncomeLoss": d(10.0)}
    b = {"NetIncomeLoss": d(-5.0, start="2024-01-01", end="2024-12-31")}
    r = compare_filing_facts(a, b)
    assert r["comparisons"]["net_income"]["material"] is True


def test_canonical_key_input_supported():
    a = {"revenue": d(100.0)}
    b = {"revenue": d(120.0, start="2024-01-01", end="2024-12-31")}
    r = compare_filing_facts(a, b)
    assert r["comparisons"]["revenue"]["delta"] == 20.0


def test_duration_first_classification():
    # fp=Q2/Q3 must not override the actual start/end duration.
    assert duration_kind({"start": "2026-01-01", "end": "2026-06-30", "fp": "Q2"}) == "YTD"
    assert duration_kind({"start": "2026-04-01", "end": "2026-06-30", "fp": "Q2"}) == "QUARTERLY"
    assert duration_kind({"start": "2026-01-01", "end": "2026-09-30", "fp": "Q3"}) == "YTD"
    assert duration_kind({"start": "2026-07-01", "end": "2026-09-30", "fp": "Q3"}) == "QUARTERLY"
    assert duration_kind({"start": "2026-01-01", "end": "2026-12-31", "fp": "FY"}) == "ANNUAL"


def test_duration_kind_instant_without_start():
    assert duration_kind({"end": "2024-12-31"}) == "INSTANT"


def test_ytd_q2_vs_q3_horizon_mismatch_unavailable():
    # Six-month cumulative (Q2 YTD) vs nine-month cumulative (Q3 YTD) both
    # classify as YTD, but they are NOT like-for-like: different cumulative
    # horizons must fail closed rather than yield a misleading delta.
    a = {"Revenues": d(100.0, start="2024-01-01", end="2024-06-30", fp="Q2", form="10-Q")}
    b = {"Revenues": d(200.0, start="2024-01-01", end="2024-09-30", fp="Q3", form="10-Q")}
    r = compare_filing_facts(a, b)
    assert r["comparisons"]["revenue"]["comparison_status"] == COMPARISON_UNAVAILABLE
    assert "ytd_horizon_mismatch" in r["comparisons"]["revenue"]["reason"]


def test_ytd_same_fiscal_period_across_years_ok():
    # Q2 YTD vs Q2 YTD in different years is the same cumulative horizon.
    a = {"Revenues": d(100.0, start="2024-01-01", end="2024-06-30", fp="Q2", form="10-Q")}
    b = {"Revenues": d(110.0, start="2025-01-01", end="2025-06-30", fp="Q2", form="10-Q")}
    r = compare_filing_facts(a, b)
    assert r["comparisons"]["revenue"]["comparison_status"] == COMPARISON_OK
    assert r["comparisons"]["revenue"]["delta"] == 10.0


def test_ytd_six_month_vs_nine_month_span_unavailable():
    # No fiscal-period label: 6-month vs 9-month span is a different horizon.
    a = {"Revenues": d(100.0, start="2026-01-01", end="2026-06-30", fp="")}
    b = {"Revenues": d(200.0, start="2026-01-01", end="2026-09-30", fp="")}
    r = compare_filing_facts(a, b)
    assert r["comparisons"]["revenue"]["comparison_status"] == COMPARISON_UNAVAILABLE
    assert "ytd_horizon_mismatch" in r["comparisons"]["revenue"]["reason"]


def test_ytd_span_within_tolerance_ok():
    # ~181d vs ~180d (one-day jitter, no fiscal period) is the same horizon.
    a = {"Revenues": d(100.0, start="2024-01-01", end="2024-06-30", fp="")}
    b = {"Revenues": d(110.0, start="2023-01-01", end="2023-06-30", fp="")}
    r = compare_filing_facts(a, b)
    assert r["comparisons"]["revenue"]["comparison_status"] == COMPARISON_OK


def test_ytd_multi_context_horizon_ambiguous_unavailable():
    # Both periods carry a Q2-YTD and a Q3-YTD candidate; two distinct horizons
    # on both sides is ambiguous and must fail closed.
    rows = [
        d(100.0, start="2024-01-01", end="2024-06-30", fp="Q2"),
        d(150.0, start="2024-01-01", end="2024-09-30", fp="Q3"),
    ]
    rows_b = [
        d(110.0, start="2024-01-01", end="2024-06-30", fp="Q2"),
        d(165.0, start="2024-01-01", end="2024-09-30", fp="Q3"),
    ]
    a = {"Revenues": rows}
    b = {"Revenues": rows_b}
    r = compare_filing_facts(a, b)
    assert r["comparisons"]["revenue"]["comparison_status"] == COMPARISON_UNAVAILABLE
    assert r["comparisons"]["revenue"]["reason"] in ("ambiguous_context", "no_like_for_like_pair")


def test_all_canonical_keys_present():
    a = {
        "Revenues": d(100.0),
        "NetIncomeLoss": d(50.0),
        "CashAndCashEquivalentsAtCarryingValue": i(20.0),
        "LongTermDebtNoncurrent": i(30.0),
        "EntityCommonStockSharesOutstanding": i(1000.0),
        "OperatingIncomeLoss": d(60.0),
        "NetCashProvidedByUsedInOperatingActivities": d(70.0),
        "PaymentsToAcquirePropertyPlantAndEquipment": d(-10.0),
    }
    b = {
        "Revenues": d(110.0, start="2024-01-01", end="2024-12-31"),
        "NetIncomeLoss": d(40.0, start="2024-01-01", end="2024-12-31"),
        "CashAndCashEquivalentsAtCarryingValue": i(25.0, end="2024-12-31"),
        "LongTermDebtNoncurrent": i(35.0, end="2024-12-31"),
        "EntityCommonStockSharesOutstanding": i(1100.0, end="2024-12-31"),
        "OperatingIncomeLoss": d(55.0, start="2024-01-01", end="2024-12-31"),
        "NetCashProvidedByUsedInOperatingActivities": d(80.0, start="2024-01-01", end="2024-12-31"),
        "PaymentsToAcquirePropertyPlantAndEquipment": d(-15.0, start="2024-01-01", end="2024-12-31"),
    }
    r = compare_filing_facts(a, b)
    for key in FACT_TAGS:
        assert key in r["comparisons"], key
