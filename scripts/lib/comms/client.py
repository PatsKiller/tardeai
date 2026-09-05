"""publish_communication — Phase 1 ledger write. Never calls providers.

Phase 3: after a successful persist, auto-reserves ChannelDelivery@v1 stubs
per channel (RESERVED only; no provider I/O, delivery_owned stays False).
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from scripts.lib.comms.delivery import attach_delivery_reservation
from scripts.lib.comms.event import CommunicationEvent, required_missing
from scripts.lib.comms.mode import get_gateway_mode

# In-process fallback when DB unavailable (OFF/SHADOW still record intent).
_MEM: dict[str, dict[str, Any]] = {}
_MEM_BY_IDEMPOTENCY: dict[str, str] = {}
_lock = threading.Lock()


class CommunicationGateError(ValueError):
    """Fail-closed: required provenance/identity/policy missing."""


@dataclass
class PublishResult:
    ok: bool
    event_id: str | None
    idempotency_key: str | None
    gateway_mode: str
    persisted: str  # "db" | "memory" | "none"
    duplicate: bool = False
    outbox_channels: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    delivery_owned: bool = False  # Phase 1–3 always False (SHADOW stubs only)
    delivery_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "event_id": self.event_id,
            "idempotency_key": self.idempotency_key,
            "gateway_mode": self.gateway_mode,
            "persisted": self.persisted,
            "duplicate": self.duplicate,
            "outbox_channels": list(self.outbox_channels),
            "errors": list(self.errors),
            "delivery_owned": self.delivery_owned,
            "delivery_ids": list(self.delivery_ids),
        }


def _db_conn():
    """Best-effort connection; None when unavailable or tables missing."""
    try:
        from db_adapter import _get_conn  # scripts/ on path in many entrypoints
    except Exception:
        try:
            from scripts.db_adapter import _get_conn  # type: ignore
        except Exception:
            return None
    try:
        conn = _get_conn()
    except Exception:
        return None
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                 WHERE table_name IN ('communication_events', 'communication_outbox')
                """
            )
            n = cur.fetchone()[0]
        if int(n) < 2:
            return None
    except Exception:
        return None
    return conn


def _channels_for(event: CommunicationEvent) -> list[str]:
    if event.channels:
        return list(event.channels)
    pol = event.delivery_policy or {}
    ch = pol.get("channels")
    if isinstance(ch, list) and ch:
        return [str(x) for x in ch]
    return ["telegram"] if event.direction == "OUTBOUND" else []


def _reserve_deliveries(result: PublishResult, channels: list[str]) -> PublishResult:
    """Phase 3: RESERVED stubs per channel. Never sends; never claims ownership."""
    if not result.ok or not result.event_id or not channels:
        return result
    delivery_ids: list[str] = []
    for ch in channels:
        try:
            stub = attach_delivery_reservation(result.event_id, ch)
            if stub.delivery_id:
                delivery_ids.append(stub.delivery_id)
        except Exception as e:
            result.errors.append(f"delivery_reserve:{ch}:{type(e).__name__}")
    result.delivery_ids = delivery_ids
    result.delivery_owned = False
    return result


def _persist_memory(event: CommunicationEvent, channels: list[str]) -> PublishResult:
    mode = get_gateway_mode()
    assert event.event_id and event.idempotency_key
    with _lock:
        existing = _MEM_BY_IDEMPOTENCY.get(event.idempotency_key)
        if existing:
            return PublishResult(
                ok=True,
                event_id=existing,
                idempotency_key=event.idempotency_key,
                gateway_mode=mode,
                persisted="memory",
                duplicate=True,
                outbox_channels=channels,
                delivery_owned=False,
            )
        row = event.to_row()
        row["gateway_mode_at_write"] = mode
        _MEM[event.event_id] = row
        _MEM_BY_IDEMPOTENCY[event.idempotency_key] = event.event_id
    return PublishResult(
        ok=True,
        event_id=event.event_id,
        idempotency_key=event.idempotency_key,
        gateway_mode=mode,
        persisted="memory",
        duplicate=False,
        outbox_channels=channels,
        delivery_owned=False,
    )


