"""ChannelDelivery@v1 — delivery attempt ledger (Phase 3).

Records RESERVED → terminal attempt rows. Never calls providers.
SHADOW / OFF: stubs only; gateway does not own egress.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from scripts.lib.comms.identity import new_event_id

SCHEMA_VERSION = "ChannelDelivery@v1"

DELIVERY_STATUSES = frozenset(
    {
        "RESERVED",
        "SENDING",
        "SENT",
        "DELIVERED",
        "ACKNOWLEDGED",
        "FAILED",
        "BOUNCED",
        "SUPPRESSED",
        "EXPIRED",
        "CANCELLED",
        "UNKNOWN",
        # Gateway did not own this class: the legacy path delivered and the
        # gateway's auto-reserved stub is settled here rather than left as a
        # phantom in-flight RESERVED row (Wave A F1).
        "LEGACY_DELIVERED",
    }
)

# Terminal statuses (set completed_at). LEGACY_DELIVERED is terminal: the
# legacy path already delivered; the gateway records it and never re-opens.
_TERMINAL_STATUSES = frozenset(
    {
        "SENT",
        "DELIVERED",
        "ACKNOWLEDGED",
        "FAILED",
        "BOUNCED",
        "SUPPRESSED",
        "EXPIRED",
        "CANCELLED",
        "LEGACY_DELIVERED",
    }
)

# Allowed status transitions (from → to). UNKNOWN is a catch-all sink.
_TRANSITIONS: dict[str, frozenset[str]] = {
    "RESERVED": frozenset(
        {"SENDING", "SENT", "FAILED", "SUPPRESSED", "EXPIRED", "CANCELLED", "UNKNOWN", "LEGACY_DELIVERED"}
    ),
    "SENDING": frozenset({"SENT", "FAILED", "CANCELLED", "UNKNOWN"}),
    "SENT": frozenset({"DELIVERED", "ACKNOWLEDGED", "BOUNCED", "FAILED", "UNKNOWN"}),
    "DELIVERED": frozenset({"ACKNOWLEDGED", "UNKNOWN"}),
    "ACKNOWLEDGED": frozenset({"UNKNOWN"}),
    "FAILED": frozenset({"RESERVED", "SENDING", "UNKNOWN"}),  # retry may re-open
    "BOUNCED": frozenset({"UNKNOWN"}),
    "SUPPRESSED": frozenset({"UNKNOWN"}),
    "EXPIRED": frozenset({"UNKNOWN"}),
    "CANCELLED": frozenset({"UNKNOWN"}),
    "UNKNOWN": frozenset(),
}

_MEM: dict[str, dict[str, Any]] = {}
_MEM_BY_IDEMPOTENCY: dict[str, str] = {}
_MEM_BY_EVENT_CHANNEL_ATTEMPT: dict[tuple[str, str, str], str] = {}
_lock = threading.Lock()


class DeliveryGateError(ValueError):
    """Fail-closed: required delivery identity/policy missing or illegal transition."""


@dataclass
class ChannelDelivery:
    """One delivery attempt for a CommunicationEvent on a channel."""

    event_id: str
    channel: str
    delivery_id: str | None = None
    attempt_id: str = "1"
    schema_version: str = SCHEMA_VERSION
    adapter_version: str | None = None
    destination_policy_id: str | None = None
    recipient_set_hash: str | None = None
    render_variant_id: str | None = None
    chunk_count: int = 1
    part_sequence: int = 0
    reply_thread_coordinates: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    status: str = "RESERVED"
    request_fingerprint: str | None = None
    response_fingerprint: str | None = None
    provider_message_id: str | None = None
    provider_coordinates: dict[str, Any] = field(default_factory=dict)
    error_taxonomy: str | None = None
    reserved_at: datetime | None = None
    sent_at: datetime | None = None
    completed_at: datetime | None = None
    retry_policy: dict[str, Any] = field(default_factory=dict)
    chunks: list[dict[str, Any]] = field(default_factory=list)
    persisted: str = "none"  # "db" | "memory" | "none"
    duplicate: bool = False

    def mint_identity(self) -> "ChannelDelivery":
        if not self.event_id or not str(self.event_id).strip():
            raise DeliveryGateError("event_id required for ChannelDelivery")
        if not self.channel or not str(self.channel).strip():
            raise DeliveryGateError("channel required for ChannelDelivery")
        if self.status not in DELIVERY_STATUSES:
            raise DeliveryGateError(f"status_invalid:{self.status}")
        if not self.delivery_id:
            self.delivery_id = f"dlv_{new_event_id()}"
        if not self.attempt_id:
            self.attempt_id = "1"
        if not self.idempotency_key:
            self.idempotency_key = delivery_idempotency_key(
                event_id=self.event_id,
                channel=self.channel,
                attempt_id=self.attempt_id,
            )
        if self.reserved_at is None:
            self.reserved_at = datetime.now(timezone.utc)
        if self.adapter_version is None and self.channel == "telegram":
            self.adapter_version = "telegram@v1"
        return self

    def to_row(self) -> dict[str, Any]:
        self.mint_identity()
        d = asdict(self)
        d.pop("chunks", None)
        d.pop("persisted", None)
        d.pop("duplicate", None)
        return d


def delivery_idempotency_key(*, event_id: str, channel: str, attempt_id: str = "1") -> str:
    material = {"event_id": event_id, "channel": channel, "attempt_id": attempt_id}
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"didem_{digest}"


def _db_conn():
    """Best-effort connection; None when unavailable or deliveries table missing."""
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
                 WHERE table_name = 'communication_deliveries'
                """
            )
            n = cur.fetchone()[0]
        if int(n) < 1:
            return None
    except Exception:
        return None
    return conn


