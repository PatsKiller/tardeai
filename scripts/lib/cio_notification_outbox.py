"""
CIO Notification Outbox — Durable append-only event store for operator notifications.

This is a LAB service (P-1.7). The event log is authoritative; projections are
derived and rebuildable via in-memory replay. No mutation of prior records.
Hash-chained with SHA-256. Lease-safe with claim tokens.

Supports channels: telegram, command_center.
Separates outbound operator notification delivery from inbound operator messaging.
ZERO provider calls. ZERO live Telegram sends. ZERO production activation.

Dependencies: Primitive serialization/hashing functions (canonicalize_payload,
compute_payload_hash, compute_event_hash, build_event) are replicated from
scripts/lib/cio_action_ledger.py (P-1.3) with identical semantics.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════
# Replicated primitives (identical semantics to P-1.3 cio_action_ledger.py)
# ═══════════════════════════════════════════════════════════════════════════════


def canonicalize_payload(payload: dict[str, Any]) -> str:
    """Deterministic JSON serialization: sorted keys, compact, no trailing whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_payload_hash(payload: dict[str, Any]) -> str:
    """SHA-256 hash of the canonicalized payload."""
    return hashlib.sha256(canonicalize_payload(payload).encode("utf-8")).hexdigest()


def compute_event_hash(envelope_without_hash: dict[str, Any]) -> str:
    """SHA-256 hash of the full event envelope (excluding event_hash itself)."""
    canonical = canonicalize_payload(envelope_without_hash)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# Message Classes
# ═══════════════════════════════════════════════════════════════════════════════

MESSAGE_CLASSES = frozenset({
    "advisory", "alert", "status", "checkin", "confirmation_request",
    "data_quality_block", "data_quality_recovered", "followup_due",
    "specialist_complete", "system_notice",
})

FORBIDDEN_MESSAGE_CLASSES = frozenset({
    "execute_trade", "order_submission", "risk_override",
    "2fa_code", "credential_request", "secret_delivery",
})

# ═══════════════════════════════════════════════════════════════════════════════
# Severity
# ═══════════════════════════════════════════════════════════════════════════════

SEVERITY_LEVELS = frozenset({"P0", "P1", "P2", "INFO"})

# ═══════════════════════════════════════════════════════════════════════════════
# Channels
# ═══════════════════════════════════════════════════════════════════════════════

SUPPORTED_CHANNELS = frozenset({"telegram", "command_center"})

# ═══════════════════════════════════════════════════════════════════════════════
# Event Types
# ═══════════════════════════════════════════════════════════════════════════════

VALID_EVENT_TYPES = frozenset({
    "NOTIFICATION_ENQUEUED", "DELIVERY_CLAIMED", "DELIVERY_ATTEMPTED",
    "DELIVERY_CONFIRMED", "DELIVERY_RETRY_SCHEDULED", "DELIVERY_RELEASED",
    "NOTIFICATION_EXPIRED", "NOTIFICATION_CANCELLED", "NOTIFICATION_DEAD_LETTERED",
    "NOTIFICATION_OUTBOX_GENESIS",
})

STATUS_EVENTS: dict[str, str] = {
    "NOTIFICATION_ENQUEUED": "PENDING",
    "DELIVERY_CLAIMED": "CLAIMED",
    "DELIVERY_ATTEMPTED": "DELIVERING",
    "DELIVERY_CONFIRMED": "DELIVERED",
    "DELIVERY_RETRY_SCHEDULED": "RETRY_SCHEDULED",
    "DELIVERY_RELEASED": "PENDING",
    "NOTIFICATION_EXPIRED": "EXPIRED",
    "NOTIFICATION_CANCELLED": "CANCELLED",
    "NOTIFICATION_DEAD_LETTERED": "DEAD_LETTERED",
}

STATE_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"CLAIMED", "EXPIRED", "CANCELLED", "DEAD_LETTERED"},
    "CLAIMED": {"DELIVERING", "PENDING", "EXPIRED", "CANCELLED", "DEAD_LETTERED", "DELIVERED"},
    "DELIVERING": {"DELIVERED", "RETRY_SCHEDULED", "DEAD_LETTERED", "PENDING"},
    "RETRY_SCHEDULED": {"PENDING", "EXPIRED", "CANCELLED", "DEAD_LETTERED"},
}

TERMINAL_STATUSES = frozenset({"DELIVERED", "EXPIRED", "CANCELLED", "DEAD_LETTERED"})

# ═══════════════════════════════════════════════════════════════════════════════
# Retry Policy
# ═══════════════════════════════════════════════════════════════════════════════

RETRY_BACKOFF_SECONDS = [30, 120, 600]  # 30s, 2m, 10m
MAX_RETRY_ATTEMPTS = 3  # after 3 attempts -> DEAD_LETTERED
LEASE_DURATION_SECONDS = 60

GENESIS_PREV_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

ALLOWED_ACTOR_TYPES = frozenset({"agent", "operator", "system"})

# ═══════════════════════════════════════════════════════════════════════════════
# Valid deep-link schemes
# ═══════════════════════════════════════════════════════════════════════════════

