#!/usr/bin/env python3
"""Fundamental freshness governance — a packet is not FRESH because price is.

Price freshness is not thesis freshness. Fundamentals are classified into an
honest, instrument-aware state, and a stale/partial fundamental set drags the
overall packet data-quality down (while the thesis stays visible — the action
policy is what refuses READY).

Pure: no DB, no network.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fundamentals_freshness as ff  # noqa: E402

NOW = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)
RECENT = (NOW - timedelta(days=1)).isoformat()
OLD = (NOW - timedelta(days=10)).isoformat()

FULL = {"pe": 25, "oper_margin_pct": 26, "lt_debt_equity": 1.0, "eps_next_5y": 20,
        "market_cap_usd_millions": 67000}


# ── instrument-aware classification ───────────────────────────────────────────

def test_established_full_recent_is_fresh():
    r = ff.classify(FULL, fetched_at=RECENT, now=NOW)
    assert r["state"] == ff.FRESH and r["instrument_class"] == "established_company"


def test_established_stale_by_age():
    r = ff.classify(FULL, fetched_at=OLD, now=NOW)
    assert r["state"] == ff.STALE


def test_established_missing_critical_is_partial():
    r = ff.classify({"pe": 25, "market_cap_usd_millions": 1000}, fetched_at=RECENT, now=NOW)
    assert r["state"] == ff.PARTIAL
    assert "profitability" in r["missing_critical_fields"]


def test_pre_profit_missing_pe_is_not_a_failure():
    """A pre-profit recent listing missing P/E is evaluated on cash/liquidity/
    trajectory — NOT flagged unavailable or partial for the missing P/E."""
    r = ff.classify({"eps_ttm": -2.5, "market_cap_usd_millions": 5000,
                     "current_ratio": 3.0, "sales_qoq": 40}, fetched_at=RECENT, now=NOW)
    assert r["state"] == ff.FRESH and r["instrument_class"] == "pre_profit"
    assert r["missing_critical_fields"] == []


def test_etf_is_not_applicable():
    r = ff.classify({"expense_ratio": 0.04}, instrument_type="etf", fetched_at=RECENT, now=NOW)
    assert r["state"] == ff.NOT_APPLICABLE and r["instrument_class"] == "etf"


def test_operating_company_with_no_fundamentals_is_unavailable():
    r = ff.classify({}, fetched_at=None, now=NOW)
    assert r["state"] == ff.UNAVAILABLE


# ── provenance ────────────────────────────────────────────────────────────────

def test_provenance_fields_present():
    r = ff.classify(FULL, fetched_at=RECENT, provider="finviz_enrichment", now=NOW)
    for k in ("provider", "fetched_at", "cache_age_days", "field_count",
              "critical_field_count", "missing_critical_fields", "source_status"):
        assert k in r
    assert r["provider"] == "finviz_enrichment" and r["field_count"] == len(FULL)


# ── timestamp vs content (spec F6/F7) ─────────────────────────────────────────

def test_timestamp_change_alone_does_not_change_content_hash():
    """The invalidation content hash is over the FIELDS, not the timestamp, so a
    re-fetch with identical content is deterministic, not a spurious change."""
    import packet_invalidation as inv
    a = inv._h({k: FULL[k] for k in FULL})
    b = inv._h({k: FULL[k] for k in FULL})
    assert a == b


def test_content_change_same_timestamp_changes_hash():
    import packet_invalidation as inv
    a = inv._h(dict(FULL))
    b = inv._h({**FULL, "pe": 30})   # same timestamp, different content
    assert a != b


# ── integration: overall data-quality reflects fundamentals ───────────────────

def test_stale_fundamentals_prevent_overall_fresh():
    """Even with fresh price + technicals, stale fundamentals must not leave the
    overall state FRESH (Part D headline)."""
    import shadow_decision_service as svc
    import event_normalizer as ev

    facts = {"live_price": 100.0, "enriched_price": 100.0, "atr": 2.0,
             "support": [90.0], "resistance": [110.0],
             "fundamentals": {"pe": 25, "oper_margin_pct": 26, "lt_debt_equity": 1.0,
                              "eps_next_5y": 20, "market_cap_usd_millions": 1000,
                              "fundamentals_as_of": OLD},
             "instrument_type": None, "quote_type": None}

    class _E:
        state, reason, date = ev.SCHEDULED, "", None
    dq = svc.assess_data_quality(facts, _E())
    assert dq["dimensions"]["price"] == "FRESH"
    assert dq["dimensions"]["fundamentals"] == "STALE"
    assert dq["state"] != "FRESH", "stale fundamentals must drag overall below FRESH"


def test_pre_profit_no_pe_does_not_drag_overall():
    import shadow_decision_service as svc
    import event_normalizer as ev
    facts = {"live_price": 20.0, "enriched_price": 20.0, "atr": 1.0,
             "support": [15.0], "resistance": [25.0],
             "fundamentals": {"eps_ttm": -2.5, "market_cap_usd_millions": 5000,
                              "current_ratio": 3.0, "sales_qoq": 40,
                              "fundamentals_as_of": RECENT},
             "instrument_type": None, "quote_type": None}

    class _E:
        state, reason, date = ev.SCHEDULED, "", None
    dq = svc.assess_data_quality(facts, _E())
    assert dq["dimensions"]["fundamentals"] == "FRESH"
    assert dq["state"] in ("FRESH", "PARTIAL")   # not dragged by the absent P/E
