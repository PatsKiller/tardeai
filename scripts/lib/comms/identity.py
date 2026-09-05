"""Identity helpers for CommunicationEvent."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any


def new_event_id() -> str:
    """Mint a sortable global event_id (UUIDv7 when available)."""
    gen = getattr(uuid, "uuid7", None)
    if callable(gen):
        return str(gen())
    # Fallback: time-sortable-ish uuid4 hybrid for older interpreters.
    return str(uuid.uuid4())


def _stable_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def idempotency_key_for(
    *,
    producer: str,
    event_type: str,
    subject_key: str,
    intended_action: str,
    entity_refs: dict[str, Any] | None = None,
    observation_version: str = "1",
) -> str:
    """Deterministic idempotency key across process restarts.

    Separate from event_id. Retries of the same logical communication must collide
    here; distinct observations must not.
    """
    material = {
        "producer": producer,
        "event_type": event_type,
        "subject_key": subject_key,
        "intended_action": intended_action,
        "entity_refs": entity_refs or {},
        "observation_version": observation_version,
    }
    digest = hashlib.sha256(_stable_dumps(material).encode("utf-8")).hexdigest()
    return f"idem_{digest}"


def content_hash_for(*, sanitized_body: str | None, protected_facts: dict[str, Any], short_summary: str | None) -> str:
    material = {
        "sanitized_body": sanitized_body or "",
        "protected_facts": protected_facts or {},
        "short_summary": short_summary or "",
    }
    return hashlib.sha256(_stable_dumps(material).encode("utf-8")).hexdigest()


def protected_facts_hash_for(protected_facts: dict[str, Any] | None) -> str:
    return hashlib.sha256(_stable_dumps(protected_facts or {}).encode("utf-8")).hexdigest()
