#!/usr/bin/env python3
"""M3-S5.5 — deterministic field-level source arbitration.

Chooses ONE source per observation type by a versioned authority policy. NEVER averages conflicting
sources. Rules (design §4 tier ladder + operator ruling):
  * stale source loses to a fresh eligible source;
  * delayed data cannot replace real-time without a VISIBLE tier downgrade;
  * incompatible feeds are never combined into one RVOL numerator/denominator (see require_feed_match);
  * two fresh eligible sources that disagree materially on price → SOURCE_CONFLICT;
  * an unresolved conflict lowers DCF or blocks the relevant gate (a directive, never a silent pick);
  * source availability may NEVER raise a score or turn a failed trigger into a passing one — this
    module only selects the canonical observation; scoring/trigger formulas are untouched.
Market-signal types (bar/quote/trade/book) and broker-state types (account/position/order) are
arbitrated on disjoint authority: brokers are authoritative only for THEIR OWN resources.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

try:
    from observation import (Observation, ObservationType, EntitlementState, FreshnessState,
                             DataTier)
except ModuleNotFoundError:  # package import
    from .observation import (Observation, ObservationType, EntitlementState, FreshnessState,
                              DataTier)

POLICY_VERSION = "source-authority-v1"

# Real-time consolidated entitlements (true T1). IEX_ONLY is real-time but venue-partial → T1_venue.
_REALTIME_CONSOLIDATED = {EntitlementState.SIP_REALTIME, EntitlementState.AVAILABLE_REALTIME}


@dataclass
class AuthorityPolicy:
    """Priority order of source_systems per observation type + acceptable entitlements. Versioned."""
    version: str = POLICY_VERSION
    # market-signal priorities (higher index = lower priority)
    market_sources: dict = field(default_factory=lambda: {
        ObservationType.BAR: ["alpaca", "yahoo"],          # alpaca IEX realtime primary; yahoo degraded fallback
        ObservationType.QUOTE: ["moomoo", "alpaca"],       # T1: consolidated only; alpaca IEX = venue-partial
        ObservationType.TRADE: ["moomoo", "alpaca"],
        ObservationType.ORDER_BOOK: ["moomoo"],            # T2 only via moomoo gateway
    })
    # broker-state authority: a source is authoritative ONLY for its own resources
    broker_authority: dict = field(default_factory=lambda: {
        ObservationType.ACCOUNT_FACT: {"schwab": "schwab", "alpaca": "alpaca"},
        ObservationType.POSITION_FACT: {"schwab": "schwab", "alpaca": "alpaca"},
        ObservationType.ORDER_FACT: {"schwab": "schwab", "alpaca": "alpaca"},
    })
    price_tolerance_bps: float = 50.0     # fresh price disagreement beyond this → SOURCE_CONFLICT

    def sources_for(self, t: ObservationType) -> list[str]:
        return self.market_sources.get(t, [])


@dataclass
class SelectionResult:
    observation_type: str
    selected: Optional[Observation]
    selected_source: Optional[str]
    rejected: list                    # [{source, reason}]
    conflict: Optional[str]           # 'SOURCE_CONFLICT' | None
    tier: Optional[str]
    tier_downgraded: Optional[str]    # reason, or None
    directive: Optional[dict]         # {action: lower_dcf|block_gate, reason} on unresolved conflict
    selection_reason: str

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["selected"] = self.selected.to_dict() if self.selected else None
        return d


def _price(o: Observation) -> Optional[float]:
    p = o.payload_ref or {}
    for k in ("close", "c", "price", "last", "mid"):
        if k in p and p[k] is not None:
            try:
                return float(p[k])
            except (TypeError, ValueError):
                return None
    bid, ask = p.get("bid"), p.get("ask")
    if bid is not None and ask is not None:
        try:
            return (float(bid) + float(ask)) / 2.0
        except (TypeError, ValueError):
            return None
    return None


def _rank_key(policy: AuthorityPolicy, t: ObservationType):
    order = {s: i for i, s in enumerate(policy.sources_for(t))}

    def key(o: Observation):
        fresh = 0 if o.freshness_state == FreshnessState.FRESH else (1 if o.freshness_state == FreshnessState.AGING else 2)
        realtime = 0 if not o.delayed else 1
        prio = order.get(o.source_system, 99)
        return (fresh, realtime, prio)
    return key


def select_market_source(obs_type: ObservationType, candidates: list[Observation],
                         policy: Optional[AuthorityPolicy] = None) -> SelectionResult:
    """Deterministically select one market-signal observation. No averaging."""
    policy = policy or AuthorityPolicy()
    allowed_sources = policy.sources_for(obs_type)
    rejected = []
    eligible = []
    for c in candidates:
        if c.source_system not in allowed_sources:
            rejected.append({"source": c.source_system, "reason": "not_authoritative_for_type"})
        elif c.entitlement_state in (EntitlementState.UNAVAILABLE, EntitlementState.SCAFFOLD_ONLY,
                                     EntitlementState.UNRESOLVED):
            rejected.append({"source": c.source_system, "reason": f"entitlement={c.entitlement_state.value}"})
        else:
            eligible.append(c)
    if not eligible:
        return SelectionResult(obs_type.value, None, None, rejected, None, None, None, None,
                               "no_eligible_source")
    ranked = sorted(eligible, key=_rank_key(policy, obs_type))
    selected = ranked[0]
    for c in ranked[1:]:
        rejected.append({"source": c.source_system, "reason": "lower_priority_or_staler"})

    # tier downgrade visibility: delayed or venue-partial (IEX_ONLY) never silently sits at full tier
    tier = selected.data_tier.value
    downgrade = None
    if selected.delayed:
        downgrade = "delayed_data→tier_down"
    elif selected.entitlement_state == EntitlementState.IEX_ONLY and obs_type in (
            ObservationType.QUOTE, ObservationType.TRADE):
        downgrade = "iex_venue_partial→T1_venue_not_consolidated"
        tier = DataTier.T1_VENUE.value

    # conflict: another FRESH, non-delayed eligible source disagreeing materially on price
    conflict = None
    sp = _price(selected)
    for peer in ranked[1:]:
        if peer.freshness_state == FreshnessState.FRESH and not peer.delayed:
            pp = _price(peer)
            if sp and pp and sp > 0 and abs(pp - sp) / sp * 1e4 > policy.price_tolerance_bps:
                conflict = "SOURCE_CONFLICT"
                break
    directive = None
    if conflict:
        directive = {"action": "lower_dcf_or_block_gate", "reason": "SOURCE_CONFLICT",
                     "note": "unresolved fresh price disagreement — never averaged"}
    return SelectionResult(obs_type.value, selected, selected.source_system, rejected, conflict,
                           tier, downgrade, directive, "authority_policy_v1")


def select_broker_fact(obs_type: ObservationType, resource_owner: str,
                       candidates: list[Observation],
                       policy: Optional[AuthorityPolicy] = None) -> SelectionResult:
    """Broker facts: only the resource's OWN broker is authoritative (schwab for schwab, etc.)."""
    policy = policy or AuthorityPolicy()
    auth_map = policy.broker_authority.get(obs_type, {})
    rejected, selected = [], None
    for c in candidates:
        if c.source_system == resource_owner and auth_map.get(c.source_system) == resource_owner:
            selected = c
        else:
            rejected.append({"source": c.source_system, "reason": "not_owner_of_resource"})
    return SelectionResult(obs_type.value, selected, selected.source_system if selected else None,
                           rejected, None, selected.data_tier.value if selected else None, None, None,
                           "broker_owns_resource" if selected else "no_owner_source")


def require_feed_match(numerator_feed: Optional[str], denominator_feed: Optional[str]) -> None:
    """RVOL numerator (live) and denominator (profile) MUST share a feed or the ratio is biased.
    Raises ValueError on mismatch — never silently combined."""
    if numerator_feed != denominator_feed:
        raise ValueError(f"feed mismatch: numerator={numerator_feed} denominator={denominator_feed} "
                         "— RVOL_tod numerator/denominator must share a feed (not combined)")