ALLOWED_DEEP_LINK_SCHEMES = frozenset({"http", "https", "cmd-center", ""})


# ═══════════════════════════════════════════════════════════════════════════════
# Semantic dedupe
# ═══════════════════════════════════════════════════════════════════════════════


def _parse_occurred(stamp: Any) -> "datetime | None":
    if not isinstance(stamp, str):
        return None
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def build_dedupe_key(notification: dict[str, Any]) -> str:
    """Build semantic dedupe key from source references.

    Phase 9: prefer InvestmentDecision / CIO decision_id + material state so the
    same unchanged decision does not re-page; notification_id alone is not enough.
    """
    parts: list[str] = []
    # Phase 8/9 decision identity (preferred)
    did = (
        notification.get("decision_id")
        or notification.get("investment_decision_id")
        or (notification.get("payload") or {}).get("decision_id")
    )
    # A check-in carries no decision identity, so the only distinguishing part
    # left was `wake_job_id` -- a fresh run id every run. Three runs with a
    # byte-identical body therefore produced three different keys and three
    # identical Telegrams (observed 2026-08-27). For this class the semantic
    # event is the CONTENT, not the run that emitted it. Suppression is bounded
    # by `dedupe_window_hours`, so an unchanged daily brief still arrives daily.
    if not did and notification.get("message_class") == "checkin" and notification.get("body_hash"):
        return hashlib.sha256(
            f"checkin:{notification['body_hash']}".encode()
        ).hexdigest()[:32]

    if did:
        parts.append(f"decision:{did}")
        state = (
            notification.get("material_state")
            or (notification.get("payload") or {}).get("material_state")
            or ""
        )
        if state:
            parts.append(f"state:{state}")
    if notification.get("cio_action_id"):
        parts.append(f"action:{notification['cio_action_id']}")
    if notification.get("wake_job_id"):
        parts.append(f"wake:{notification['wake_job_id']}")
    if notification.get("handoff_id"):
        parts.append(f"handoff:{notification['handoff_id']}")
    if notification.get("health_decision_id"):
        parts.append(f"health:{notification['health_decision_id']}")
    parts.append(f"class:{notification.get('message_class', '')}")
    return hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()[:32]


# ═══════════════════════════════════════════════════════════════════════════════
# Priority / Severity mapping
# ═══════════════════════════════════════════════════════════════════════════════


def determine_severity(message_class: str, priority: str = "normal") -> str:
    """Map message_class + optional priority to severity level."""
    mapping: dict[str, str] = {
        "data_quality_block": "P0",
        "alert": "P1",
        "confirmation_request": "P1",
        "advisory": "P2",
        "followup_due": "P2",
        "specialist_complete": "P2",
        "checkin": "INFO",
        "status": "INFO",
        "system_notice": "INFO",
    }
    return mapping.get(message_class, "INFO")


# ═══════════════════════════════════════════════════════════════════════════════
# Event builder (replicated with parameterized validation)
# ═══════════════════════════════════════════════════════════════════════════════


def build_event(
    event_type: str,
    stream_id: str,
    payload: dict[str, Any],
    actor_type: str,
    actor_id: str,
    authority: str,
    prev_event_hash: str,
    metadata: dict[str, Any] | None = None,
    schema_version: str = "1.0.0",
) -> dict[str, Any]:
    """Build a fully-hashed event envelope.

    The event_id includes a microsecond-resolution timestamp prefix for
    total ordering, followed by a random hex suffix for uniqueness.
    """
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Invalid event_type: {event_type}")

    if actor_type not in ALLOWED_ACTOR_TYPES:
        raise ValueError(f"Invalid actor_type: {actor_type}")

    occurred_at = datetime.now(timezone.utc).isoformat()
    event_id = f"{int(time.time() * 1_000_000):020d}-{uuid.uuid4().hex[:12]}"

    payload_hash = compute_payload_hash(payload)

    envelope: dict[str, Any] = {
        "schema_version": schema_version,
        "event_id": event_id,
        "stream_id": stream_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "authority": authority,
        "prev_event_hash": prev_event_hash,
        "payload_hash": payload_hash,
        "payload": payload,
        "metadata": metadata or {},
    }

    envelope["event_hash"] = compute_event_hash(envelope)
    return envelope


# ═══════════════════════════════════════════════════════════════════════════════
# Fake Delivery Adapter
# ═══════════════════════════════════════════════════════════════════════════════


