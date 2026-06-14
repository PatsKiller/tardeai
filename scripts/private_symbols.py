#!/usr/bin/env python3
"""private_symbols.py — registry of PRIVATE / non-tradeable pseudo-tickers (single source of truth).

Stops the whole system from hallucinating that a private company is a live, investable ticker. The
operator can add a directive like "watch SPCX" meaning SpaceX — but SPCX is a DELISTED SPAC ETF, NOT
SpaceX, and SpaceX has no public stock. Any price/entry/R:R the pipelines attach to these is meaningless,
so consumers (watchlist cards, ask box, research) flag them and suppress the fake tradeable framing.
"""
from __future__ import annotations

PRIVATE_NONTRADEABLE = {
    "SPCX": {"company": "SpaceX",
             "note": "⚠ SPCX is a DELISTED SPAC ETF — NOT SpaceX. SpaceX is PRIVATE with no public ticker. "
                     "Any price/entry shown is stale/incorrect. Exposure only via ARK Venture (ARKVX) or "
                     "Destiny Tech100 (DXYZ)."},
    "SPACEX": {"company": "SpaceX",
               "note": "SpaceX is PRIVATE — no public ticker. Exposure only via ARKVX / DXYZ / pre-IPO secondaries."},
    "OPENAI": {"company": "OpenAI", "note": "OpenAI is private — no ticker. Indirect via MSFT only."},
    "XAI": {"company": "xAI", "note": "xAI is private — no public ticker."},
    "STRIPE": {"company": "Stripe", "note": "Stripe is private — no public ticker."},
    "ANTHROPIC": {"company": "Anthropic", "note": "Anthropic is private — indirect via AMZN/GOOGL only."},
    "DATABRICKS": {"company": "Databricks", "note": "Databricks is private — no public ticker."},
}


def is_private_nontradeable(symbol: str) -> bool:
    return (symbol or "").strip().upper() in PRIVATE_NONTRADEABLE


def private_info(symbol: str) -> dict | None:
    return PRIVATE_NONTRADEABLE.get((symbol or "").strip().upper())
