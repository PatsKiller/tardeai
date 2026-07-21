#!/usr/bin/env python3
"""fundamentals_freshness.py — provenance + freshness for the fundamental facts.

WHY THIS EXISTS
---------------
A packet was labelled DATA FRESH whenever the PRICE was fresh — even if the
long-term thesis rested on fundamentals cached a week ago, or on a coverage set
missing the fields that thesis needs. Price freshness is not thesis freshness.

This module classifies the fundamentals into an honest state, instrument-aware:
    FRESH                     recent + critical fields present
    PARTIAL                   present but missing some critical fields
    STALE                     older than the trust window
    CONFLICTED                sources disagree (reserved; single-source today)
    UNAVAILABLE               an operating company with no fundamentals at all
    LEGITIMATELY_NOT_APPLICABLE   an ETF (company fundamentals do not apply) or a
                                  genuinely pre-profit name missing only P/E

The critical-field set is INSTRUMENT-AWARE: a pre-profit recent listing missing
P/E is NOT a data failure — it is evaluated on cash, burn, backlog, revenue
trajectory, dilution and debt. An ETF's company fundamentals are not-applicable,
not unavailable.

PURE: takes a fundamentals dict + instrument hints; no DB, no network.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

STALE_DAYS = float(os.getenv("FUNDAMENTALS_STALE_DAYS", "7"))

FRESH = "FRESH"
PARTIAL = "PARTIAL"
STALE = "STALE"
CONFLICTED = "CONFLICTED"
UNAVAILABLE = "UNAVAILABLE"
NOT_APPLICABLE = "LEGITIMATELY_NOT_APPLICABLE"

# Instrument-aware critical fields. Each entry is a list of ALTERNATIVES — any one
# present satisfies that requirement (e.g. lt_debt_equity OR total_debt_equity).
CRITICAL_ESTABLISHED = [
    ("valuation", ("pe", "forward_pe", "ps")),
    ("profitability", ("oper_margin_pct", "profit_margin_pct", "roe_pct")),
    ("leverage", ("lt_debt_equity", "total_debt_equity", "current_ratio")),
    ("growth", ("eps_next_5y", "eps_next_y", "sales_past_5y", "sales_qoq")),
]
# Pre-profit: valuation via P/E is legitimately absent; use size + liquidity/debt +
# trajectory. Missing P/E does NOT count against it.
CRITICAL_PRE_PROFIT = [
    ("size", ("market_cap_usd_millions", "shares_outstanding_m")),
    ("liquidity_or_debt", ("current_ratio", "quick_ratio", "lt_debt_equity", "total_debt_equity")),
    ("trajectory", ("sales_qoq", "sales_past_5y", "eps_next_y", "eps_next_5y")),
]


def _now(now=None) -> datetime:
    return now or datetime.now(timezone.utc)


def _parse(ts) -> Optional[datetime]:
    if not ts:
        return None
    try:
        s = str(ts).replace(" ", "T", 1) if "T" not in str(ts) else str(ts)
        d = datetime.fromisoformat(s.replace("Z", "+00:00")[:32])
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def is_etf(instrument_type=None, quote_type=None, fundamentals=None) -> bool:
    it = str(instrument_type or "").lower()
    qt = str(quote_type or "").lower()
    if "etf" in it or "fund" in it or "etf" in qt or qt in ("etf", "mutualfund"):
        return True
    # ETFs carry an expense ratio and no company margins.
    f = fundamentals or {}
    if f.get("expense_ratio") is not None and f.get("oper_margin_pct") is None:
        return True
    return False


def looks_pre_profit(fundamentals: dict) -> bool:
    """No positive earnings / no P/E but has a market presence — a growth name,
    not a data hole."""
    f = fundamentals or {}
    eps = f.get("eps_ttm")
    has_size = f.get("market_cap_usd_millions") is not None
    no_pe = f.get("pe") is None
    negative_eps = eps is not None and float(eps) <= 0
    return has_size and (no_pe or negative_eps)


def classify(fundamentals: dict, *, instrument_type=None, quote_type=None,
             fetched_at=None, provider="finviz_enrichment", now=None) -> dict:
    """The fundamentals freshness/provenance record for the packet."""
    f = fundamentals or {}
    present = {k: v for k, v in f.items()
               if v is not None and k not in ("fundamentals_as_of",)}
    fetched = fetched_at or f.get("fundamentals_as_of")

    base = {
        "provider": provider if present else None,
        "fetched_at": fetched,
        "cache_age_days": None,
        "field_count": len(present),
        "critical_field_count": 0,
        "missing_critical_fields": [],
        "instrument_class": None,
        "source_status": "ok" if present else "empty",
    }

    # ── ETF: company fundamentals not applicable ──────────────────────────────
    if is_etf(instrument_type, quote_type, f):
        base.update(state=NOT_APPLICABLE, instrument_class="etf",
                    missing_critical_fields=[], critical_field_count=0)
        return base

    # ── no fundamentals at all on an operating company ────────────────────────
    if not present:
        base.update(state=UNAVAILABLE, instrument_class="operating_company")
        return base

    pre_profit = looks_pre_profit(f)
    rules = CRITICAL_PRE_PROFIT if pre_profit else CRITICAL_ESTABLISHED
    base["instrument_class"] = "pre_profit" if pre_profit else "established_company"

    missing = [name for name, alts in rules if not any(f.get(a) is not None for a in alts)]
    base["critical_field_count"] = len(rules) - len(missing)
    base["missing_critical_fields"] = missing

    # ── age ───────────────────────────────────────────────────────────────────
    fd = _parse(fetched)
    if fd is not None:
        age = (_now(now) - fd).total_seconds() / 86400.0
        base["cache_age_days"] = round(age, 1)
        if age > STALE_DAYS:
            base["state"] = STALE
            return base

    # ── state ─────────────────────────────────────────────────────────────────
    base["state"] = PARTIAL if missing else FRESH
    return base
