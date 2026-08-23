"""Deterministic admission checks for automatic research inputs and outputs."""
from __future__ import annotations

import re
from typing import Any

SCHEMA = "ResearchDataQualityGate@v1"
_ZERO_PE = re.compile(
    r"\b(?:p\s*/\s*e|pe)(?:\s+ratio)?\s*(?:is|of|[:=])?\s*0(?:\.0+)?\b",
    re.IGNORECASE,
)
_ZERO_52W_RANGE = re.compile(
    r"\b52[- ]week\s+(?:range|low\s*/\s*high|high\s*/\s*low)"
    r"[^\n.;]{0,50}?\$?0(?:\.0+)?\s*(?:-|to|through|\u2013|\u2014)\s*\$?0(?:\.0+)?\b",
    re.IGNORECASE,
)


def assess_prompt_context(context: dict[str, Any]) -> dict[str, Any]:
    market = dict(context.get("deterministic_current_data") or {})
    reasons: list[str] = []
    for key in ("price", "atr", "avg_vol_m"):
        value = market.get(key)
        if value is not None:
            try:
                if float(value) <= 0:
                    reasons.append(f"invalid_{key}")
            except (TypeError, ValueError):
                reasons.append(f"non_numeric_{key}")
    high = market.get("week52_high_pct")
    low = market.get("week52_low_pct")
    try:
        if high is not None and low is not None and float(high) == 0 and float(low) == 0:
            reasons.append("invalid_zero_52week_range")
    except (TypeError, ValueError):
        reasons.append("non_numeric_52week_range")
    return {
        "schema": SCHEMA,
        "status": "BLOCK" if reasons else "PASS",
        "reason_codes": sorted(set(reasons)),
        "provider_call_allowed": not reasons,
        "authority": "READ_ONLY_ADVISORY",
    }


def validate_research_output(text: str) -> dict[str, Any]:
    body = str(text or "")
    reasons = []
    if _ZERO_PE.search(body):
        reasons.append("placeholder_zero_pe")
    if _ZERO_52W_RANGE.search(body):
        reasons.append("placeholder_zero_52week_range")
    return {
        "schema": SCHEMA,
        "status": "REJECT" if reasons else "PASS",
        "reason_codes": reasons,
        "accepted": not reasons,
        "instruction": "Use DATA_UNAVAILABLE for missing facts; never convert missing values to zero.",
        "authority": "READ_ONLY_ADVISORY",
    }
