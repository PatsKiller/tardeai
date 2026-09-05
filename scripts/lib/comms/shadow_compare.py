"""SHADOW mode comparison helper (Phase 11).

Compares legacy routing decisions against gateway CommunicationEvent
fields without claiming delivery ownership. Memory-only observation log
for local/CI evidence before CANARY/ACTIVE.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

_lock = threading.Lock()
_OBSERVATIONS: list[dict[str, Any]] = []

COMPARE_FIELDS = ("subject_key", "severity", "route_intent")


def _norm_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _norm_channels(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            text = _norm_str(item)
            if text:
                out.append(text)
        return sorted(set(out))
    text = _norm_str(value)
    return [text] if text else []


def extract_route_intent(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize route intent from legacy decision or gateway event dicts.

    Prefers explicit ``route_intent``; otherwise composes from
    ``channels`` / ``channel`` + ``intended_action`` / ``action`` / ``route``.
    """
    if not isinstance(payload, dict):
        return {"channels": [], "intended_action": None}

    explicit = payload.get("route_intent")
    if isinstance(explicit, dict):
        return {
            "channels": _norm_channels(
                explicit.get("channels", explicit.get("channel"))
            ),
            "intended_action": _norm_str(
                explicit.get("intended_action")
                or explicit.get("action")
                or explicit.get("route")
            ),
        }
    if isinstance(explicit, str) and explicit.strip():
        return {"channels": [], "intended_action": explicit.strip()}

    channels = _norm_channels(payload.get("channels", payload.get("channel")))
    action = _norm_str(
        payload.get("intended_action")
        or payload.get("action")
        or payload.get("route")
    )
    delivery_policy = payload.get("delivery_policy")
    if not channels and isinstance(delivery_policy, dict):
        channels = _norm_channels(
            delivery_policy.get("channels", delivery_policy.get("channel"))
        )
        if action is None:
            action = _norm_str(
                delivery_policy.get("intended_action")
                or delivery_policy.get("action")
            )
    return {"channels": channels, "intended_action": action}


def _extract_field(payload: dict[str, Any], field: str) -> Any:
    if field == "route_intent":
        return extract_route_intent(payload)
    if field == "subject_key":
        return _norm_str(payload.get("subject_key"))
    if field == "severity":
        return _norm_str(payload.get("severity")) or "info"
    return payload.get(field)


def compare_legacy_vs_gateway(
    legacy_decision: dict,
    gateway_event: dict,
) -> dict:
    """Compare legacy decision vs gateway event on subject_key, severity, route intent.

    Returns a dict with per-field match/mismatch, overall ``match`` bool,
    and the normalized values used for the comparison.
    """
    legacy = legacy_decision if isinstance(legacy_decision, dict) else {}
    gateway = gateway_event if isinstance(gateway_event, dict) else {}

    fields: dict[str, Any] = {}
    mismatches: list[str] = []
    matches: list[str] = []

    for field in COMPARE_FIELDS:
        legacy_val = _extract_field(legacy, field)
        gateway_val = _extract_field(gateway, field)
        equal = legacy_val == gateway_val
        fields[field] = {
            "match": equal,
            "legacy": legacy_val,
            "gateway": gateway_val,
        }
        if equal:
            matches.append(field)
        else:
            mismatches.append(field)

    return {
        "match": len(mismatches) == 0,
        "matches": matches,
        "mismatches": mismatches,
        "fields": fields,
        "compared_at": datetime.now(timezone.utc).isoformat(),
    }


def record_shadow_observation(
    *,
    legacy_decision: dict | None = None,
    gateway_event: dict | None = None,
    comparison: dict | None = None,
    producer: str | None = None,
    note: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one SHADOW observation to the in-process memory log."""
    legacy = legacy_decision if isinstance(legacy_decision, dict) else {}
    gateway = gateway_event if isinstance(gateway_event, dict) else {}
    result = comparison if isinstance(comparison, dict) else compare_legacy_vs_gateway(
        legacy, gateway
    )
    row: dict[str, Any] = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "producer": producer,
        "note": note,
        "match": bool(result.get("match")),
        "mismatches": list(result.get("mismatches") or []),
        "matches": list(result.get("matches") or []),
        "comparison": result,
        "legacy_subject_key": _extract_field(legacy, "subject_key"),
        "gateway_subject_key": _extract_field(gateway, "subject_key"),
        "gateway_event_id": gateway.get("event_id"),
        "meta": dict(meta or {}),
    }
    with _lock:
        _OBSERVATIONS.append(row)
    return dict(row)


def shadow_report() -> dict:
    """Summarize in-memory SHADOW observations for evidence packets."""
    with _lock:
        rows = list(_OBSERVATIONS)
    total = len(rows)
    matched = sum(1 for r in rows if r.get("match"))
    mismatched = total - matched
    by_field: dict[str, int] = {f: 0 for f in COMPARE_FIELDS}
    for row in rows:
        for field in row.get("mismatches") or []:
            if field in by_field:
                by_field[field] += 1
    return {
        "total_observations": total,
        "matched": matched,
        "mismatched": mismatched,
        "match_rate": (matched / total) if total else None,
        "mismatch_counts_by_field": by_field,
        "observations": rows,
        "delivery_owned": False,
        "mode_note": "SHADOW compare only; does not claim gateway delivery ownership",
    }


def reset_shadow_observations() -> None:
    """Clear the in-process SHADOW observation log (tests / local runs)."""
    with _lock:
        _OBSERVATIONS.clear()
