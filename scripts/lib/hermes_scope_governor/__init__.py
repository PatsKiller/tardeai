"""Hermes Scope Governor — sole owner of watchlist_items.scope_tier.

Hot/Warm/Cold map to S0+S1 / S2 / S3. Outcome yield outranks throughput yield.
"""
from .models import (
    ScopeDecision,
    ScopeTier,
    SymbolEdgeScore,
    TIER_FREQUENCY,
    TIER_HEAT,
    heat_of,
)
from .engine import ScopeGovernorEngine

__all__ = [
    "ScopeGovernorEngine",
    "ScopeDecision",
    "ScopeTier",
    "SymbolEdgeScore",
    "TIER_FREQUENCY",
    "TIER_HEAT",
    "heat_of",
]