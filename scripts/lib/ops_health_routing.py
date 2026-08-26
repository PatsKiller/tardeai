"""Route machine telemetry away from investment intelligence."""
from __future__ import annotations

import re
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
OPS_PATTERNS = (
    r"zero_non_error_24h",
    r"COST_CONFIGURATION_INVALID",
    r"RAW-store health",
    r"hermes_rank_surge",
    r"deepseek",
    r"lane health",
    r"provider.?cost",
    r"scheduler mismatch",
)


def classify_message(text: str) -> dict[str, Any]:
    t = text or ""
    ops = any(re.search(p, t, re.I) for p in OPS_PATTERNS)
    if ops:
        return {
            "channel": "OPS_HEALTH",
            "is_investment_intelligence": False,
            "operator_alert": "only_if_cio_capability_degraded",
            "human": (
                "CIO DATA DEGRADATION — research enrichment unavailable. "
                "Existing portfolio facts remain available. No investment decision "
                "is being changed because of this failure. Action: none; system repair required."
            ) if re.search(r"COST_CONFIGURATION_INVALID|zero_non_error", t, re.I) else (
                "Operations telemetry — not an investment recommendation."
            ),
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
            "financial_action": False,
        }
    return {
        "channel": "CIO_INTELLIGENCE",
        "is_investment_intelligence": True,
        "authority": AUTHORITY,
        "financial_action": False,
    }
