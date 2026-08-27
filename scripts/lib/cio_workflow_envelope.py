"""CIOWorkflowEnvelope@v1 — durable stage projection for a CIO workflow.

READ_ONLY_ADVISORY. MBI=0. Never mints security_guid from ticker text.
This module is schema + merge only; persistence lives in cio_lineage.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

SCHEMA = "CIOWorkflowEnvelope@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
MEMORY_BEHAVIOR_INFLUENCE = 0

STAGE_KEYS = ("research", "specialist", "cio", "notification", "checkpoint")
STAGE_NOT_REQUIRED = "NOT_REQUIRED"
STAGE_SUPPRESSED = "SUPPRESSED"
STAGE_UNAVAILABLE = "UNAVAILABLE"
STAGE_FAILED = "FAILED"
STAGE_NOT_YET_CREATED = "NOT_YET_CREATED"
STAGE_COMPLETED = "COMPLETED"
STAGE_STATUSES = frozenset({
    STAGE_NOT_REQUIRED,
    STAGE_SUPPRESSED,
    STAGE_UNAVAILABLE,
    STAGE_FAILED,
    STAGE_NOT_YET_CREATED,
    STAGE_COMPLETED,
})

NOTIFICATION_IMMEDIATE = "IMMEDIATE"
NOTIFICATION_DIGEST = "DIGEST"
NOTIFICATION_COMMAND_CENTER_ONLY = "COMMAND_CENTER_ONLY"
NOTIFICATION_SUPPRESSED = "SUPPRESSED"
NOTIFICATION_NOT_REQUIRED = "NOT_REQUIRED"
NOTIFICATION_FAILED = "FAILED"
NOTIFICATION_CLASSIFICATIONS = frozenset({
    NOTIFICATION_IMMEDIATE,
    NOTIFICATION_DIGEST,
    NOTIFICATION_COMMAND_CENTER_ONLY,
    NOTIFICATION_SUPPRESSED,
    NOTIFICATION_NOT_REQUIRED,
    NOTIFICATION_FAILED,
})

SKIP_NON_MATERIAL = "NON_MATERIAL"
SKIP_NO_CIO_REQUIRED = "NO_CIO_REQUIRED"
SKIP_UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
CIO_SKIP_REASONS = frozenset({
    SKIP_NON_MATERIAL,
    SKIP_NO_CIO_REQUIRED,
    SKIP_UPSTREAM_UNAVAILABLE,
})

ENVELOPE_REQUIRED_KEYS = (
    "workflow_id",
    "subject_id",
    "entity_type",
    "subject_guid",
    "event_id",
    "context_id",
    "research_request_id",
    "research_artifact_id",
    "specialist_dispatch_id",
    "specialist_artifact_id",
    "cio_generation_id",
    "notification_id",
    "notification_classification",
    "suppression_reason",
    "checkpoint_id",
    "created_at",
    "updated_at",
    "source_sha",
    "authority",
    "memory_behavior_influence",
    "schema",
    "stage_status",
)

# Timestamps must not fork semantic identity on rewrite/replay.
ENVELOPE_VOLATILE_KEYS = frozenset({
    "recorded_at",
    "semantic_key",
    "created_at",
    "updated_at",
})

_STORAGE_KEYS = frozenset({"record_type", "semantic_key", "recorded_at"})

_NULLABLE_IDENTITY = (
    "subject_id",
    "subject_guid",
    "event_id",
    "context_id",
    "research_request_id",
    "research_artifact_id",
    "specialist_dispatch_id",
    "specialist_artifact_id",
    "cio_generation_id",
    "cio_skip_reason",
    "notification_id",
    "notification_classification",
    "suppression_reason",
    "checkpoint_id",
    "source_sha",
)


def default_stage_status() -> dict[str, str]:
    return {key: STAGE_NOT_YET_CREATED for key in STAGE_KEYS}


def _blank_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def coerce_stage_status(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if raw in STAGE_STATUSES:
        return raw
    return STAGE_NOT_YET_CREATED


def coerce_notification_classification(value: Any) -> str | None:
    raw = str(value or "").strip().upper()
    if not raw:
        return None
    if raw in NOTIFICATION_CLASSIFICATIONS:
        return raw
    return NOTIFICATION_FAILED


def coerce_skip_reason(value: Any) -> str | None:
    raw = str(value or "").strip().upper()
    if not raw:
        return None
    if raw in CIO_SKIP_REASONS:
        return raw
    return raw


def identity_from_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Stable envelope identity. Never mints security_guid from ticker."""
    src = dict(payload or {})
    guid_raw = src.get("subject_guid")
    if guid_raw is None:
        guid_raw = src.get("security_guid")
    guid = _blank_to_none(guid_raw)
    guid_s = str(guid).strip() if guid is not None else None
    if not guid_s:
        guid_s = None
    symbol = str(src.get("symbol") or "").strip() or None
    entity_type = _blank_to_none(src.get("entity_type"))
    if entity_type:
        entity_type_s = str(entity_type)
    elif guid_s:
        entity_type_s = "SECURITY"
    else:
        entity_type_s = "UNRESOLVED"
    subject_id = _blank_to_none(src.get("subject_id"))
    if subject_id:
        subject_id_s = str(subject_id)
    elif guid_s:
        subject_id_s = guid_s
    else:
        subject_id_s = symbol
    return {
        "subject_guid": guid_s,
        "entity_type": entity_type_s,
        "subject_id": subject_id_s,
        "never_minted_security_guid": True,
    }


