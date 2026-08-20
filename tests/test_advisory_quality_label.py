"""Tests for accurate Advisory Desk quality labels."""
from __future__ import annotations

from scripts.lib.advisory_quality_label import classify_advisory_quality


def test_reentry_near_not_data_unavailable():
    row = {
        "row_class": "closed_journal",
        "verdict": "RE_ENTER",
        "reentry_state": "NEAR ENTRY",
        "rationale": "Price near zone",
        "data_quality": {
            "evidence_count": 2,
            "gap_count": 4,
            "evidence_gaps": ["catalysts", "earnings_calendar", "hermes_health", "analyst_context"],
            "quality": "DATA_UNAVAILABLE",
        },
    }
    c = classify_advisory_quality(row, row["data_quality"])
    assert c["kind"] == "REENTRY_MECHANICAL_OK"
    assert "DESK OK" in c["label"]
    assert "DATA_UNAVAILABLE" not in c["label"]
    assert c["requeueable"] is True
    assert "catalysts" in c["requeue_gaps"]


def test_alloc_cash_not_scored():
    row = {
        "row_class": "allocation",
        "symbol": "ALLOC:cash:schwab_rollover_ira",
        "verdict": "INSUFFICIENT_DATA",
        "rationale": "Cash in schwab_rollover_ira: $533248. Per-account drift not evaluated against model",
        "data_quality": {"evidence_count": 0, "gap_count": 0, "quality": "DATA_UNAVAILABLE"},
    }
    c = classify_advisory_quality(row, row["data_quality"])
    assert c["kind"] == "ALLOC_NOT_SCORED"
    assert "NOT SCORED" in c["label"]


def test_fixed_income_cusips():
    row = {
        "row_class": "allocation",
        "symbol": "ALLOC:fixed_income",
        "verdict": "INSUFFICIENT_DATA",
        "rationale": "three CUSIP positions (12507E201) may be bonds but are unresolved",
        "data_quality": {"evidence_count": 0, "gap_count": 0},
    }
    c = classify_advisory_quality(row, row["data_quality"])
    assert c["kind"] == "ALLOC_UNMEASURED"
    assert "CUSIP" in c["label"]


def test_mark_conflict():
    row = {
        "row_class": "holding",
        "verdict": "TRIM",
        "data_quality": {
            "action_suppressed": True,
            "banner": "DATA CONFLICT — ACTION SUPPRESSED",
            "evidence_count": 9,
            "gap_count": 3,
            "quality": "CONFLICTED",
        },
    }
    c = classify_advisory_quality(row, row["data_quality"])
    assert c["kind"] == "MARK_CONFLICT"
    assert c["requeueable"] is False


def test_watch_tech_stale():
    row = {
        "row_class": "watchlist",
        "verdict": "WAIT",
        "setup_state": "BLOCKED",
        "rationale": "quality admission: technical snapshot is STALE",
        "data_quality": {"evidence_count": 4, "gap_count": 4, "quality": "DATA_UNAVAILABLE"},
    }
    c = classify_advisory_quality(row, row["data_quality"])
    assert c["kind"] == "TECH_PIPELINE_STALE"
    assert "TECH CACHE" in c["label"]
