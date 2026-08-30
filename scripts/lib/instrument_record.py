"""InstrumentRecord@v1 canonical projection.

This is a read/write adapter over the existing watchlist/instrument row.  It
does not create a second source of truth: callers provide the canonical row
and linked evidence, and this module normalizes the one operator-facing
record consumed by Command Center and notification policy.
"""
from __future__ import annotations

from typing import Any, Mapping

SCHEMA = "InstrumentRecord@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
QUALITY = {"AVAILABLE", "PARTIAL", "STALE", "INVALID_SCHEMA", "UNAVAILABLE", "LEGACY"}


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def build_instrument_record(
    row: Mapping[str, Any],
    *,
    identity: Mapping[str, Any] | None = None,
    research: Mapping[str, Any] | None = None,
    artifacts: list[Mapping[str, Any]] | None = None,
    operator_turns: list[Mapping[str, Any]] | None = None,
    lessons: list[Mapping[str, Any]] | None = None,
    workflow_id: str | None = None,
    data_quality: str | None = None,
) -> dict[str, Any]:
    """Normalize existing sources without inventing identity or lineage."""
    r = dict(row or {})
    ident = dict(identity or {})
    research = dict(research or {})
    arts = [dict(a) for a in (artifacts or []) if isinstance(a, Mapping)]
    turns = [dict(t) for t in (operator_turns or []) if isinstance(t, Mapping)]
    ls = [dict(x) for x in (lessons or []) if isinstance(x, Mapping)]
    symbol = str(_first(r.get("symbol"), ident.get("symbol")) or "").upper() or None
    entity_id = _first(r.get("canonical_entity_id"), ident.get("canonical_entity_id"), ident.get("security_guid"), ident.get("issuer_guid"))
    record = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "canonical_entity_id": entity_id,
        "security_id": _first(r.get("security_id"), ident.get("security_guid")),
        "issuer_guid": ident.get("issuer_guid"),
        "symbol": symbol,
        "sector_id": _first(r.get("sector_id"), ident.get("sector_id")),
        "industry_id": _first(r.get("industry_id"), ident.get("industry_id")),
        "watch": r.get("watch", r.get("watchlisted")),
        "exit": r.get("exit", r.get("exit_state")),
        "thesis": _first(r.get("thesis"), r.get("deterministic_thesis"), r.get("recommendation")),
        "cc_narrative": _first(r.get("cc_narrative"), r.get("synthesis_narrative"), r.get("agent_narrative")),
        "last_event": _first(r.get("last_event"), r.get("last_event_id")),
        "last_price_hash": r.get("last_price_hash"),
        "research": research,
        "research_ids": _list(_first(r.get("research_ids"), research.get("research_ids"), research.get("ids"))),
        "artifact_ids": _list(_first(r.get("artifact_ids"), [a.get("artifact_id") for a in arts if a.get("artifact_id")])),
        "operator_turns": turns,
        "operator_turn_ids": _list(_first(r.get("operator_turn_ids"), [t.get("turn_id") or t.get("feedback_id") for t in turns if t.get("turn_id") or t.get("feedback_id")])),
        "lessons": ls,
        "lesson_ids": _list(_first(r.get("lesson_ids"), [x.get("lesson_id") for x in ls if x.get("lesson_id")])),
        "analyst": r.get("analyst"),
        "earnings_next": _first(r.get("earnings_next"), r.get("next_earnings")),
        "next_eligible_at": _first(r.get("next_eligible_at"), research.get("next_eligible_at")),
        "notify_priority": _first(r.get("notify_priority"), r.get("notification_priority"), r.get("urgency")),
        "workflow_id": _first(workflow_id, r.get("workflow_id")),
        "updated_at": _first(r.get("updated_at"), r.get("last_seen_at")),
        "data_quality": data_quality or ("LEGACY" if not entity_id else "AVAILABLE"),
    }
    if record["data_quality"] not in QUALITY:
        record["data_quality"] = "INVALID_SCHEMA"
    # A workflow is not inferred from a ticker or timestamp.
    record["lineage_complete"] = bool(record["workflow_id"] and (record["research_ids"] or record["artifact_ids"]))
    return record


def validate_instrument_record(record: Mapping[str, Any]) -> list[str]:
    """Return contract violations; callers decide whether to reject or degrade."""
    errors: list[str] = []
    if record.get("schema") != SCHEMA:
        errors.append("schema")
    if not record.get("symbol"):
        errors.append("symbol")
    if record.get("data_quality") not in QUALITY:
        errors.append("data_quality")
    if record.get("canonical_entity_id") is None and record.get("security_id") is None:
        errors.append("canonical_identity_missing")
    for key in ("research_ids", "artifact_ids", "operator_turn_ids", "lesson_ids"):
        if not isinstance(record.get(key), list):
            errors.append(key)
    return errors


def notification_crossed(previous: Any, current: Any, *, ordering: tuple[str, ...] = ("LOW", "NORMAL", "HIGH", "CRITICAL")) -> bool:
    """True only when priority crosses upward; equal/replayed values suppress."""
    if previous is None or current is None:
        return previous != current and current is not None
    try:
        return ordering.index(str(current).upper()) > ordering.index(str(previous).upper())
    except ValueError:
        return str(previous) != str(current)


def persist_instrument_record(record: Mapping[str, Any]) -> bool:
    """Persist through db_adapter when available; return False on unavailable DB."""
    symbol = str(record.get("symbol") or "").strip().upper()
    if not symbol:
        return False
    try:
        from scripts import db_adapter
        return bool(db_adapter.save_instrument_record(symbol, dict(record)))
    except Exception:
        return False
