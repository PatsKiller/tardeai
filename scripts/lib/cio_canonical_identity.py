"""CANONICAL ENTITY / IDENTITY — one real event, one id, derivable from both arcs.

The operator's pipeline diagram puts a CANONICAL ENTITY / IDENTITY node directly
after the event sources and before materiality. It had no implementation: no code
carried that name, the `identity.registry` store did not exist on disk, and every
lineage envelope in production read `entity_type: UNRESOLVED`.

The cost of that gap is measured in
`docs/audits/CIO_PIPELINE_DIAGRAM_VERIFICATION_2026-08-27.md`: lineage forks into
two arcs that never join, so `is_complete_to_checkpoint` was false for 94/94
workflows and had never once been true.

    arc A  research + specialist + checkpoint   workflow_id = "wf_" + digest(...)
    arc B  cio + notification                   workflow_id = the CIO run UUID

This module supplies the missing join: a deterministic `event_id` that either arc
can compute from what it already holds, with no shared mutable state, no lookup
race, and no ordering requirement between the two.

**Deterministic, not minted-and-stored.** A registry that hands out ids needs both
arcs to agree who asks first. Deriving the id from the event's own identity means
each arc computes the same value independently and idempotently. The registry
below therefore *records* what was derived for observability; it is never the
source of the id, so losing it cannot break the join.

**Never mints a security_guid from a ticker.** `identity_from_payload` in
cio_workflow_envelope is deliberate about this and so is this module: a symbol is
a subject_id, not a security identity. `entity_type` stays UNRESOLVED when the
inputs genuinely do not resolve, because a confident wrong entity is worse than
an honest unresolved one.

**Time bucketing.** Two arcs observe the same event at different wall-clock times,
so an id keyed on an exact timestamp would never match. Events are bucketed to a
UTC hour by default: long enough for a research request and the run reacting to it
to land in the same bucket, short enough that a daily cadence does not collapse
distinct events into one. `bucket_hours` is a parameter because that trade-off is
a property of the pipeline's cadence, not a universal constant.

AUTHORITY: READ_ONLY_ADVISORY. Pure derivation plus an append-only observability
record. This mints no investment decision and grants no authority.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CanonicalEventIdentity@v1"
REGISTRY_SCHEMA = "IdentityRegistry@v1"

EVENT_PREFIX = "evt_"
WORKFLOW_PREFIX = "wf_"
DEFAULT_BUCKET_HOURS = 1

ENTITY_UNRESOLVED = "UNRESOLVED"
ENTITY_SECURITY = "SECURITY"

# data/runtime/identity_registry.json in the canonical store registry.
REGISTRY_RELATIVE = Path("data") / "runtime" / "identity_registry.json"


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def time_bucket(occurred_at: Any, *, bucket_hours: int = DEFAULT_BUCKET_HOURS) -> str:
    """UTC bucket label. Unparseable or absent time yields a stable sentinel.

    The sentinel matters: an event with no usable timestamp must still produce a
    repeatable id rather than silently keying on 'now', which would make the same
    event hash differently on every call and quietly break the join.
    """
    dt = _parse_ts(occurred_at)
    if dt is None:
        return "unbucketed"
    dt = dt.astimezone(timezone.utc)
    hours = max(1, int(bucket_hours))
    return f"{dt:%Y%m%d}T{(dt.hour // hours) * hours:02d}"


def resolve_entity(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Canonical entity reference for an event payload.

    Mirrors `cio_workflow_envelope.identity_from_payload` on purpose -- the two
    must not disagree about what a subject is. Accepts the several spellings the
    arcs actually use (`subject_id`, `symbol`, `ticker`, `subject_guid`,
    `security_guid`) rather than forcing callers to normalise first, because
    requiring normalisation at every call site is how the fields drift apart
    again.
    """
    src = dict(payload or {})

    guid = src.get("subject_guid") or src.get("security_guid")
    guid_s = str(guid).strip() if guid not in (None, "") else None

    subject = (
        src.get("subject_id")
        or src.get("symbol")
        or src.get("ticker")
        or guid_s
    )
    subject_s = str(subject).strip().upper() if subject not in (None, "") else None

    # Consult the durable spine before falling back to the symbol string. Until
    # Phase A this module keyed events on a ticker, which is an alias and not an
    # identity -- a ticker is reassigned after delisting, so two different
    # companies could collide on one event id years apart. A registered entity
    # supplies its real GUID; an unregistered one degrades to the previous
    # behaviour rather than blocking.
    if not guid_s and subject_s:
        try:
            from scripts.lib.identity_registry import load as _load_registry, lookup_symbol
            entity = lookup_symbol(_load_registry(), subject_s)
            if entity and entity.get("subject_guid"):
                guid_s = str(entity["subject_guid"])
                src.setdefault("entity_type", ENTITY_SECURITY)
        except Exception:
            pass  # registry unavailable: identity still resolves by symbol

    declared = src.get("entity_type")
    if declared not in (None, ""):
        entity_type = str(declared)
    elif guid_s:
        entity_type = ENTITY_SECURITY
    else:
        entity_type = ENTITY_UNRESOLVED

    return {
        "subject_id": subject_s,
        "subject_guid": guid_s,
        "entity_type": entity_type,
        "resolved": bool(subject_s),
        # Same guarantee the envelope makes: a ticker is not a security identity.
        "never_minted_security_guid": True,
    }


