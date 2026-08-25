"""Source-only autonomous situation detection. No trading.

A verified-material situation may become OPERATOR_NOTIFICATION_CANDIDATE.
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
OUT_NOTIFY = "OPERATOR_NOTIFICATION_CANDIDATE"
OUT_NONE = "NO_SITUATION"

SITUATIONS = (
    "cash_outside_policy",
    "allocation_drift",
    "thesis_deterioration",
    "market_regime_change",
    "seasonal_opportunity",
    "catalyst_event",
    "research_gap_resolution",
    "operator_feedback",
    "outcome_maturation",
)


def detect(*, cash: float | None, policy_cash_band: tuple[float, float] | None, cognition: dict[str, Any] | None = None) -> dict[str, Any]:
    hits: list[str] = []
    if cash is not None and policy_cash_band:
        lo, hi = policy_cash_band
        if cash < lo or cash > hi:
            hits.append("cash_outside_policy")
    pack = cognition or {}
    if pack.get("portfolio_call") == "THESIS_REVIEW_REQUIRED":
        hits.append("thesis_deterioration")
    if pack.get("open_gap_count"):
        hits.append("research_gap_resolution")
    return {
        "schema": "ProactiveCIODetection@v1",
        "situations": hits,
        "call": OUT_NOTIFY if hits else OUT_NONE,
        "authority": AUTHORITY,
        "financial_action": False,
        "trading": False,
        "memory_behavior_influence": 0,
    }
