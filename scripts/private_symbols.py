#!/usr/bin/env python3
"""private_symbols.py — registry of PRIVATE / non-tradeable pseudo-tickers (single source of truth).

Stops the whole system from hallucinating that a private company is a live, investable ticker. The
operator can add a directive like "watch SPCX" meaning SpaceX — but SPCX is a DELISTED SPAC ETF, NOT
SpaceX, and SpaceX has no public stock. Any price/entry/R:R the pipelines attach to these is meaningless,
so consumers (watchlist cards, ask box, research) flag them and suppress the fake tradeable framing.
"""
from __future__ import annotations

# KEEP THIS CURRENT — a private company can IPO and become a live ticker. Verify against LIVE quote data
# before adding/keeping an entry; do NOT assume from stale model knowledge.
#   • SpaceX IPO'd 2026-06-12 (ticker SPCX, Nasdaq, ~$161) — it is PUBLIC. REMOVED from this list.
#     (xAI / X were folded into SpaceX, so that exposure is now via SPCX too.)
# Only list companies that genuinely have NO public ticker right now.
PRIVATE_NONTRADEABLE = {
    "OPENAI": {"company": "OpenAI", "note": "OpenAI is private — no ticker. Indirect via MSFT only."},
    "STRIPE": {"company": "Stripe", "note": "Stripe is private — no public ticker."},
    "ANTHROPIC": {"company": "Anthropic", "note": "Anthropic is private — indirect via AMZN/GOOGL only."},
    "DATABRICKS": {"company": "Databricks", "note": "Databricks is private — no public ticker."},
}


def is_private_nontradeable(symbol: str) -> bool:
    return (symbol or "").strip().upper() in PRIVATE_NONTRADEABLE


def private_info(symbol: str) -> dict | None:
    return PRIVATE_NONTRADEABLE.get((symbol or "").strip().upper())
