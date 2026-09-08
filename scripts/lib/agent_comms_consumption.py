#!/usr/bin/env python3
"""agent_comms_consumption.py — production-capable agent consumption of comm events.

Emits AgentConsumptionReceipt@v2 with source_kind='comm_event' and exact event
linkage. Dry-run by default; --apply writes receipts only.

HARD BOUNDARY (Lane B): does NOT import Lane A wake modules and does NOT
write agent_wake_receipts / wake / commitment tables. Wake coupling belongs
to Lane A.

Prior art from wt-g1g2 adapted and stripped of wake writes.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

SCHEMA_VERSION = "AgentCommsConsumption@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
OBJECT_TYPE = "CommunicationEvent"
DEFAULT_PURPOSE = "operator_turn_intake"
DEFAULT_LOOKBACK_HOURS = float(os.getenv("COMMS_CONSUMPTION_LOOKBACK_H", "24"))
DEFAULT_LIMIT = int(os.getenv("COMMS_CONSUMPTION_LIMIT", "50"))
ORPHAN_MARKER = "ORPHAN_EVENT_NOT_FOUND"

_EVENT_COLUMNS = (
    "event_id",
    "direction",
    "event_type",
    "message_class",
    "severity",
    "producer",
    "subject_key",
    "thread_id",
    "correlation_id",
    "knowledge_eligibility",
    "knowledge_status",
    "expires_at",
    "content_hash",
    "short_summary",
    "observed_at",
    "created_at",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def comms_subject_guid(subject_key: str) -> str:
    """Deterministic conversation guid under the house tradeai: namespace.

    Identifies the conversation only — never a security. Does not redefine
    SubjectGuid spine helpers.
    """
    key = str(subject_key or "").strip()
    if not key:
        raise ValueError("subject_key required to identify a conversation")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:comms:subject:{key}"))


def fetch_recent_events(
    conn: Any,
    *,
    since: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    direction: str | None = None,
    lookback_hours: float = DEFAULT_LOOKBACK_HOURS,
) -> list[dict[str, Any]]:
    """Read recent communication events from DB, or [] when unavailable."""
    if conn is None:
        return []
    cutoff = since or (_now() - timedelta(hours=float(lookback_hours)))
    cols = ", ".join(_EVENT_COLUMNS)
    params: list[Any] = [cutoff]
    where = "WHERE COALESCE(observed_at, created_at) >= %s"
    if direction:
        where += " AND direction = %s"
        params.append(str(direction).upper())
    params.append(max(1, int(limit)))
    cur = conn.cursor()
    cur.execute(
        f"""SELECT {cols} FROM communication_events
            {where}
            ORDER BY COALESCE(observed_at, created_at) DESC
            LIMIT %s""",
        tuple(params),
    )
    return [dict(zip(_EVENT_COLUMNS, row)) for row in cur.fetchall()]


def select_events_for_agent(
    agent_id: str,
    events: Iterable[dict[str, Any]],
    *,
    allow_unknown: bool = False,
) -> list[dict[str, Any]]:
    """Subscription-scoped selection without the knowledge gate."""
    from scripts.lib.comms.agent_contracts import eligible_events_for_agent

    return list(
        eligible_events_for_agent(
            agent_id,
            list(events),
            allow_unknown=allow_unknown,
            eligible_only=False,
        )
    )


def consume_event(
    agent_id: str,
    event: dict[str, Any],
    *,
    purpose: str = DEFAULT_PURPOSE,
    apply: bool = False,
    agent_version: str | None = None,
    effect_kind: str = "none",
    effect_ref: str | None = None,
    source_sha: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read one event and optionally emit AgentConsumptionReceipt@v2.

    ``apply=False`` (default) builds the receipt in memory without writing.
    Never writes wake tables.
    """
    event_id = str(event.get("event_id") or "").strip()
    if not event_id:
        return {"ok": False, "reason": "event_missing_id"}
    subject_key = str(event.get("subject_key") or "").strip()
    subject_guid = None
    if subject_key:
        try:
            subject_guid = comms_subject_guid(subject_key)
        except ValueError:
            subject_guid = None

    report: dict[str, Any] = {
        "ok": False,
        "event_id": event_id,
        "subject_key": subject_key or None,
        "subject_guid": subject_guid,
        "applied": bool(apply),
        "schema": SCHEMA_VERSION,
        "authority": AUTHORITY,
    }

    prov = dict(provenance or {})
    if not prov.get("producer"):
        # Fixture/test rows must be tagged producer='test'.
        prov["producer"] = "test" if not apply else "agent_comms_consumption"
    prov.setdefault("inputs", [event_id])
    prov.setdefault("policy_decisions", ["read_only_advisory"])
    prov.setdefault("llm", None)

    from scripts.lib.comms.agent_contracts import (
        AgentConsumptionReceipt,
        emit_consumption_receipt,
    )

    if not apply:
        # Dry-run: mint the @v2 shape in-process; write nothing.
        receipt = AgentConsumptionReceipt(
            agent_id=str(agent_id).strip().lower(),
            event_id=event_id,
            source_kind="comm_event",
            source_id=event_id,
            purpose=purpose,
            agent_version=agent_version,
            thread_id=event.get("thread_id") or None,
            subject_guid=subject_guid,
            effect_kind=effect_kind,
            effect_ref=effect_ref,
            policy_decision="read_only_advisory",
            source_sha=source_sha,
            correlation_id=event.get("correlation_id") or event.get("thread_id"),
            parent_id=event_id,
            parent_kind="comm_event",
            provenance=prov,
        )
        receipt.mint_identity()
        report["ok"] = True
        report["receipt_id"] = receipt.receipt_id
        report["source_kind"] = receipt.source_kind
        report["source_id"] = receipt.source_id
        report["effect_kind"] = receipt.effect_kind
        report["schema_version"] = receipt.schema_version
        report["persisted"] = "dry_run"
        report["provenance_producer"] = (receipt.provenance or {}).get("producer")
        return report

    receipt = emit_consumption_receipt(
        agent_id,
        event_id=event_id,
        source_kind="comm_event",
        source_id=event_id,
        purpose=purpose,
        agent_version=agent_version,
        thread_id=event.get("thread_id") or None,
        subject_guid=subject_guid,
        effect_kind=effect_kind,
        effect_ref=effect_ref,
        policy_decision="read_only_advisory",
        event=event,
        source_sha=source_sha,
        correlation_id=event.get("correlation_id") or event.get("thread_id"),
        parent_id=event_id,
        parent_kind="comm_event",
        provenance=prov,
    )
    report["ok"] = True
    report["receipt_id"] = receipt.receipt_id
    report["source_kind"] = receipt.source_kind
    report["source_id"] = receipt.source_id
    report["effect_kind"] = receipt.effect_kind
    report["schema_version"] = receipt.schema_version
    report["persisted"] = receipt.persisted
    report["provenance_producer"] = (receipt.provenance or {}).get("producer")
    return report


