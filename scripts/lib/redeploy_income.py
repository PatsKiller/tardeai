"""redeploy_income — canonical per-symbol income model (defect map 2026-07-14 #8/#9).

ONE yield/income calculation shared by the plan engine, performance, pro forma
and memo so every tab shows the same number with the same provenance.

Sources (local cache only, provenance-tagged):
  - ticker_dividends   trailing-12M distributions (ex-date, USD per share)
  - ticker_prices      latest close (yield denominator)
  - instrument_facts   yfinance indicated distribution_yield_pct (fallback)

Rules:
  - trailing-distribution yield is PREFERRED whenever distribution history
    exists; the indicated (yfinance) yield is the fallback; `yield_type`
    states which one was used.
  - mutual-fund trailing distributions include capital-gain distributions;
    the ordinary-vs-capital-gain split is UNAVAILABLE and is said so — a
    trailing number is KNOWN history, never a guaranteed recurring rate.
  - nothing is fabricated: no data → income_status 'UNAVAILABLE', yield None.

Advisory only.
"""
from __future__ import annotations

from typing import Any

from lib.redeploy_price_history import (
    get_instrument_facts,
    load_closes,
    load_dividends,
)

ENGINE_VERSION = "income_1.0.0"

MUTUAL_FUND_CAPGAIN_NOTE = (
    "trailing distributions include capital-gain distributions — "
    "ordinary-vs-capital-gain split UNAVAILABLE; not guaranteed recurring"
)


def infer_distribution_frequency(dividend_count_12m: int) -> str | None:
    """Frequency from trailing-12M ex-date count; None when no distributions."""
    n = dividend_count_12m
    if n <= 0:
        return None
    if n >= 10:
        return "monthly"
    if 3 <= n <= 6:
        return "quarterly"
    if n <= 2:
        return "annual"
    return "irregular"


def income_snapshot(cur, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Canonical income snapshot per symbol — the ONLY yield calc to use.

    Returns {SYMBOL: {yield_type, yield_pct, trailing_distribution_yield_pct,
    indicated_yield_pct, distribution_frequency,
    distributions_trailing_12m_usd_per_share, income_status,
    recurring_income_note, source, as_of, coverage}}.
    """
    syms = sorted({str(s).upper().strip() for s in symbols if s and str(s).strip()})
    facts_map = get_instrument_facts(cur, syms) if syms else {}
    out: dict[str, dict[str, Any]] = {}
    for sym in syms:
        facts = facts_map.get(sym) or {}
        divs = load_dividends(cur, sym, days=370)
        closes = load_closes(cur, sym, days=30)
        last_close = closes[-1][1] if closes and closes[-1][1] > 0 else None

        t12 = round(sum(a for _, a in divs), 6) if divs else None
        trailing = (round(t12 / last_close * 100.0, 2)
                    if t12 is not None and last_close else None)
        indicated = facts.get("distribution_yield_pct")

        if trailing is not None:
            yield_type, yield_pct, status = "trailing_distribution", trailing, "KNOWN"
            source = "ticker_dividends + ticker_prices (trailing 12M distributions / latest close)"
            as_of = str(divs[-1][0])
        elif indicated is not None:
            yield_type, yield_pct, status = "indicated", indicated, "ESTIMATED"
            source = "instrument_facts (yfinance indicated distribution yield)"
            as_of = str(facts.get("fetched_at")) if facts.get("fetched_at") else None
        else:
            yield_type, yield_pct, status = "unavailable", None, "UNAVAILABLE"
            source = None
            as_of = None

        note = None
        if trailing is not None and (facts.get("quote_type") or "").upper() == "MUTUALFUND":
            note = MUTUAL_FUND_CAPGAIN_NOTE

        out[sym] = {
            "symbol": sym,
            "yield_type": yield_type,
            "yield_pct": yield_pct,
            "trailing_distribution_yield_pct": trailing,
            "indicated_yield_pct": indicated,
            "distribution_frequency": infer_distribution_frequency(len(divs)),
            "distributions_trailing_12m_usd_per_share": t12,
            "income_status": status,
            "recurring_income_note": note,
            "source": source,
            "as_of": as_of,
            "coverage": {
                "dividend_rows_12m": len(divs),
                "latest_close_date": str(closes[-1][0]) if closes else None,
                "facts_fetched_at": (str(facts.get("fetched_at"))
                                     if facts.get("fetched_at") else None),
            },
        }
    return out