def _row_to_delivery(row: dict[str, Any], *, persisted: str, duplicate: bool = False) -> ChannelDelivery:
    return ChannelDelivery(
        delivery_id=row.get("delivery_id"),
        attempt_id=str(row.get("attempt_id") or "1"),
        event_id=str(row["event_id"]),
        channel=str(row["channel"]),
        schema_version=str(row.get("schema_version") or SCHEMA_VERSION),
        adapter_version=row.get("adapter_version"),
        destination_policy_id=row.get("destination_policy_id"),
        recipient_set_hash=row.get("recipient_set_hash"),
        render_variant_id=row.get("render_variant_id"),
        chunk_count=int(row.get("chunk_count") or 1),
        part_sequence=int(row.get("part_sequence") or 0),
        reply_thread_coordinates=dict(row.get("reply_thread_coordinates") or {}),
        idempotency_key=row.get("idempotency_key"),
        status=str(row.get("status") or "RESERVED"),
        request_fingerprint=row.get("request_fingerprint"),
        response_fingerprint=row.get("response_fingerprint"),
        provider_message_id=row.get("provider_message_id"),
        provider_coordinates=dict(row.get("provider_coordinates") or {}),
        error_taxonomy=row.get("error_taxonomy"),
        reserved_at=row.get("reserved_at"),
        sent_at=row.get("sent_at"),
        completed_at=row.get("completed_at"),
        retry_policy=dict(row.get("retry_policy") or {}),
        chunks=list(row.get("chunks") or []),
        persisted=persisted,
        duplicate=duplicate,
    )


def _persist_memory(delivery: ChannelDelivery) -> ChannelDelivery:
    delivery.mint_identity()
    assert delivery.delivery_id and delivery.idempotency_key
    key = (delivery.event_id, delivery.channel, delivery.attempt_id)
    with _lock:
        existing_id = _MEM_BY_IDEMPOTENCY.get(delivery.idempotency_key)
        if existing_id is None:
            existing_id = _MEM_BY_EVENT_CHANNEL_ATTEMPT.get(key)
        if existing_id:
            row = _MEM[existing_id]
            return _row_to_delivery(row, persisted="memory", duplicate=True)
        row = delivery.to_row()
        row["chunks"] = list(delivery.chunks)
        _MEM[delivery.delivery_id] = row
        _MEM_BY_IDEMPOTENCY[delivery.idempotency_key] = delivery.delivery_id
        _MEM_BY_EVENT_CHANNEL_ATTEMPT[key] = delivery.delivery_id
    delivery.persisted = "memory"
    delivery.duplicate = False
    return delivery


