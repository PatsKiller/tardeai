"""Materiality tiers for thesis research budget protection.

Membership / auto-promotion / social_score are NOT thesis evidence.
Only T0/T1/T2 normally receive expensive thesis work.
"""
from __future__ import annotations

from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"

TIERS = (
    "T0_CURRENT_HOLDING",
    "T1_REENTRY_NEAR",
    "T1_HIGH_OPPORTUNITY",
    "T1_MULTI_DESK",
    "T2_MATERIAL_WATCH",
    "T3_DISCOVERY",
    "T4_COLD_INSUFFICIENT",
)

EXPENSIVE_TIERS = frozenset({
    "T0_CURRENT_HOLDING",
    "T1_REENTRY_NEAR",
    "T1_HIGH_OPPORTUNITY",
    "T1_MULTI_DESK",
    "T2_MATERIAL_WATCH",
})


def classify_materiality(
    *,
    memberships: Optional[list[str]] = None,
    held: bool = False,
    reentry_state: str | None = None,
    opportunity_rank: Any = None,
    scope_tier: str | None = None,
    source_tier: str | None = None,
    desk_concurrence: int = 0,
    research_quality: float | None = None,
    freshness: str | None = None,
    origin_system: str | None = None,
    provenance_complete: bool = True,
    social_score: float | None = None,
) -> dict[str, Any]:
    """Return tier + whether expensive thesis work is allowed."""
    m = set(memberships or [])
    if held or "HELD" in m:
        tier = "T0_CURRENT_HOLDING"
    else:
        rs = str(reentry_state or "").upper()
        near = any(x in rs for x in ("NEAR", "READY", "IN_ZONE", "REENTER"))
        try:
            rank = int(opportunity_rank) if opportunity_rank is not None else 999
        except (TypeError, ValueError):
            rank = 999
        if near and ("REENTRY" in m or "FORMER_HOLDING" in m):
            tier = "T1_REENTRY_NEAR"
        elif "OPPORTUNITY" in m and rank <= 20:
            tier = "T1_HIGH_OPPORTUNITY"
        elif desk_concurrence >= 2 or str(scope_tier or "").upper() in {"CORE", "ACTIVE", "A"}:
            tier = "T1_MULTI_DESK"
        elif "REENTRY" in m or "FORMER_HOLDING" in m or "OPPORTUNITY" in m:
            tier = "T2_MATERIAL_WATCH"
        elif str(source_tier or "").lower() == "candidate" or (
            origin_system and "research" in str(origin_system).lower()
        ):
            tier = "T3_DISCOVERY"
        elif "WATCHLIST" in m:
            # social_score may boost ranking but never alone creates T1
            if social_score is not None and float(social_score) >= 80 and provenance_complete:
                tier = "T3_DISCOVERY"
            else:
                tier = "T4_COLD_INSUFFICIENT"
        else:
            tier = "T4_COLD_INSUFFICIENT"

    # Legacy / incomplete provenance: never elevate above T3 for expensive work
    if not provenance_complete and tier in EXPENSIVE_TIERS and tier != "T0_CURRENT_HOLDING":
        # holdings still get work; others demote trust
        expensive_ok = tier == "T0_CURRENT_HOLDING"
        trust = "LEGACY_UNATTRIBUTED" if origin_system in (None, "", "unknown") else "PROVENANCE_INCOMPLETE"
    else:
        expensive_ok = tier in EXPENSIVE_TIERS
        trust = "PROVENANCE_OK" if provenance_complete else "PROVENANCE_INCOMPLETE"

    return {
        "materiality_tier": tier,
        "expensive_thesis_work_allowed": expensive_ok,
        "membership_is_not_evidence": True,
        "social_score_is_derived_only": True,
        "auto_apply_is_not_research_confidence": True,
        "bootstrap_hit_rate_floor_is_not_measured_alpha": True,
        "evidence_trust": trust,
        "inputs": {
            "memberships": sorted(m),
            "held": held,
            "reentry_state": reentry_state,
            "opportunity_rank": opportunity_rank,
            "scope_tier": scope_tier,
            "source_tier": source_tier,
            "desk_concurrence": desk_concurrence,
            "research_quality": research_quality,
            "freshness": freshness,
            "origin_system": origin_system,
            "social_score": social_score,
        },
        "authority": AUTHORITY,
        "financial_action": False,
    }
