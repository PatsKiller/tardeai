"""Data models for Hermes Scope Governor decisions and governed universe feed."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ScopeTier = Literal["S0", "S1", "S2", "S3"]
HeatTier = Literal["hot", "warm", "cold"]
ScopeAction = Literal["assign", "promote", "demote", "reactivate", "pause"]

TIER_HEAT: dict[str, HeatTier] = {
    "S0": "hot",
    "S1": "hot",
    "S2": "warm",
    "S3": "cold",
}

TIER_FREQUENCY: dict[str, str] = {
    "S0": "every_15m",
    "S1": "every_30m_market_hours",
    "S2": "premarket_daily",
    "S3": "on_event_only",
}


def heat_of(tier: str | None) -> HeatTier:
    return TIER_HEAT.get(tier or "S3", "cold")


@dataclass
class SymbolSignals:
    symbol: str
    is_holding: bool = False
    is_open_position: bool = False
    is_live_proposal: bool = False
    is_operator_directive: bool = False
    is_open_scalp: bool = False
    is_watchlist_active: bool = False
    is_high_conviction_watch: bool = False
    hermes_composite: float | None = None
    hermes_rank: int | None = None
    has_fresh_catalyst: bool = False
    has_fresh_directive_hit: bool = False
    has_fresh_event: bool = False
    social_score: float | None = None
    social_fresh_hours: float | None = None
    rvol: float | None = None
    avg_volume: float | None = None
    atr_pct: float | None = None
    outcome_hits: int = 0
    outcome_misses: int = 0
    outcome_neutral: int = 0
    avg_realized_r: float | None = None
    research_actioned_rate: float | None = None
    regime_label: str | None = None
    sector: str | None = None


@dataclass
class SymbolEdgeScore:
    symbol: str
    edge_score: float
    components: dict[str, float] = field(default_factory=dict)
    signals: SymbolSignals | None = None
    reasons: list[str] = field(default_factory=list)
    outcome_gate: str | None = None  # promote_eligible | demote_pressure | pause_eligible | neutral


@dataclass
class ScopeDecision:
    symbol: str
    from_tier: str | None
    to_tier: str
    action: ScopeAction
    reason: str
    edge_score: float | None = None
    heat: HeatTier = "cold"
    monitoring_frequency: str = "on_event_only"
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class GovernedUniverse:
    version: str
    run_id: str
    generated_at: str
    regime_label: str | None
    total_cap: int
    counts_by_tier: dict[str, int]
    counts_by_heat: dict[str, int]
    live_universe: int
    estimated_score_computations_per_day: int
    symbols: list[dict[str, Any]]
    recent_decisions: list[dict[str, Any]]