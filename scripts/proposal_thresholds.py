"""proposal_thresholds.py — single source of truth for proposal R:R floor + price-freshness.

These were previously redefined 3-4 different ways across the promote flow
(check_quality 1.2 / pre-promotion 2.0 / litmus 1.2 / curator 2.0 / band 2.0; freshness 0/15/20m).
Resolve them here from env/config so every gate agrees. Defaults preserve the canonical values.
"""
from __future__ import annotations

import os

# Canonical minimum reward:risk for a live/promotable trade.
MIN_RR_FLOOR_DEFAULT = float(os.getenv("PROPOSAL_MIN_RR_FLOOR", "2.0"))
# Soft pre-screen floor used by the early paper-generation quality filter (looser than live).
MIN_RR_PRESCREEN = float(os.getenv("PROPOSAL_MIN_RR_PRESCREEN", "1.2"))
# How old a stored quote may be (minutes) before it is "stale" for live R:R / zone math.
PRICE_MAX_AGE_MIN = int(os.getenv("BROKER_PRICE_MAX_AGE_MIN", "20"))


def min_rr_floor(strategy_id: str | None = None) -> float:
    """Live/promote R:R floor. Per-strategy override via PROPOSAL_MIN_RR_FLOOR__<STRATEGY> env."""
    if strategy_id:
        ov = os.getenv(f"PROPOSAL_MIN_RR_FLOOR__{strategy_id.upper()}")
        if ov:
            try:
                return float(ov)
            except ValueError:
                pass
    return MIN_RR_FLOOR_DEFAULT


def min_rr_prescreen() -> float:
    """Looser floor for the early paper-generation quality screen (real gate is min_rr_floor)."""
    return MIN_RR_PRESCREEN


def price_max_age_min() -> int:
    """Canonical max stored-quote age (minutes) for live math."""
    return PRICE_MAX_AGE_MIN
