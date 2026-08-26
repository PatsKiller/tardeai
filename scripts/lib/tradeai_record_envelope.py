"""TradeAIRecordEnvelope@v1 — common provenance for persisted intelligence."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "TradeAIRecordEnvelope@v1"
ENTITY_TYPES = (
    "SECURITY", "ISSUER", "LISTING", "TICKER",
    "PORTFOLIO", "PORTFOLIO_CASH",
    "SECTOR", "INDUSTRY", "SUBINDUSTRY", "THEME",
    "CATALYST", "CALENDAR_EVENT", "MACRO_EVENT",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def entity_ref(*, entity_type: str, guid: str | None = None, semantic_subject: str | None = None,
               relationship: str = "subject") -> dict[str, Any]:
    et = str(entity_type or "").upper()
    if et not in ENTITY_TYPES:
        et = "OTHER"
    if et == "SECURITY" and not guid:
        raise ValueError("security_guid_required")
    return {
        "entity_type": et,
        "entity_guid": guid,
        "semantic_subject": semantic_subject or (f"{et}:{guid}" if guid else None),
        "relationship": relationship,
        "ticker_guid_is_not_security": et != "SECURITY",
    }


def envelope(
    payload: dict[str, Any],
    *,
    record_id: str | None = None,
    entity_refs: list[dict[str, Any]] | None = None,
    semantic_key: str | None = None,
    generation_id: str | None = None,
    lineage_id: str | None = None,
    producer: str = "unknown",
    source: str = "unknown",
    source_commit: str | None = None,
    environment: str = "PRODUCTION",
    synthetic: bool = False,
    valid_at: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    produced = _now()
    body = {
        "schema": SCHEMA,
        "record_id": record_id or _sha({"p": producer, "t": produced, "k": semantic_key}),
        "entity_refs": entity_refs or [],
        "semantic_key": semantic_key,
        "generation_id": generation_id,
        "lineage_id": lineage_id,
        "valid_at": valid_at or produced,
        "observed_at": observed_at or produced,
        "produced_at": produced,
        "producer": producer,
        "source": source,
        "source_commit": source_commit,
        "environment": environment,
        "synthetic": bool(synthetic),
        "authority": AUTHORITY,
        "data_quality": "OK",
        "content_hash": _sha(payload),
        "supersedes": None,
        "superseded_by": None,
        "payload": payload,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
    return body