def event_id_for(
    payload: Mapping[str, Any] | None,
    *,
    event_kind: str = "UNSPECIFIED",
    occurred_at: Any = None,
    bucket_hours: int = DEFAULT_BUCKET_HOURS,
) -> str | None:
    """Deterministic `evt_…` for a real-world event, or None if unresolvable.

    Returns None rather than a placeholder when the entity does not resolve. A
    shared "unknown" id would join every unresolved event to every other one,
    which is worse than no join: it would report completions that never happened.
    """
    entity = resolve_entity(payload)
    if not entity["resolved"]:
        return None

    src = dict(payload or {})
    when = occurred_at or src.get("occurred_at") or src.get("created_at") or src.get("as_of")

    return EVENT_PREFIX + _digest({
        "subject": entity["subject_guid"] or entity["subject_id"],
        "entity_type": entity["entity_type"],
        "kind": str(event_kind or "UNSPECIFIED").upper(),
        "bucket": time_bucket(when, bucket_hours=bucket_hours),
    })


def workflow_id_for_event(event_id: str) -> str:
    """The workflow id both arcs should use for one event.

    Keeps the existing `wf_` shape so a reader cannot tell an event-derived id
    from a legacy one by inspection, and nothing downstream needs to learn a new
    format.
    """
    return WORKFLOW_PREFIX + _digest({"event_id": event_id})


def identity_fields(
    payload: Mapping[str, Any] | None,
    *,
    event_kind: str = "UNSPECIFIED",
    occurred_at: Any = None,
    bucket_hours: int = DEFAULT_BUCKET_HOURS,
) -> dict[str, Any]:
    """Envelope fields for a payload. Safe to merge into an existing envelope.

    Only ever adds `event_id`/`entity_type`/`subject_id`; it does not decide
    `workflow_id`. Rewriting workflow_id changes how every downstream consumer
    keys lineage, so that stays an explicit caller choice.
    """
    entity = resolve_entity(payload)
    eid = event_id_for(
        payload, event_kind=event_kind, occurred_at=occurred_at, bucket_hours=bucket_hours
    )
    fields: dict[str, Any] = {
        "entity_type": entity["entity_type"],
        "never_minted_security_guid": True,
    }
    if entity["subject_id"]:
        fields["subject_id"] = entity["subject_id"]
    if entity["subject_guid"]:
        fields["subject_guid"] = entity["subject_guid"]
    if eid:
        fields["event_id"] = eid
    return fields


def registry_path(root: Path | str | None = None) -> Path:
    env = os.environ.get("TRADEAI_IDENTITY_REGISTRY")
    if env:
        return Path(env)
    if root:
        return Path(root) / REGISTRY_RELATIVE
    try:
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root()) / REGISTRY_RELATIVE
    except Exception:
        return Path.home() / "trade-ai-releases" / "persistent-state" / REGISTRY_RELATIVE


def record_identity(
    payload: Mapping[str, Any] | None,
    *,
    event_kind: str = "UNSPECIFIED",
    occurred_at: Any = None,
    root: Path | str | None = None,
) -> dict[str, Any] | None:
    """Append an observability record for a derived identity.

    Best-effort by design: the id is derived, not looked up, so a failure here
    cannot break the join. Returns None when the entity does not resolve or the
    write fails -- callers should not branch on it.
    """
    eid = event_id_for(payload, event_kind=event_kind, occurred_at=occurred_at)
    if not eid:
        return None

    entity = resolve_entity(payload)
    record = {
        "schema": SCHEMA,
        "event_id": eid,
        "workflow_id": workflow_id_for_event(eid),
        "subject_id": entity["subject_id"],
        "entity_type": entity["entity_type"],
        "event_kind": str(event_kind or "UNSPECIFIED").upper(),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }

    try:
        path = registry_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                doc = {}
        except (OSError, ValueError):
            doc = {}
        doc.setdefault("schema", REGISTRY_SCHEMA)
        doc.setdefault("authority", AUTHORITY)
        entries = doc.setdefault("events", {})
        if isinstance(entries, dict):
            entries[eid] = record
        doc["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        return None

    return record