def _persist_db(conn, event: CommunicationEvent, channels: list[str]) -> PublishResult:
    mode = get_gateway_mode()
    assert event.event_id and event.idempotency_key
    row = event.to_row()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO communication_events (
                event_id, schema_version, direction, event_type, message_class,
                severity, audience, producer, producer_version, producer_event_id,
                idempotency_key, subject_key, thread_id, correlation_id, causation_id,
                parent_event_id, reply_to_event_id, incident_id, supersedes_event_id,
                version, entity_refs, protected_facts, protected_facts_hash,
                authoritative_sources, command_center_url, external_links,
                content_classification, retention_class, expires_at, legal_hold,
                redaction_policy, curation_mode, content_hash, sanitized_body,
                short_summary, raw_body_ref, provider_coordinates, delivery_policy,
                knowledge_eligibility, knowledge_status, build_sha, release_id,
                run_id, source_system, source_agent, source_job, observed_at,
                created_at, payload, gateway_mode_at_write
            ) VALUES (
                %(event_id)s, %(schema_version)s, %(direction)s, %(event_type)s, %(message_class)s,
                %(severity)s, %(audience)s, %(producer)s, %(producer_version)s, %(producer_event_id)s,
                %(idempotency_key)s, %(subject_key)s, %(thread_id)s, %(correlation_id)s, %(causation_id)s,
                %(parent_event_id)s, %(reply_to_event_id)s, %(incident_id)s, %(supersedes_event_id)s,
                %(version)s, %(entity_refs)s, %(protected_facts)s, %(protected_facts_hash)s,
                %(authoritative_sources)s, %(command_center_url)s, %(external_links)s,
                %(content_classification)s, %(retention_class)s, %(expires_at)s, %(legal_hold)s,
                %(redaction_policy)s, %(curation_mode)s, %(content_hash)s, %(sanitized_body)s,
                %(short_summary)s, %(raw_body_ref)s, %(provider_coordinates)s, %(delivery_policy)s,
                %(knowledge_eligibility)s, %(knowledge_status)s, %(build_sha)s, %(release_id)s,
                %(run_id)s, %(source_system)s, %(source_agent)s, %(source_job)s, %(observed_at)s,
                %(created_at)s, %(payload)s, %(gateway_mode_at_write)s
            )
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING event_id
            """,
            {
                **row,
                "entity_refs": json.dumps(row.get("entity_refs") or {}),
                "protected_facts": json.dumps(row.get("protected_facts") or {}),
                "authoritative_sources": json.dumps(row.get("authoritative_sources") or []),
                "external_links": json.dumps(row.get("external_links") or []),
                "provider_coordinates": json.dumps(row.get("provider_coordinates") or {}),
                "delivery_policy": json.dumps(row.get("delivery_policy") or {}),
                "payload": json.dumps(row.get("payload") or {}),
                "gateway_mode_at_write": mode,
            },
        )
        returned = cur.fetchone()
        duplicate = returned is None
        event_id = event.event_id
        if duplicate:
            cur.execute(
                "SELECT event_id FROM communication_events WHERE idempotency_key = %s",
                (event.idempotency_key,),
            )
            existing = cur.fetchone()
            event_id = existing[0] if existing else event.event_id
        else:
            for ch in channels:
                cur.execute(
                    """
                    INSERT INTO communication_outbox (event_id, channel, status)
                    VALUES (%s, %s, 'recorded')
                    ON CONFLICT (event_id, channel) DO NOTHING
                    """,
                    (event_id, ch),
                )
            for etype, eid in (event.entity_refs or {}).items():
                if eid is None:
                    continue
                if isinstance(eid, (list, tuple)):
                    ids = eid
                else:
                    ids = [eid]
                for one in ids:
                    cur.execute(
                        """
                        INSERT INTO communication_entity_links (event_id, entity_type, entity_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (event_id, str(etype), str(one)),
                    )
        conn.commit()
    return PublishResult(
        ok=True,
        event_id=event_id,
        idempotency_key=event.idempotency_key,
        gateway_mode=mode,
        persisted="db",
        duplicate=duplicate,
        outbox_channels=channels,
        delivery_owned=False,
    )


def publish_communication(event: CommunicationEvent) -> PublishResult:
    """Mint identity, fail closed on required fields, persist ledger row.

    Never performs Telegram/Email/Slack/WhatsApp provider calls.
    delivery_owned is always False in Phase 1–3 (SHADOW stubs only).
    After persist, attaches SubjectThread membership (Phase 4) then reserves
    ChannelDelivery@v1 rows per channel without sending.
    """
    mode = get_gateway_mode()
    event.mint_identity()
    missing = required_missing(event)
    if missing:
        return PublishResult(
            ok=False,
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            gateway_mode=mode,
            persisted="none",
            errors=[f"missing:{m}" for m in missing],
            delivery_owned=False,
        )

    channels = _channels_for(event)
    conn = _db_conn()
    if conn is not None:
        try:
            result = _persist_db(conn, event, channels)
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            # Degrade to memory rather than drop the logical event in OFF/SHADOW.
            result = _persist_memory(event, channels)
            result.errors.append(f"db_fallback:{type(e).__name__}")
    else:
        result = _persist_memory(event, channels)

    if result.ok and result.event_id and event.subject_key:
        _attach_subject_memory(event, result.event_id, channels)
    return _reserve_deliveries(result, channels)


def _attach_subject_memory(
    event: CommunicationEvent, event_id: str, channels: list[str]
) -> None:
    """Best-effort SubjectThread membership after successful publish.

    Lazy import avoids circular imports with subject_memory → client snapshot.
    Never raises into publish_communication.
    """
    try:
        from scripts.lib.comms.subject_memory import attach_event_to_subject

        ch = channels[0] if channels else None
        attach_event_to_subject(
            event.subject_key,
            event_id,
            channel=ch,
            provider_coordinates=event.provider_coordinates or None,
        )
    except Exception:
        return


def memory_store_snapshot() -> dict[str, dict[str, Any]]:
    """Test helper: copy of in-memory ledger."""
    with _lock:
        return {k: dict(v) for k, v in _MEM.items()}


def reset_memory_store() -> None:
    """Test helper."""
    with _lock:
        _MEM.clear()
        _MEM_BY_IDEMPOTENCY.clear()
