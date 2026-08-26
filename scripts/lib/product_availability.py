"""Standard CIO / advisory product availability reasons.

Never use the generic phrase "no product on disk".
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

AVAILABLE = "AVAILABLE"

UNAVAILABLE_REASONS = (
    "PRODUCER_NOT_RUN",
    "STALE",
    "INVALID_SCHEMA",
    "WRONG_RUNTIME_SHA",
    "INELIGIBLE_ORIGIN",
    "SOURCE_UNAVAILABLE",
    "DATA_CONFLICT",
    "MISSING_REQUIRED_INPUT",
    "QUARANTINED",
)

# Legacy aliases → canonical reasons.
_ALIASES = {
    "MISSING": "PRODUCER_NOT_RUN",
    "MISSING_DEPENDENCY": "MISSING_REQUIRED_INPUT",
    "WRONG_SOURCE_PIN": "WRONG_RUNTIME_SHA",
    "INELIGIBLE": "INELIGIBLE_ORIGIN",
    "PRODUCER_NOT_RUN_OR_STALE_FILENAME": "PRODUCER_NOT_RUN",
    "no_current_product": "PRODUCER_NOT_RUN",
    "no product on disk": "PRODUCER_NOT_RUN",
}


def canonicalize_reason(reason: str | None) -> str:
    raw = str(reason or "").strip()
    if raw == AVAILABLE:
        return AVAILABLE
    mapped = _ALIASES.get(raw, raw)
    if mapped in UNAVAILABLE_REASONS:
        return mapped
    if not mapped:
        return "PRODUCER_NOT_RUN"
    # Unknown tokens still become a named reason — never a generic disk phrase.
    return "PRODUCER_NOT_RUN"


def availability_payload(
    *,
    reason: str | None,
    detail: str | None = None,
    path: str | None = None,
    last_valid_product: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = canonicalize_reason(reason)
    available = status == AVAILABLE
    out: dict[str, Any] = {
        "available": available,
        "status": status,
        "reason": None if available else status,
        "detail": detail,
        "path": path,
        "last_valid_product": last_valid_product,
        "operator_data_quality": "OK" if available else (
            "DEGRADED" if status in {"INVALID_SCHEMA", "STALE", "DATA_CONFLICT", "SOURCE_UNAVAILABLE"} else "UNAVAILABLE"
        ),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "note": "Never use ambiguous available=false without an enumerated reason.",
    }
    if extra:
        out.update(extra)
    return out