def _persist_db(conn, delivery: ChannelDelivery) -> ChannelDelivery:
    delivery.mint_identity()
    assert delivery.delivery_id and delivery.idempotency_key
    row = delivery.to_row()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO communication_deliveries (
                delivery_id, attempt_id, event_id, channel, adapter_version,
                destination_policy_id, recipient_set_hash, render_variant_id,
                chunk_count, part_sequence, reply_thread_coordinates,
                idempotency_key, status, request_fingerprint, response_fingerprint,
                provider_message_id, provider_coordinates, error_taxonomy,
                reserved_at, sent_at, completed_at, retry_policy, schema_version
            ) VALUES (
                %(delivery_id)s, %(attempt_id)s, %(event_id)s, %(channel)s, %(adapter_version)s,
                %(destination_policy_id)s, %(recipient_set_hash)s, %(render_variant_id)s,
                %(chunk_count)s, %(part_sequence)s, %(reply_thread_coordinates)s,
                %(idempotency_key)s, %(status)s, %(request_fingerprint)s, %(response_fingerprint)s,
                %(provider_message_id)s, %(provider_coordinates)s, %(error_taxonomy)s,
                %(reserved_at)s, %(sent_at)s, %(completed_at)s, %(retry_policy)s, %(schema_version)s
            )
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING delivery_id
            """,
            {
                **row,
                "reply_thread_coordinates": json.dumps(row.get("reply_thread_coordinates") or {}),
                "provider_coordinates": json.dumps(row.get("provider_coordinates") or {}),
                "retry_policy": json.dumps(row.get("retry_policy") or {}),
            },
        )
        returned = cur.fetchone()
        duplicate = returned is None
        delivery_id = delivery.delivery_id
        if duplicate:
            cur.execute(
                "SELECT delivery_id FROM communication_deliveries WHERE idempotency_key = %s",
                (delivery.idempotency_key,),
            )
            existing = cur.fetchone()
            delivery_id = existing[0] if existing else delivery.delivery_id
            cur.execute(
                "SELECT * FROM communication_deliveries WHERE delivery_id = %s",
                (delivery_id,),
            )
            colnames = [d[0] for d in cur.description]
            fetched = cur.fetchone()
            conn.commit()
            if fetched:
                mapped = dict(zip(colnames, fetched))
                for jsonb_key in (
                    "reply_thread_coordinates",
                    "provider_coordinates",
                    "retry_policy",
                ):
                    val = mapped.get(jsonb_key)
                    if isinstance(val, str):
                        mapped[jsonb_key] = json.loads(val)
                return _row_to_delivery(mapped, persisted="db", duplicate=True)
        conn.commit()
    delivery.delivery_id = delivery_id
    delivery.persisted = "db"
    delivery.duplicate = duplicate
    return delivery


def reserve_delivery(
    *,
    event_id: str | None,
    channel: str,
    attempt_id: str = "1",
    adapter_version: str | None = None,
    destination_policy_id: str | None = None,
    recipient_set_hash: str | None = None,
    render_variant_id: str | None = None,
    reply_thread_coordinates: dict[str, Any] | None = None,
    retry_policy: dict[str, Any] | None = None,
    request_fingerprint: str | None = None,
) -> ChannelDelivery:
    """Create (or return existing) RESERVED delivery attempt. Fail closed without event_id."""
    if not event_id or not str(event_id).strip():
        raise DeliveryGateError("event_id required to reserve delivery")
    delivery = ChannelDelivery(
        event_id=str(event_id).strip(),
        channel=str(channel).strip(),
        attempt_id=str(attempt_id or "1"),
        adapter_version=adapter_version,
        destination_policy_id=destination_policy_id,
        recipient_set_hash=recipient_set_hash,
        render_variant_id=render_variant_id,
        reply_thread_coordinates=dict(reply_thread_coordinates or {}),
        retry_policy=dict(retry_policy or {}),
        request_fingerprint=request_fingerprint,
        status="RESERVED",
    )
    delivery.mint_identity()

    conn = _db_conn()
    if conn is not None:
        try:
            return _persist_db(conn, delivery)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return _persist_memory(delivery)
    return _persist_memory(delivery)


def attach_delivery_reservation(event_id: str, channel: str) -> ChannelDelivery:
    """Helper for publish_communication: reserve a stub after ledger persist."""
    return reserve_delivery(event_id=event_id, channel=channel, attempt_id="1")


def _load_memory(delivery_id: str) -> ChannelDelivery | None:
    with _lock:
        row = _MEM.get(delivery_id)
        if not row:
            return None
        return _row_to_delivery(dict(row), persisted="memory")


def _update_memory(delivery: ChannelDelivery) -> ChannelDelivery:
    assert delivery.delivery_id
    with _lock:
        if delivery.delivery_id not in _MEM:
            raise DeliveryGateError(f"delivery_not_found:{delivery.delivery_id}")
        row = delivery.to_row()
        row["chunks"] = list(delivery.chunks)
        _MEM[delivery.delivery_id] = row
    delivery.persisted = "memory"
    return delivery


def _assert_transition(current: str, new_status: str) -> None:
    if new_status not in DELIVERY_STATUSES:
        raise DeliveryGateError(f"status_invalid:{new_status}")
    if current == new_status:
        return
    allowed = _TRANSITIONS.get(current, frozenset())
    if new_status not in allowed:
        raise DeliveryGateError(f"status_transition_illegal:{current}->{new_status}")


def settle_delivery(
    delivery_id: str,
    *,
    status: str,
    provider_message_id: str | None = None,
    provider_coordinates: dict[str, Any] | None = None,
    response_fingerprint: str | None = None,
    error_taxonomy: str | None = None,
    sent_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> ChannelDelivery:
    """Transition a reserved/in-flight delivery to a settlement status. No provider I/O."""
    if not delivery_id or not str(delivery_id).strip():
        raise DeliveryGateError("delivery_id required to settle")
    new_status = str(status).strip().upper()

    mem = _load_memory(delivery_id)
    if mem is not None:
        _assert_transition(mem.status, new_status)
        mem.status = new_status
        if provider_message_id is not None:
            mem.provider_message_id = provider_message_id
        if provider_coordinates is not None:
            mem.provider_coordinates = dict(provider_coordinates)
        if response_fingerprint is not None:
            mem.response_fingerprint = response_fingerprint
        if error_taxonomy is not None:
            mem.error_taxonomy = error_taxonomy
        now = datetime.now(timezone.utc)
        if new_status in ("SENT", "DELIVERED", "ACKNOWLEDGED") and mem.sent_at is None:
            mem.sent_at = sent_at or now
        if new_status in _TERMINAL_STATUSES:
            mem.completed_at = completed_at or now
        elif sent_at is not None:
            mem.sent_at = sent_at
        if completed_at is not None:
            mem.completed_at = completed_at
        return _update_memory(mem)

    conn = _db_conn()
    if conn is None:
        raise DeliveryGateError(f"delivery_not_found:{delivery_id}")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM communication_deliveries WHERE delivery_id = %s FOR UPDATE",
                (delivery_id,),
            )
            colnames = [d[0] for d in cur.description]
            fetched = cur.fetchone()
            if not fetched:
                conn.rollback()
                raise DeliveryGateError(f"delivery_not_found:{delivery_id}")
            mapped = dict(zip(colnames, fetched))
            for jsonb_key in ("reply_thread_coordinates", "provider_coordinates", "retry_policy"):
                val = mapped.get(jsonb_key)
                if isinstance(val, str):
                    mapped[jsonb_key] = json.loads(val)
            current = str(mapped["status"])
            _assert_transition(current, new_status)
            now = datetime.now(timezone.utc)
            new_sent = mapped.get("sent_at")
            new_completed = mapped.get("completed_at")
            if new_status in ("SENT", "DELIVERED", "ACKNOWLEDGED") and new_sent is None:
                new_sent = sent_at or now
            if new_status in _TERMINAL_STATUSES:
                new_completed = completed_at or now
            coords = (
                json.dumps(provider_coordinates)
                if provider_coordinates is not None
                else json.dumps(mapped.get("provider_coordinates") or {})
            )
            cur.execute(
                """
                UPDATE communication_deliveries SET
                    status = %s,
                    provider_message_id = COALESCE(%s, provider_message_id),
                    provider_coordinates = %s::jsonb,
                    response_fingerprint = COALESCE(%s, response_fingerprint),
                    error_taxonomy = COALESCE(%s, error_taxonomy),
                    sent_at = COALESCE(%s, sent_at),
                    completed_at = COALESCE(%s, completed_at),
                    updated_at = now()
                WHERE delivery_id = %s
                RETURNING *
                """,
                (
                    new_status,
                    provider_message_id,
                    coords,
                    response_fingerprint,
                    error_taxonomy,
                    new_sent if sent_at is None else sent_at,
                    new_completed if completed_at is None else completed_at,
                    delivery_id,
                ),
            )
            colnames = [d[0] for d in cur.description]
            updated = cur.fetchone()
            conn.commit()
            mapped = dict(zip(colnames, updated))
            for jsonb_key in ("reply_thread_coordinates", "provider_coordinates", "retry_policy"):
                val = mapped.get(jsonb_key)
                if isinstance(val, str):
                    mapped[jsonb_key] = json.loads(val)
            return _row_to_delivery(mapped, persisted="db")
    except DeliveryGateError:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise DeliveryGateError(f"settle_failed:{type(e).__name__}") from e


def record_chunk(
    delivery_id: str,
    *,
    part_sequence: int,
    provider_message_id: str | None = None,
    provider_coordinates: dict[str, Any] | None = None,
    response_fingerprint: str | None = None,
) -> ChannelDelivery:
    """Record a multi-part chunk against an existing delivery (Telegram splits, etc.)."""
    if not delivery_id or not str(delivery_id).strip():
        raise DeliveryGateError("delivery_id required to record_chunk")
    if part_sequence < 0:
        raise DeliveryGateError("part_sequence must be >= 0")

    chunk = {
        "part_sequence": int(part_sequence),
        "provider_message_id": provider_message_id,
        "provider_coordinates": dict(provider_coordinates or {}),
        "response_fingerprint": response_fingerprint,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }

    mem = _load_memory(delivery_id)
    if mem is not None:
        # Replace same part_sequence if re-recorded.
        mem.chunks = [c for c in mem.chunks if c.get("part_sequence") != part_sequence]
        mem.chunks.append(chunk)
        mem.chunks.sort(key=lambda c: int(c.get("part_sequence") or 0))
        mem.part_sequence = int(part_sequence)
        mem.chunk_count = max(mem.chunk_count, len(mem.chunks), part_sequence + 1)
        if provider_message_id and not mem.provider_message_id:
            mem.provider_message_id = provider_message_id
        if provider_coordinates:
            coords = dict(mem.provider_coordinates)
            coords.setdefault("chunks", {})
            if isinstance(coords["chunks"], dict):
                coords["chunks"][str(part_sequence)] = dict(provider_coordinates)
            mem.provider_coordinates = coords
        return _update_memory(mem)

    conn = _db_conn()
    if conn is None:
        raise DeliveryGateError(f"delivery_not_found:{delivery_id}")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM communication_deliveries WHERE delivery_id = %s FOR UPDATE",
                (delivery_id,),
            )
            colnames = [d[0] for d in cur.description]
            fetched = cur.fetchone()
            if not fetched:
                conn.rollback()
                raise DeliveryGateError(f"delivery_not_found:{delivery_id}")
            mapped = dict(zip(colnames, fetched))
            for jsonb_key in ("reply_thread_coordinates", "provider_coordinates", "retry_policy"):
                val = mapped.get(jsonb_key)
                if isinstance(val, str):
                    mapped[jsonb_key] = json.loads(val)
            coords = dict(mapped.get("provider_coordinates") or {})
            chunks_meta = coords.get("chunks") if isinstance(coords.get("chunks"), dict) else {}
            chunks_meta = dict(chunks_meta)
            chunks_meta[str(part_sequence)] = {
                "provider_message_id": provider_message_id,
                "provider_coordinates": dict(provider_coordinates or {}),
                "response_fingerprint": response_fingerprint,
            }
            coords["chunks"] = chunks_meta
            chunk_count = max(
                int(mapped.get("chunk_count") or 1),
                len(chunks_meta),
                int(part_sequence) + 1,
            )
            cur.execute(
                """
                UPDATE communication_deliveries SET
                    part_sequence = %s,
                    chunk_count = %s,
                    provider_message_id = COALESCE(%s, provider_message_id),
                    provider_coordinates = %s::jsonb,
                    response_fingerprint = COALESCE(%s, response_fingerprint),
                    updated_at = now()
                WHERE delivery_id = %s
                RETURNING *
                """,
                (
                    int(part_sequence),
                    chunk_count,
                    provider_message_id,
                    json.dumps(coords),
                    response_fingerprint,
                    delivery_id,
                ),
            )
            colnames = [d[0] for d in cur.description]
            updated = cur.fetchone()
            conn.commit()
            mapped = dict(zip(colnames, updated))
            for jsonb_key in ("reply_thread_coordinates", "provider_coordinates", "retry_policy"):
                val = mapped.get(jsonb_key)
                if isinstance(val, str):
                    mapped[jsonb_key] = json.loads(val)
            result = _row_to_delivery(mapped, persisted="db")
            result.chunks = [
                {"part_sequence": int(k), **v} for k, v in sorted(chunks_meta.items(), key=lambda kv: int(kv[0]))
            ]
            return result
    except DeliveryGateError:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise DeliveryGateError(f"record_chunk_failed:{type(e).__name__}") from e


def memory_delivery_snapshot() -> dict[str, dict[str, Any]]:
    """Test helper: copy of in-memory delivery ledger."""
    with _lock:
        return {k: dict(v) for k, v in _MEM.items()}


def reset_memory_deliveries() -> None:
    """Test helper."""
    with _lock:
        _MEM.clear()
        _MEM_BY_IDEMPOTENCY.clear()
        _MEM_BY_EVENT_CHANNEL_ATTEMPT.clear()
