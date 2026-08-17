"""Deterministic SEC filing-fact comparison tests."""
from __future__ import annotations

from financial_senses.sec_filing_diff import (
    COMPARISON_UNAVAILABLE,
    FACT_TAGS,
    compare_filing_facts,
)


def _tag_facts():
    a = {
        "Revenues": {"value": 100.0, "units": "USD"},
        "NetIncomeLoss": {"value": 50.0, "units": "USD"},
        "CashAndCashEquivalentsAtCarryingValue": {"value": 20.0, "units": "USD"},
    }
    b = {
        "Revenues": {"value": 110.0, "units": "USD"},
        "NetIncomeLoss": {"value": 40.0, "units": "USD"},
        "CashAndCashEquivalentsAtCarryingValue": {"value": 20.0, "units": "USD"},
    }
    return a, b


def test_revenue_change_computed():
    a, b = _tag_facts()
    r = compare_filing_facts(a, b)
    rev = r["changed_facts"]["revenue"]
    assert rev["delta"] == 10.0
    assert rev["delta_pct"] == 10.0


def test_net_income_sign_flip_material():
    a = {"NetIncomeLoss": {"value": 10.0, "units": "USD"}}
    b = {"NetIncomeLoss": {"value": -5.0, "units": "USD"}}
    r = compare_filing_facts(a, b)
    assert r["materiality"]["net_income"] is True


def test_unit_mismatch_is_unavailable():
    a = {"Revenues": {"value": 100.0, "units": "USD"}}
    b = {"Revenues": {"value": 100.0, "units": "EUR"}}
    r = compare_filing_facts(a, b)
    assert r["changed_facts"]["revenue"]["comparison_status"] == COMPARISON_UNAVAILABLE


def test_missing_period_is_unavailable():
    a = {"Revenues": {"value": 100.0, "units": "USD"}}
    b = {}
    r = compare_filing_facts(a, b)
    assert r["changed_facts"]["revenue"]["comparison_status"] == COMPARISON_UNAVAILABLE


def test_canonical_key_input_supported():
    a = {"revenue": {"value": 100.0, "units": "USD"}}
    b = {"revenue": {"value": 120.0, "units": "USD"}}
    r = compare_filing_facts(a, b)
    assert r["changed_facts"]["revenue"]["delta"] == 20.0


def test_unmapped_tags_reported():
    a = {"Revenues": {"value": 100.0}, "SomeWeirdTag": {"value": 1.0}}
    b = {"Revenues": {"value": 100.0}}
    r = compare_filing_facts(a, b)
    assert "SomeWeirdTag" in r["unmapped"]


def test_all_canonical_keys_present():
    a, b = _tag_facts()
    r = compare_filing_facts(a, b)
    for key in FACT_TAGS:
        assert key in r["changed_facts"]