def notification_stage_for(classification: str | None) -> str:
    klass = coerce_notification_classification(classification)
    if klass in {NOTIFICATION_IMMEDIATE, NOTIFICATION_DIGEST, NOTIFICATION_COMMAND_CENTER_ONLY}:
        return STAGE_COMPLETED
    if klass == NOTIFICATION_SUPPRESSED:
        return STAGE_SUPPRESSED
    if klass == NOTIFICATION_NOT_REQUIRED:
        return STAGE_NOT_REQUIRED
    if klass == NOTIFICATION_FAILED:
        return STAGE_FAILED
    return STAGE_NOT_YET_CREATED


def cio_stage_for_skip(reason: str | None) -> str:
    mapped = coerce_skip_reason(reason)
    if mapped == SKIP_UPSTREAM_UNAVAILABLE:
        return STAGE_UNAVAILABLE
    if mapped in {SKIP_NO_CIO_REQUIRED, SKIP_NON_MATERIAL}:
        return STAGE_NOT_REQUIRED
    return STAGE_NOT_REQUIRED


def is_complete_to_checkpoint(envelope: Mapping[str, Any] | None) -> bool:
    """True only when a real checkpoint exists and notification is not left ambiguous."""
    env = dict(envelope or {})
    ss = env.get("stage_status") if isinstance(env.get("stage_status"), dict) else {}
    if ss.get("checkpoint") != STAGE_COMPLETED:
        return False
    if not _blank_to_none(env.get("checkpoint_id")):
        return False
    if ss.get("notification") in {None, STAGE_NOT_YET_CREATED}:
        return False
    return True


def notification_is_ambiguous(envelope: Mapping[str, Any] | None) -> bool:
    env = dict(envelope or {})
    ss = env.get("stage_status") if isinstance(env.get("stage_status"), dict) else {}
    return ss.get("notification", STAGE_NOT_YET_CREATED) == STAGE_NOT_YET_CREATED


def freeze_governance(envelope: dict[str, Any]) -> dict[str, Any]:
    envelope["schema"] = SCHEMA
    envelope["authority"] = AUTHORITY
    envelope["memory_behavior_influence"] = MBI
    envelope["complete_to_checkpoint"] = is_complete_to_checkpoint(envelope)
    envelope["never_minted_security_guid"] = True
    return envelope


def empty_envelope(workflow_id: str, *, created_at: str | None = None) -> dict[str, Any]:
    return {
        "workflow_id": str(workflow_id),
        "subject_id": None,
        "entity_type": "UNRESOLVED",
        "subject_guid": None,
        "event_id": None,
        "context_id": None,
        "research_request_id": None,
        "research_artifact_id": None,
        "specialist_dispatch_id": None,
        "specialist_artifact_id": None,
        "cio_generation_id": None,
        "cio_skip_reason": None,
        "notification_id": None,
        "notification_classification": None,
        "suppression_reason": None,
        "checkpoint_id": None,
        "created_at": created_at,
        "updated_at": created_at,
        "source_sha": None,
        "never_minted_security_guid": True,
        "stage_status": default_stage_status(),
        "complete_to_checkpoint": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "schema": SCHEMA,
    }


def _merge_stage_status(base: Mapping[str, Any] | None, updates: Any) -> dict[str, str]:
    out = default_stage_status()
    if isinstance(base, Mapping):
        for key in STAGE_KEYS:
            if key in base and base[key] is not None:
                out[key] = coerce_stage_status(base[key])
    if isinstance(updates, Mapping):
        for key in STAGE_KEYS:
            if key in updates and updates[key] is not None:
                out[key] = coerce_stage_status(updates[key])
    return out