class FakeDeliveryAdapter:
    """Fake adapter for testing — does NOT make real Telegram calls."""

    def __init__(
        self,
        should_fail: bool = False,
        fail_count: int = 0,
        should_timeout: bool = False,
    ):
        self.should_fail = should_fail
        self.fail_count = fail_count
        self.should_timeout = should_timeout
        self.attempts = 0
        self.sent_messages: list[dict[str, Any]] = []
        self.last_external_id = 0

    def deliver(
        self, notification: dict[str, Any], channel: str, claim_token: str
    ) -> dict[str, Any]:
        """Simulate delivery attempt.

        Returns a dict with success, and optionally external_message_id
        and transport_receipt_hash on success, or error/error_class on failure.
        """
        self.attempts += 1

        if self.should_timeout:
            return {"success": False, "error": "timeout", "error_class": "TIMEOUT"}

        if self.should_fail and self.attempts <= self.fail_count:
            return {
                "success": False,
                "error": "connection_error",
                "error_class": "CONNECTION_ERROR",
            }

        self.last_external_id += 1
        ext_id = f"ext-msg-{self.last_external_id}"
        self.sent_messages.append({
            "notification_id": notification.get("notification_id"),
            "channel": channel,
            "external_id": ext_id,
            "body_hash": notification.get("body_hash"),
        })

        return {
            "success": True,
            "external_message_id": ext_id,
            "transport_receipt_hash": hashlib.sha256(
                ext_id.encode()
            ).hexdigest()[:32],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Notification Outbox
# ═══════════════════════════════════════════════════════════════════════════════


class NotificationOutbox:
    """Deterministic append-only Notification Outbox backed by a JSONL file.

    Every write is wrapped in fcntl exclusive lock + fsync. The event log is
    authoritative; projections are derived on read via replay.
    """

    def __init__(self, event_store_path: Path | None = None):
        if event_store_path is None:
            event_store_path = (
                Path(__file__).resolve().parent.parent.parent
                / "data"
                / "cio"
                / "operator_notification_outbox.jsonl"
            )
        self.event_store_path = Path(event_store_path)
        self.event_store_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = Path(str(event_store_path) + ".lock")

        if (
            not self.event_store_path.exists()
            or self.event_store_path.stat().st_size == 0
        ):
            self._initialize_genesis()

    # ── Locking ────────────────────────────────────────────────────────────

    def _acquire_lock(self) -> int:
        """Acquire an exclusive (write) lock on the outbox lock file."""
        lock_fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return lock_fd

    def _release_lock(self, lock_fd: int) -> None:
        """Release the lock and close the file descriptor."""
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

    # ── Genesis ────────────────────────────────────────────────────────────

    def _initialize_genesis(self) -> None:
        """Create the genesis event if the outbox is empty."""
        genesis = build_event(
            event_type="NOTIFICATION_OUTBOX_GENESIS",
            stream_id="outbox-genesis",
            payload={
                "message": "CIO Notification Outbox initialized",
                "schema_version": "1.0.0",
            },
            actor_type="system",
            actor_id="p1_7_init",
            authority="system",
            prev_event_hash=GENESIS_PREV_HASH,
        )
        self._append_event(genesis)

    # ── Low-level event store ──────────────────────────────────────────────

    def _get_last_event(self) -> dict[str, Any] | None:
        """Return the most recent event in the outbox, or None if empty."""
        if not self.event_store_path.exists():
            return None
        with open(self.event_store_path, "r") as f:
            lines = f.readlines()
            if not lines:
                return None
            return json.loads(lines[-1].strip())

    def _get_last_event_hash(self) -> str:
        """Return the event_hash of the last event, or the genesis null hash."""
        last = self._get_last_event()
        if last is None:
            return GENESIS_PREV_HASH
        return last["event_hash"]

    def _append_event(self, event: dict[str, Any]) -> None:
        """Append ONE event with exclusive lock, hash-chain continuity, and fsync."""
        lock_fd = self._acquire_lock()
        try:
            self._raw_append_locked(event)
        finally:
            self._release_lock(lock_fd)

    def _raw_append_locked(self, event: dict[str, Any]) -> None:
        """Append ONE event under an already-held exclusive lock."""
        current_head_hash = self._get_last_event_hash()
        event["prev_event_hash"] = current_head_hash

        # Recompute event_hash with the authoritative prev_event_hash
        event_without_hash = {
            k: v for k, v in event.items() if k != "event_hash"
        }
        event["event_hash"] = compute_event_hash(event_without_hash)

        line = json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n"

        with open(self.event_store_path, "a") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    # ── Stream reading ─────────────────────────────────────────────────────

    def _get_stream_events(self, stream_id: str) -> list[dict[str, Any]]:
        """Return all events for a given notification stream, in insertion order."""
        events: list[dict[str, Any]] = []
        if not self.event_store_path.exists():
            return events
        with open(self.event_store_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                event = json.loads(stripped)
                if event["stream_id"] == stream_id:
                    events.append(event)
        return events

    # ── Idempotency ────────────────────────────────────────────────────────

    def _iter_all_events(self):
        """Yield every event in the outbox across all streams, in append order.

        Skips malformed lines so a corrupt tail record can never break the
        dedupe/idempotency guard (fail-safe: we still return existing matches).
        """
        if not self.event_store_path.exists():
            return
        with open(self.event_store_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    yield json.loads(stripped)
                except json.JSONDecodeError:
                    continue

    def _check_idempotency(
        self, idempotency_key: str, stream_id: str | None = None
    ) -> dict[str, Any] | None:
        """Check if a notification with the same idempotency_key already exists.

        Searches globally across all streams (not just `stream_id`). Idempotency
        keys are producer-scoped and must be unique across the outbox, so a
        cross-stream lookup is the stronger guard against two producers enqueueing
        different `notification_id`s for the same operation.
        """
        if not idempotency_key:
            return None
        for e in self._iter_all_events():
            if e.get("payload", {}).get("idempotency_key") == idempotency_key:
                return e
        return None

    def _check_dedupe(
        self, dedupe_key: str, stream_id: str | None = None,
        window_hours: float | None = None,
    ) -> dict[str, Any] | None:
        """Check if a semantically-identical notification already exists.

        Searches globally across all streams (not just `stream_id`) so two
        producers that enqueue different `notification_id`s for the same semantic
        event (same `dedupe_key`) collapse to a single notification.

        `window_hours` bounds how far back a match counts. Without it the search
        is unbounded, which is right for a decision-keyed notification (the same
        decision should never re-page) but wrong for a content-keyed check-in:
        an unchanged daily brief would match its own first send forever and the
        operator would hear nothing again. Absent = previous behaviour.
        """
        if not dedupe_key:
            return None
        cutoff = None
        if window_hours is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        for e in self._iter_all_events():
            payload = e.get("payload", {})
            if payload.get("dedupe_key") != dedupe_key and \
               payload.get("idempotency_key") != dedupe_key:
                continue
            if cutoff is not None:
                occurred = _parse_occurred(e.get("occurred_at"))
                # An unreadable stamp must not silently widen the window into
                # unbounded suppression; treat it as outside and keep looking.
                if occurred is None or occurred < cutoff:
                    continue
            return e
        return None

    # ── Projection Replay ──────────────────────────────────────────────────

    def _replay_state(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Rebuild current notification state by folding over the event stream."""
        state: dict[str, Any] = {
            "notification_id": None,
            "current_status": None,
            "event_count": 0,
            "last_event_id": None,
            "last_event_hash": None,
            "attempt_number": 0,
            "external_message_id": None,
            "transport_receipt_hash": None,
            "retry_after": None,
            "dead_letter_reason": None,
        }

        for event in events:
            state["event_count"] += 1
            state["last_event_id"] = event["event_id"]
            state["last_event_hash"] = event["event_hash"]

            event_type = event["event_type"]
            payload = event.get("payload", {})

            if event_type == "NOTIFICATION_ENQUEUED":
                state.update({
                    "notification_id": payload.get("notification_id"),
                    "current_status": "PENDING",
                    "message_class": payload.get("message_class"),
                    "severity": payload.get("severity"),
                    "channel_targets": list(payload.get("channel_targets", [])),
                    "subject": payload.get("subject"),
                    "body": payload.get("body"),
                    "body_hash": payload.get("body_hash"),
                    "created_at": payload.get("created_at", event["occurred_at"]),
                    "expires_at": payload.get("expires_at"),
                    "dedupe_key": payload.get("dedupe_key"),
                    "cio_action_id": payload.get("cio_action_id"),
                    "wake_job_id": payload.get("wake_job_id"),
                    "handoff_id": payload.get("handoff_id"),
                    "health_decision_id": payload.get("health_decision_id"),
                    "deep_link": payload.get("deep_link"),
                    "reply_markup": payload.get("reply_markup"),
                    "object_id": payload.get("object_id"),
                    "symbol": payload.get("symbol"),
                    "card_schema": payload.get("card_schema"),
                    "parse_mode": payload.get("parse_mode"),
                    "claim_token": None,
                    "claim_worker_id": None,
                    "lease_expires_at": None,
                    "external_message_id": None,
                    "transport_receipt_hash": None,
                })

            elif event_type == "DELIVERY_CLAIMED":
                state["current_status"] = "CLAIMED"
                state["claim_token"] = payload.get("claim_token")
                state["claim_worker_id"] = payload.get("worker_id")
                state["lease_expires_at"] = payload.get("lease_expires_at")
                state.setdefault("attempt_number", 0)

            elif event_type == "DELIVERY_ATTEMPTED":
                state["current_status"] = "DELIVERING"
                state["attempt_number"] = payload.get(
                    "attempt_number",
                    state.get("attempt_number", 0),
                )

            elif event_type == "DELIVERY_CONFIRMED":
                state["current_status"] = "DELIVERED"
                state["external_message_id"] = payload.get("external_message_id")
                state["transport_receipt_hash"] = payload.get(
                    "transport_receipt_hash"
                )

            elif event_type == "DELIVERY_RETRY_SCHEDULED":
                state["current_status"] = "RETRY_SCHEDULED"
                state["attempt_number"] = payload.get(
                    "attempt_number",
                    state.get("attempt_number", 0) + 1,
                )
                state["retry_after"] = payload.get("retry_after")

            elif event_type == "DELIVERY_RELEASED":
                state["current_status"] = "PENDING"
                state["claim_token"] = None
                state["claim_worker_id"] = None
                state["lease_expires_at"] = None

            elif event_type == "NOTIFICATION_EXPIRED":
                state["current_status"] = "EXPIRED"

            elif event_type == "NOTIFICATION_CANCELLED":
                state["current_status"] = "CANCELLED"

            elif event_type == "NOTIFICATION_DEAD_LETTERED":
                state["current_status"] = "DEAD_LETTERED"
                state["dead_letter_reason"] = payload.get("reason")

        return state

    # ── Validation ─────────────────────────────────────────────────────────

    def _validate_enqueue(self, notification: dict[str, Any]) -> None:
        """Validate a notification before enqueueing."""
        required = [
            "notification_id", "message_class", "channel_targets",
            "subject", "body", "body_hash",
        ]
        for field in required:
            if field not in notification:
                raise ValueError(f"Missing required field: {field}")

        # Validate message_class
        msg_class = notification["message_class"]
        if msg_class in FORBIDDEN_MESSAGE_CLASSES:
            raise ValueError(
                f"Forbidden message_class: {msg_class}. "
                f"Execution/credential messages are not allowed in the outbox."
            )
        if msg_class not in MESSAGE_CLASSES:
            raise ValueError(
                f"Invalid message_class: {msg_class}. "
                f"Must be one of: {sorted(MESSAGE_CLASSES)}"
            )

        # Validate severity
        severity = notification.get("severity")
        if severity and severity not in SEVERITY_LEVELS:
            raise ValueError(
                f"Invalid severity: {severity}. Must be one of: {sorted(SEVERITY_LEVELS)}"
            )

        # Validate channels
        channels = notification.get("channel_targets", [])
        for ch in channels:
            if ch not in SUPPORTED_CHANNELS:
                raise ValueError(
                    f"Unsupported channel: {ch}. "
                    f"Must be one of: {sorted(SUPPORTED_CHANNELS)}"
                )

        # Validate body_hash matches body
        expected_body_hash = hashlib.sha256(
            notification["body"].encode("utf-8")
        ).hexdigest()
        if notification["body_hash"] != expected_body_hash:
            raise ValueError(
                f"body_hash mismatch: expected {expected_body_hash}, "
                f"got {notification['body_hash']}"
            )

        # Validate deep_link scheme if present
        deep_link = notification.get("deep_link", "")
        if deep_link:
            scheme = deep_link.split("://")[0] if "://" in deep_link else ""
            if scheme not in ALLOWED_DEEP_LINK_SCHEMES and scheme != "":
                raise ValueError(
                    f"Invalid deep_link scheme: {scheme}. "
                    f"Allowed: {sorted(ALLOWED_DEEP_LINK_SCHEMES)}"
                )
            # Block javascript: and other dangerous schemes
            if ":" in deep_link and "://" not in deep_link:
                raise ValueError(f"Invalid deep_link format: {deep_link}")

        # Check notification_id is not already used
        existing = self.get_notification(notification["notification_id"])
        if existing is not None:
            raise ValueError(
                f"Notification already exists: {notification['notification_id']}"
            )

    def _get_current_state(self, notification_id: str) -> dict[str, Any]:
        """Get the current projection state for a notification."""
        current = self.get_notification(notification_id)
        if current is None:
            raise ValueError(f"Notification not found: {notification_id}")
        return current

    def _validate_transition(
        self,
        notification_id: str,
        current_status: str,
        target_status: str,
    ) -> None:
        """Validate that a state transition is legal."""
        if current_status in TERMINAL_STATUSES:
            raise ValueError(
                f"Notification {notification_id} is in terminal state {current_status}"
            )

        allowed = STATE_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            raise ValueError(
                f"Invalid transition: {current_status} -> {target_status}"
            )

    # ── Core domain operations ─────────────────────────────────────────────

    def enqueue(
        self,
        notification: dict[str, Any],
        actor_id: str,
        actor_type: str = "agent",
        authority: str = "advisory",
    ) -> dict[str, Any]:
        """Enqueue a notification for delivery.

        Required fields in notification dict:
          - notification_id, message_class, channel_targets, subject, body, body_hash
        Optional fields:
          - severity (auto-determined if absent), created_at, expires_at,
            dedupe_key, cio_action_id, wake_job_id, handoff_id,
            health_decision_id, deep_link, idempotency_key, priority,
            reply_markup (Telegram inline keyboard), object_id, symbol, card_schema,
            parse_mode (optional Telegram parse mode, e.g. ``HTML``)
        """
        # Guard: validate dict shape before accessing fields to avoid KeyErrors
        if not isinstance(notification, dict):
            raise ValueError("notification must be a dict")
        if "notification_id" not in notification or "message_class" not in notification:
            self._validate_enqueue(notification)
            # Unreachable — _validate_enqueue always raises on missing fields
            raise ValueError("Missing required fields")

        # Auto-determine severity if not set
        if "severity" not in notification:
            notification["severity"] = determine_severity(
                notification["message_class"],
                notification.get("priority", "normal"),
            )

        # Build dedupe key if not provided
        if "dedupe_key" not in notification or not notification.get("dedupe_key"):
            notification["dedupe_key"] = build_dedupe_key(notification)

        # Idempotency guard — check BEFORE validation (global cross-stream)
        idempotency_key = str(notification.get("idempotency_key", ""))
        if idempotency_key:
            existing = self._check_idempotency(idempotency_key)
            if existing is not None:
                return existing

        # Dedupe guard — check if semantically identical notification exists
        dedupe_key = notification.get("dedupe_key", "")
        if dedupe_key:
            existing_dedupe = self._check_dedupe(
                dedupe_key,
                window_hours=notification.get("dedupe_window_hours"),
            )
            if existing_dedupe is not None:
                return existing_dedupe

        self._validate_enqueue(notification)

        # Set defaults
        if "created_at" not in notification:
            notification["created_at"] = datetime.now(timezone.utc).isoformat()
        if "expires_at" not in notification:
            notification["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(hours=24)
            ).isoformat()

        payload: dict[str, Any] = {
            "notification_id": notification["notification_id"],
            "message_class": notification["message_class"],
            "severity": notification["severity"],
            "channel_targets": list(notification.get("channel_targets", [])),
            "subject": notification["subject"],
            "body": notification["body"],
            "body_hash": notification["body_hash"],
            "created_at": notification.get(
                "created_at", datetime.now(timezone.utc).isoformat()
            ),
            "expires_at": notification.get("expires_at"),
            "dedupe_key": notification.get("dedupe_key"),
            "cio_action_id": notification.get("cio_action_id"),
            "wake_job_id": notification.get("wake_job_id"),
            "handoff_id": notification.get("handoff_id"),
            "health_decision_id": notification.get("health_decision_id"),
            "deep_link": notification.get("deep_link"),
            "idempotency_key": idempotency_key,
        }
        # Optional Telegram inline keyboard (IIC / decision URL buttons).
        if notification.get("reply_markup") is not None:
            payload["reply_markup"] = notification.get("reply_markup")
        if notification.get("object_id") is not None:
            payload["object_id"] = notification.get("object_id")
        if notification.get("symbol") is not None:
            payload["symbol"] = notification.get("symbol")
        if notification.get("card_schema") is not None:
            payload["card_schema"] = notification.get("card_schema")
        # Optional Telegram parse_mode (IIC HTML cards / book digest).
        if notification.get("parse_mode") is not None:
            payload["parse_mode"] = notification.get("parse_mode")

        event = build_event(
            event_type="NOTIFICATION_ENQUEUED",
            stream_id=notification["notification_id"],
            payload=payload,
            actor_type=actor_type,
            actor_id=actor_id,
            authority=authority,
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    def claim(
        self,
        notification_id: str,
        channel: str,
        worker_id: str,
        claim_token: str,
    ) -> dict[str, Any]:
        """Claim a notification for delivery by a worker.

        Validates the channel, checks expiry, and records a DELIVERY_CLAIMED event.
        Only one worker can hold a claim at a time. All checks happen under lock.
        """
        if channel not in SUPPORTED_CHANNELS:
            raise ValueError(
                f"Unsupported channel: {channel}"
            )

        lock_fd = self._acquire_lock()
        try:
            # Re-read state under lock to prevent TOCTOU races
            current = self._get_current_state(notification_id)
            current_status = current.get("current_status", "")

            # Check expiry
            expires_at_str = current.get("expires_at")
            if expires_at_str:
                try:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    if datetime.now(timezone.utc) > expires_at:
                        raise ValueError(
                            f"Notification {notification_id} has expired"
                        )
                except ValueError as ve:
                    if "expired" in str(ve).lower():
                        raise
                    raise ValueError(
                            f"Notification {notification_id} has expired "
                            f"(at {expires_at_str})"
                        )

            # Check if already claimed and lease not stale
            if current_status == "CLAIMED":
                lease_str = current.get("lease_expires_at")
                if lease_str:
                    try:
                        lease_expires = datetime.fromisoformat(lease_str)
                        if datetime.now(timezone.utc) < lease_expires:
                            raise ValueError(
                                f"Notification {notification_id} already claimed "
                                f"by {current.get('claim_worker_id')}"
                            )
                    except ValueError as ve:
                        if "already claimed" in str(ve):
                            raise
                # Lease expired — allow reclaim

            self._validate_transition(notification_id, current_status, "CLAIMED")

            lease_expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=LEASE_DURATION_SECONDS)
            ).isoformat()

            payload: dict[str, Any] = {
                "notification_id": notification_id,
                "channel": channel,
                "worker_id": worker_id,
                "claim_token": claim_token,
                "lease_expires_at": lease_expires_at,
            }

            event = build_event(
                event_type="DELIVERY_CLAIMED",
                stream_id=notification_id,
                payload=payload,
                actor_type="system",
                actor_id=worker_id,
                authority="delivery",
                prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
            )

            self._raw_append_locked(event)
            return event
        finally:
            self._release_lock(lock_fd)

    def _verify_claim_token(
        self, notification_id: str, claim_token: str
    ) -> None:
        """Verify that a claim token matches the current claim."""
        current = self.get_notification(notification_id)
        if current is None:
            raise ValueError(f"Notification not found: {notification_id}")
        current_token = current.get("claim_token")
        if current_token is None:
            raise ValueError(
                f"Notification {notification_id} is not claimed"
            )
        if current_token != claim_token:
            raise ValueError(
                f"Wrong claim token for {notification_id}"
            )

    def attempt(
        self,
        notification_id: str,
        channel: str,
        claim_token: str,
        worker_id: str,
    ) -> dict[str, Any]:
        """Record a delivery attempt.

        Must hold a valid claim token. Moves state to DELIVERING.
        """
        self._verify_claim_token(notification_id, claim_token)
        current = self._get_current_state(notification_id)
        current_status = current.get("current_status", "")

        self._validate_transition(notification_id, current_status, "DELIVERING")

        payload: dict[str, Any] = {
            "notification_id": notification_id,
            "channel": channel,
            "worker_id": worker_id,
            "attempt_number": current.get("attempt_number", 0) + 1,
        }

        event = build_event(
            event_type="DELIVERY_ATTEMPTED",
            stream_id=notification_id,
            payload=payload,
            actor_type="system",
            actor_id=worker_id,
            authority="delivery",
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    def confirm(
        self,
        notification_id: str,
        channel: str,
        claim_token: str,
        worker_id: str,
        external_message_id: str,
        transport_receipt_hash: str,
    ) -> dict[str, Any]:
        """Confirm successful delivery.

        Records the external delivery receipt. Moves state to DELIVERED (terminal).
        """
        self._verify_claim_token(notification_id, claim_token)
        current = self._get_current_state(notification_id)
        current_status = current.get("current_status", "")

        self._validate_transition(notification_id, current_status, "DELIVERED")

        payload: dict[str, Any] = {
            "notification_id": notification_id,
            "channel": channel,
            "worker_id": worker_id,
            "external_message_id": external_message_id,
            "transport_receipt_hash": transport_receipt_hash,
        }

        event = build_event(
            event_type="DELIVERY_CONFIRMED",
            stream_id=notification_id,
            payload=payload,
            actor_type="system",
            actor_id=worker_id,
            authority="delivery",
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    def retry(
        self,
        notification_id: str,
        channel: str,
        failure_code: str,
        worker_id: str,
        claim_token: str,
    ) -> dict[str, Any]:
        """Schedule a retry after a failed delivery attempt.

        If attempt_number >= MAX_RETRY_ATTEMPTS, dead-letters instead.
        """
        self._verify_claim_token(notification_id, claim_token)
        current = self._get_current_state(notification_id)

        # attempt_number was already incremented by attempt()
        attempt_number = current.get("attempt_number", 0)

        # If exhausted retries, dead-letter instead
        if attempt_number >= MAX_RETRY_ATTEMPTS:
            return self.dead_letter(
                notification_id, channel,
                f"Retry limit exhausted after {attempt_number} attempts. Last failure: {failure_code}"
            )

        current_status = current.get("current_status", "")
        self._validate_transition(
            notification_id, current_status, "RETRY_SCHEDULED"
        )

        # Determine backoff
        backoff_idx = min(attempt_number, len(RETRY_BACKOFF_SECONDS)) - 1
        backoff_seconds = RETRY_BACKOFF_SECONDS[backoff_idx]
        retry_after = (
            datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
        ).isoformat()

        payload: dict[str, Any] = {
            "notification_id": notification_id,
            "channel": channel,
            "worker_id": worker_id,
            "failure_code": failure_code,
            "attempt_number": attempt_number,
            "retry_after": retry_after,
            "backoff_seconds": backoff_seconds,
        }

        event = build_event(
            event_type="DELIVERY_RETRY_SCHEDULED",
            stream_id=notification_id,
            payload=payload,
            actor_type="system",
            actor_id=worker_id,
            authority="delivery",
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    def release(
        self,
        notification_id: str,
        channel: str,
        claim_token: str,
        worker_id: str,
    ) -> dict[str, Any]:
        """Release a claim, making the notification available for another worker."""
        # Release should work even from RETRY_SCHEDULED or CLAIMED states
        current = self._get_current_state(notification_id)
        current_status = current.get("current_status", "")

        # RETRY_SCHEDULED can also be released back to PENDING
        if current_status == "RETRY_SCHEDULED":
            allowed = {"PENDING", "EXPIRED", "CANCELLED", "DEAD_LETTERED"}
            if current_status in TERMINAL_STATUSES:
                raise ValueError(
                    f"Notification {notification_id} is in terminal state {current_status}"
                )
        else:
            try:
                self._verify_claim_token(notification_id, claim_token)
            except ValueError:
                # Allow release of expired claims
                pass

            self._validate_transition(notification_id, current_status, "PENDING")

        payload: dict[str, Any] = {
            "notification_id": notification_id,
            "channel": channel,
            "worker_id": worker_id,
        }

        event = build_event(
            event_type="DELIVERY_RELEASED",
            stream_id=notification_id,
            payload=payload,
            actor_type="system",
            actor_id=worker_id,
            authority="delivery",
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    def expire(
        self,
        notification_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """Mark a notification as expired."""
        current = self._get_current_state(notification_id)
        current_status = current.get("current_status", "")

        self._validate_transition(notification_id, current_status, "EXPIRED")

        payload: dict[str, Any] = {
            "notification_id": notification_id,
            "reason": reason,
        }

        event = build_event(
            event_type="NOTIFICATION_EXPIRED",
            stream_id=notification_id,
            payload=payload,
            actor_type="system",
            actor_id="expiry_worker",
            authority="system",
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    def cancel(
        self,
        notification_id: str,
        reason: str,
        actor_id: str,
        actor_type: str = "operator",
    ) -> dict[str, Any]:
        """Cancel a pending notification."""
        current = self._get_current_state(notification_id)
        current_status = current.get("current_status", "")

        self._validate_transition(notification_id, current_status, "CANCELLED")

        payload: dict[str, Any] = {
            "notification_id": notification_id,
            "reason": reason,
        }

        event = build_event(
            event_type="NOTIFICATION_CANCELLED",
            stream_id=notification_id,
            payload=payload,
            actor_type=actor_type,
            actor_id=actor_id,
            authority="operator",
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    def dead_letter(
        self,
        notification_id: str,
        channel: str,
        reason: str,
    ) -> dict[str, Any]:
        """Move a notification to the dead-letter queue."""
        current = self._get_current_state(notification_id)
        current_status = current.get("current_status", "")

        if current_status not in ("CLAIMED", "DELIVERING", "RETRY_SCHEDULED", "PENDING"):
            if current_status in TERMINAL_STATUSES:
                raise ValueError(
                    f"Notification {notification_id} is in terminal state {current_status}"
                )
            raise ValueError(
                f"Cannot dead-letter notification in state {current_status}"
            )

        payload: dict[str, Any] = {
            "notification_id": notification_id,
            "channel": channel,
            "reason": reason,
        }

        event = build_event(
            event_type="NOTIFICATION_DEAD_LETTERED",
            stream_id=notification_id,
            payload=payload,
            actor_type="system",
            actor_id="dead_letter_worker",
            authority="system",
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    # ── Read APIs (projection via replay) ──────────────────────────────────

    def get_notification(self, notification_id: str) -> dict[str, Any] | None:
        """Rebuild the current state of a notification from its event stream."""
        events = self._get_stream_events(notification_id)
        if not events:
            return None
        return self._replay_state(events)

    def list_notifications(
        self,
        status: str | None = None,
        channel: str | None = None,
        message_class: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List notifications, optionally filtered."""
        stream_ids: set[str] = set()
        if self.event_store_path.exists():
            with open(self.event_store_path, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    event = json.loads(stripped)
                    sid = event["stream_id"]
                    if sid != "outbox-genesis":
                        stream_ids.add(sid)

        notifications: list[dict[str, Any]] = []
        for sid in stream_ids:
            n = self.get_notification(sid)
            if n is None:
                continue
            if status is not None and n.get("current_status") != status:
                continue
            if channel is not None and channel not in (
                n.get("channel_targets") or []
            ):
                continue
            if message_class is not None and n.get("message_class") != message_class:
                continue
            notifications.append(n)

        notifications.sort(
            key=lambda n: str(n.get("created_at", "")), reverse=True
        )
        return notifications[:limit]

    def list_dead_lettered(self, limit: int = 50) -> list[dict[str, Any]]:
        """List all dead-lettered notifications."""
        return self.list_notifications(status="DEAD_LETTERED", limit=limit)

    # ── Integrity verification ─────────────────────────────────────────────

    def verify_integrity(self) -> dict[str, Any]:
        """Verify the entire outbox's hash chain, payload hashes, and event hashes."""
        result: dict[str, Any] = {
            "valid": True,
            "total_events": 0,
            "valid_events": 0,
            "corrupt_events": [],
            "chain_breaks": [],
        }

        if (
            not self.event_store_path.exists()
            or self.event_store_path.stat().st_size == 0
        ):
            return result

        prev_hash: str | None = None

        with open(self.event_store_path, "r") as f:
            for line_num, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped:
                    continue

                result["total_events"] += 1

                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError:
                    result["corrupt_events"].append(
                        {"line": line_num, "reason": "invalid_json"}
                    )
                    result["valid"] = False
                    continue

                # Verify payload hash
                if "payload" in event and "payload_hash" in event:
                    computed_ph = compute_payload_hash(event["payload"])
                    if computed_ph != event["payload_hash"]:
                        result["corrupt_events"].append({
                            "line": line_num,
                            "reason": "payload_hash_mismatch",
                            "expected": event["payload_hash"],
                            "computed": computed_ph,
                        })
                        result["valid"] = False

                # Verify event hash
                if "event_hash" in event:
                    event_without_hash = {
                        k: v for k, v in event.items() if k != "event_hash"
                    }
                    computed_eh = compute_event_hash(event_without_hash)
                    if computed_eh != event["event_hash"]:
                        result["corrupt_events"].append({
                            "line": line_num,
                            "reason": "event_hash_mismatch",
                            "expected": event["event_hash"],
                            "computed": computed_eh,
                        })
                        result["valid"] = False

                # Verify chain link
                if "prev_event_hash" in event and prev_hash is not None:
                    if event["prev_event_hash"] != prev_hash:
                        result["chain_breaks"].append({
                            "line": line_num,
                            "expected_prev": prev_hash,
                            "actual_prev": event["prev_event_hash"],
                        })
                        result["valid"] = False

                if "event_hash" in event:
                    prev_hash = event["event_hash"]

                if "payload_hash" in event:
                    result["valid_events"] += 1

        if not result["corrupt_events"] and not result["chain_breaks"]:
            result["valid_events"] = result["total_events"]

        return result