def consume_recent(
    agent_id: str = "cio",
    *,
    conn: Any = None,
    purpose: str = DEFAULT_PURPOSE,
    direction: str | None = "INBOUND",
    limit: int = DEFAULT_LIMIT,
    lookback_hours: float = DEFAULT_LOOKBACK_HOURS,
    apply: bool = False,
    events: list[dict[str, Any]] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One pass: fetch, subscription-scope, read, emit @v2 receipt (no wake)."""
    fetched = (
        list(events)
        if events is not None
        else fetch_recent_events(
            conn, limit=limit, direction=direction, lookback_hours=lookback_hours
        )
    )
    selected = select_events_for_agent(agent_id, fetched)
    results = [
        consume_event(
            agent_id,
            ev,
            purpose=purpose,
            apply=apply,
            provenance=provenance,
        )
        for ev in selected
    ]
    consumed = [r for r in results if r.get("ok")]
    return {
        "schema": SCHEMA_VERSION,
        "authority": AUTHORITY,
        "agent_id": agent_id,
        "purpose": purpose,
        "direction": direction,
        "applied": bool(apply),
        "fetched": len(fetched),
        "selected": len(selected),
        "consumed": len(consumed),
        "skipped": len(results) - len(consumed),
        "results": results,
    }


def find_orphan_comms_receipts(conn: Any) -> list[dict[str, Any]]:
    """Receipts naming an event that does not exist."""
    if conn is None:
        return []
    cur = conn.cursor()
    cur.execute(
        """SELECT r.receipt_id, r.agent_id, r.event_id, r.purpose,
                  r.policy_decision, r.retrieved_at
             FROM communication_agent_consumption_receipts r
            WHERE NOT EXISTS (
                  SELECT 1 FROM communication_events e
                   WHERE e.event_id::text = r.event_id)
            ORDER BY r.created_at"""
    )
    cols = (
        "receipt_id",
        "agent_id",
        "event_id",
        "purpose",
        "policy_decision",
        "retrieved_at",
    )
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def flag_orphan_comms_receipts(conn: Any, *, apply: bool = False) -> dict[str, Any]:
    """Mark orphan receipts in place. Never deletes one (AGENTS.md §0.6)."""
    orphans = find_orphan_comms_receipts(conn)
    out: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "orphans": orphans,
        "count": len(orphans),
        "applied": bool(apply),
        "flagged": 0,
        "marker": ORPHAN_MARKER,
    }
    unflagged = [o for o in orphans if o.get("policy_decision") != ORPHAN_MARKER]
    out["already_flagged"] = len(orphans) - len(unflagged)
    if apply and unflagged:
        cur = conn.cursor()
        cur.execute(
            """UPDATE communication_agent_consumption_receipts
                  SET policy_decision = %s
                WHERE receipt_id = ANY(%s)""",
            (ORPHAN_MARKER, [o["receipt_id"] for o in unflagged]),
        )
        out["flagged"] = cur.rowcount
        conn.commit()
    return out
