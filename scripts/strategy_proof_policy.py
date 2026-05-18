#!/usr/bin/env python3
"""strategy_proof_policy.py — Pure strategy proof gating functions.

No DB writes. No side effects. No strategy activation. No trade creation.
"""
from datetime import datetime, timezone

THRESHOLDS = {
    "min_proposals_for_observing": 10,
    "min_proposals_for_review": 30,
    "min_simulations_for_review": 10,
    "min_paper_trades_for_review": 10,
    "min_closed_trades_for_review": 20,
    "min_closed_trades_for_decision": 30,
    "min_market_days_for_decision": 10,
    "min_lifecycle_linkage_rate": 0.90,
}

A5_END_DATE = "2026-05-22"


def get_strategy_sample_thresholds(strategy_id: str = "default") -> dict:
    return dict(THRESHOLDS)


def classify_strategy_proof_status(metrics: dict, a5_complete: bool = False) -> dict:
    proposals = metrics.get("proposal_count", 0)
    closed = metrics.get("closed_count", 0)
    linkage = metrics.get("lifecycle_linkage_rate", 0)

    if not a5_complete:
        status = "blocked_a5_incomplete" if proposals > 0 else "insufficient"
        return {"proof_status": status, "sample_quality": "insufficient",
                "decision_allowed": False, "recommendation_status": "human_review_only"}

    if closed >= THRESHOLDS["min_closed_trades_for_decision"] and \
       proposals >= THRESHOLDS["min_proposals_for_review"] and \
       linkage >= THRESHOLDS["min_lifecycle_linkage_rate"]:
        return {"proof_status": "decision_ready", "sample_quality": "usable",
                "decision_allowed": False, "recommendation_status": "human_review_only"}

    if closed >= THRESHOLDS["min_closed_trades_for_review"]:
        return {"proof_status": "review_ready", "sample_quality": "preliminary",
                "decision_allowed": False, "recommendation_status": "human_review_only"}

    if closed >= 5:
        return {"proof_status": "preliminary", "sample_quality": "preliminary",
                "decision_allowed": False, "recommendation_status": "human_review_only"}

    if proposals >= THRESHOLDS["min_proposals_for_observing"]:
        return {"proof_status": "observing", "sample_quality": "insufficient",
                "decision_allowed": False, "recommendation_status": "human_review_only"}

    return {"proof_status": "insufficient", "sample_quality": "insufficient",
            "decision_allowed": False, "recommendation_status": "human_review_only"}


def summarize_strategy_blockers(metrics: dict, a5_complete: bool = False) -> list:
    blockers = []
    if not a5_complete:
        blockers.append(f"A-5 observation incomplete (ends {A5_END_DATE})")
    closed = metrics.get("closed_count", 0)
    proposals = metrics.get("proposal_count", 0)
    if closed < 5:
        blockers.append(f"only {closed} closed trades (min 5 for any conclusion)")
    elif closed < 20:
        blockers.append(f"only {closed} closed trades (min 20 for review)")
    if proposals < 10:
        blockers.append(f"only {proposals} proposals (min 10 for observing)")
    linkage = metrics.get("lifecycle_linkage_rate", 0)
    if linkage < 0.9:
        blockers.append(f"lifecycle linkage {linkage:.0%} (min 90%)")
    return blockers


def is_decision_allowed(metrics: dict, a5_complete: bool = False) -> bool:
    return False  # Always human_review_only — never auto-decide


def is_review_ready(metrics: dict, a5_complete: bool = False) -> bool:
    if not a5_complete:
        return False
    return metrics.get("closed_count", 0) >= THRESHOLDS["min_closed_trades_for_review"]