def merge_envelope(
    existing: Mapping[str, Any] | None,
    updates: Mapping[str, Any] | None = None,
    *,
    updated_at: str | None = None,
    created_at: str | None = None,
    unset: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Merge updates onto an envelope. None does not wipe an existing value unless unset."""
    incoming = dict(updates or {})
    stage_updates = incoming.pop("stage_status", None)
    incoming.pop("complete_to_checkpoint", None)
    incoming.pop("schema", None)
    incoming.pop("authority", None)
    incoming.pop("memory_behavior_influence", None)

    wf = str(
        incoming.get("workflow_id")
        or (existing or {}).get("workflow_id")
        or ""
    )
    base_src = {k: v for k, v in dict(existing or {}).items() if k not in _STORAGE_KEYS}
    out = empty_envelope(wf, created_at=created_at or base_src.get("created_at"))
    for key, value in base_src.items():
        if key in {"workflow_id", "stage_status"}:
            continue
        out[key] = value
    out["stage_status"] = _merge_stage_status(base_src.get("stage_status"), None)
    out["workflow_id"] = wf

    for key, value in incoming.items():
        if key == "workflow_id":
            continue
        if value is None and key in _NULLABLE_IDENTITY and out.get(key) is not None:
            # None in an update does not wipe a previously recorded identifier.
            continue
        if value is None and key not in _NULLABLE_IDENTITY and key not in {"entity_type"}:
            continue
        if value is None and key == "entity_type":
            continue
        out[key] = value

    out["stage_status"] = _merge_stage_status(out.get("stage_status"), stage_updates)
    for key in unset or ():
        if key == "stage_status":
            continue
        out[key] = None
    if created_at and not out.get("created_at"):
        out["created_at"] = created_at
    if updated_at:
        out["updated_at"] = updated_at
    for key in ENVELOPE_REQUIRED_KEYS:
        if key == "stage_status":
            out.setdefault(key, default_stage_status())
        else:
            out.setdefault(key, None)
    return freeze_governance(out)


def new_envelope(workflow_id: str, *, created_at: str | None = None, **fields: Any) -> dict[str, Any]:
    return merge_envelope(
        empty_envelope(str(workflow_id), created_at=created_at),
        fields,
        updated_at=created_at,
        created_at=created_at,
    )


def semantic_payload(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Content used for upsert idempotency (timestamps excluded)."""
    return {k: envelope.get(k) for k in envelope if k not in ENVELOPE_VOLATILE_KEYS}


def missing_required_keys(envelope: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(k for k in ENVELOPE_REQUIRED_KEYS if k not in envelope)


def derived_event_id(payload: Mapping[str, Any] | None, *, event_kind: str) -> Any:
    """Canonical event id for a payload, or None.

    `event_id` has been read here since the envelope landed and populated by
    nothing, which is why the research and CIO arcs have no key to join on. This
    derives one when the caller did not supply it. Local import keeps this module
    schema-and-merge-only, and any failure degrades to None rather than breaking
    a lineage projection that is only ever an audit view.
    """
    try:
        from scripts.lib.cio_canonical_identity import event_id_for
        return event_id_for(payload, event_kind=event_kind)
    except Exception:
        return None


def hermes_request_fields(request: Mapping[str, Any]) -> dict[str, Any]:
    ident = identity_from_payload(request)
    rid = _blank_to_none(request.get("research_id"))
    fields: dict[str, Any] = {
        "research_request_id": str(rid) if rid is not None else None,
        "specialist_dispatch_id": _blank_to_none(request.get("specialist_dispatch_id")),
        "event_id": _blank_to_none(request.get("event_id"))
                    or derived_event_id(request, event_kind="RESEARCH_REQUEST"),
        "context_id": _blank_to_none(request.get("context_id")),
        "source_sha": _blank_to_none(request.get("source_sha")),
        "subject_id": ident["subject_id"],
        "entity_type": ident["entity_type"],
        "subject_guid": ident["subject_guid"],
        "never_minted_security_guid": True,
        "stage_status": {"research": STAGE_NOT_YET_CREATED, "specialist": STAGE_NOT_YET_CREATED},
    }
    return fields


def hermes_completion_fields(request: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    ident = identity_from_payload({**dict(request), **dict(result)})
    rid = _blank_to_none(result.get("research_id") or request.get("research_id"))
    result_id = _blank_to_none(result.get("result_id"))
    result_id_s = str(result_id) if result_id is not None else None
    return {
        "research_request_id": str(rid) if rid is not None else None,
        "research_artifact_id": result_id_s,
        # Honest: Hermes result_id, not a specialist-office artifact.
        "specialist_artifact_id": result_id_s,
        "specialist_dispatch_id": _blank_to_none(
            result.get("specialist_dispatch_id") or request.get("specialist_dispatch_id")
        ),
        # Derived from the REQUEST, never the result: the completion must land on
        # the same event as the request that opened it, and only the request is
        # guaranteed to carry the originating timestamp.
        "event_id": _blank_to_none(result.get("event_id") or request.get("event_id"))
                    or derived_event_id(request, event_kind="RESEARCH_REQUEST"),
        "context_id": _blank_to_none(result.get("context_id") or request.get("context_id")),
        "source_sha": _blank_to_none(result.get("source_sha") or request.get("source_sha")),
        "subject_id": ident["subject_id"],
        "entity_type": ident["entity_type"],
        "subject_guid": ident["subject_guid"],
        "never_minted_security_guid": True,
        "stage_status": {
            "research": STAGE_COMPLETED,
            "specialist": STAGE_COMPLETED if result_id_s else STAGE_NOT_YET_CREATED,
        },
    }
