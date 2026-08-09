"""
CIO Wake Job Store — Deterministic append-only event store for CIO wake jobs.

This is a LAB service (P-1.6). The event log is authoritative; projections are
derived and rebuildable via in-memory replay. No mutation of prior records.
Hash-chained with SHA-256.

Dependencies: Primitive serialization/hashing functions (canonicalize_payload,
compute_payload_hash, compute_event_hash, build_event) are replicated from
scripts/lib/cio_action_ledger.py (P-1.3) with identical semantics.

Separated from: CIO Action Ledger (P-1.3), Agent Handoff Queue (P-1.4),
Health Boundary (P-1.5).
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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


def build_event(
    event_type: str,
    stream_id: str,
    payload: dict[str, Any],
    actor_type: str,
    actor_id: str,
    authority: str,
    prev_event_hash: str,
    metadata: Optional[dict[str, Any]] = None,
    schema_version: str = "1.0.0",
) -> dict[str, Any]:
    """Build a fully-hashed event envelope."""
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
# Canonical constants
# ═══════════════════════════════════════════════════════════════════════════════

VALID_EVENT_TYPES = frozenset({
    "CIO_WAKE_ENQUEUED",
    "CIO_WAKE_CLAIMED",
    "CIO_WAKE_DISPATCHED",
    "CIO_WAKE_ACKNOWLEDGED",
    "CIO_WAKE_RELEASED",
    "CIO_WAKE_EXPIRED",
    "CIO_WAKE_CANCELLED",
    "CIO_WAKE_COMPLETED",
    "CIO_WAKE_RETRY_SCHEDULED",
    "CIO_WAKE_JOB_STORE_GENESIS",
})

STATUS_EVENTS: dict[str, str] = {
    "CIO_WAKE_ENQUEUED": "PENDING",
    "CIO_WAKE_CLAIMED": "CLAIMED",
    "CIO_WAKE_DISPATCHED": "DISPATCHED",
    "CIO_WAKE_ACKNOWLEDGED": "ACKNOWLEDGED",
    "CIO_WAKE_RELEASED": "PENDING",
    "CIO_WAKE_EXPIRED": "EXPIRED",
    "CIO_WAKE_CANCELLED": "CANCELLED",
    "CIO_WAKE_COMPLETED": "COMPLETED",
    "CIO_WAKE_RETRY_SCHEDULED": "RETRY_PENDING",
}

TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"CLAIMED", "CANCELLED", "EXPIRED"},
    "CLAIMED": {"DISPATCHED", "RELEASED", "EXPIRED", "CANCELLED"},
    "DISPATCHED": {"ACKNOWLEDGED", "EXPIRED", "CANCELLED", "RETRY_PENDING"},
    "ACKNOWLEDGED": {"COMPLETED", "EXPIRED", "CANCELLED"},
    "RETRY_PENDING": {"CLAIMED", "EXPIRED", "CANCELLED"},
    "COMPLETED": set(),
    "EXPIRED": set(),
    "CANCELLED": set(),
}

TERMINAL = frozenset({"COMPLETED", "EXPIRED", "CANCELLED"})

TRIGGER_TYPES = frozenset({
    "SCHEDULE_DUE",
    "ACTION_FOLLOWUP_DUE",
    "HEALTH_BLOCK_STARTED",
    "HEALTH_BLOCK_CLEARED",
    "HANDOFF_COMPLETED",
})

WAKE_REASON_CODES = frozenset({
    "SCHEDULE_DUE",
    "ACTION_FOLLOWUP_DUE",
    "HEALTH_BLOCK_STARTED",
    "HEALTH_BLOCK_CLEARED",
    "HANDOFF_COMPLETED",
    "ACTION_DEADLINE_NEAR",
    "HANDOFF_FAILED_MATERIAL",
})

PRIORITY_MAP: dict[str, str] = {
    "HEALTH_BLOCK_STARTED": "high",
    "ACTION_DEADLINE_NEAR": "high",
    "ACTION_FOLLOWUP_DUE": "normal",
    "HEALTH_BLOCK_CLEARED": "normal",
    "HANDOFF_COMPLETED": "normal",
    "HANDOFF_FAILED_MATERIAL": "normal",
    "SCHEDULE_DUE": "normal",
}

GENESIS_PREV_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

ALLOWED_ACTOR_TYPES = frozenset({"agent", "operator", "system"})


# ═══════════════════════════════════════════════════════════════════════════════
# CIO Wake Job Store
# ═══════════════════════════════════════════════════════════════════════════════


class CIOWakeJobStore:
    """Deterministic append-only wake job store backed by a JSONL file.

    Every write uses fcntl exclusive lock + fsync. Event log is authoritative.
    Projections are derived via replay on read.
    """

    def __init__(self, event_store_path: Optional[Path] = None):
        if event_store_path is None:
            event_store_path = (
                Path(__file__).resolve().parent.parent.parent
                / "data"
                / "cio"
                / "cio_wake_jobs.jsonl"
            )
        self.event_store_path = Path(event_store_path)
        self.event_store_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = Path(str(event_store_path) + ".lock")

        if not self.event_store_path.exists() or self.event_store_path.stat().st_size == 0:
            self._initialize_genesis()

    # ── Locking ────────────────────────────────────────────────────────────

    def _acquire_lock(self) -> int:
        lock_fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return lock_fd

    def _release_lock(self, lock_fd: int) -> None:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

    # ── Genesis ────────────────────────────────────────────────────────────

    def _initialize_genesis(self) -> None:
        genesis = build_event(
            event_type="CIO_WAKE_JOB_STORE_GENESIS",
            stream_id="wake-store-genesis",
            payload={
                "message": "CIO Wake Job Store initialized",
                "schema_version": "1.0.0",
            },
            actor_type="system",
            actor_id="p1_6_init",
            authority="system",
            prev_event_hash=GENESIS_PREV_HASH,
        )
        self._append_event(genesis)

    # ── Low-level append ───────────────────────────────────────────────────

    def _get_last_event(self) -> Optional[dict[str, Any]]:
        if not self.event_store_path.exists():
            return None
        with open(self.event_store_path, "r") as f:
            lines = f.readlines()
            if not lines:
                return None
            return json.loads(lines[-1].strip())

    def _get_last_event_hash(self) -> str:
        last = self._get_last_event()
        if last is None:
            return GENESIS_PREV_HASH
        return last["event_hash"]

    def _append_event(self, event: dict[str, Any]) -> None:
        lock_fd = self._acquire_lock()
        try:
            current_head_hash = self._get_last_event_hash()
            event["prev_event_hash"] = current_head_hash

            event_without_hash = {k: v for k, v in event.items() if k != "event_hash"}
            event["event_hash"] = compute_event_hash(event_without_hash)

            line = json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n"

            with open(self.event_store_path, "a") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        finally:
            self._release_lock(lock_fd)

    # ── Core domain operations ─────────────────────────────────────────────

    def enqueue(
        self,
        wake_payload: dict[str, Any],
        actor_id: str = "cio_detector",
        actor_type: str = "system",
        authority: str = "system",
    ) -> dict[str, Any]:
        """Enqueue a new wake job. The wake_job_id must be unique."""
        wake_job_id = wake_payload["wake_job_id"]
        trigger_type = wake_payload.get("trigger_type", "SCHEDULE_DUE")

        # Idempotency guard
        idempotency_key = str(wake_payload.get("idempotency_key", ""))
        if idempotency_key:
            existing = self._check_idempotency(
                idempotency_key, "CIO_WAKE_ENQUEUED", wake_job_id
            )
            if existing is not None:
                return existing

        # Check not already exists
        existing_wake = self.get_wake_job(wake_job_id)
        if existing_wake is not None:
            raise ValueError(f"Wake job already exists: {wake_job_id}")

        if trigger_type not in TRIGGER_TYPES:
            raise ValueError(f"Invalid trigger_type: {trigger_type}")

        priority = PRIORITY_MAP.get(trigger_type, "normal")
        for rc in wake_payload.get("reason_codes", []):
            if rc == "ACTION_DEADLINE_NEAR":
                priority = "high"
                break
            if rc == "HEALTH_BLOCK_STARTED":
                priority = "high"
                break

        payload: dict[str, Any] = {
            "wake_job_id": wake_job_id,
            "trigger_type": trigger_type,
            "trigger_ref": wake_payload.get("trigger_ref", ""),
            "trigger_hash": wake_payload.get("trigger_hash", ""),
            "scheduled_slot": wake_payload.get("scheduled_slot", ""),
            "created_at": wake_payload.get("created_at", datetime.now(timezone.utc).isoformat()),
            "due_at": wake_payload.get("due_at", datetime.now(timezone.utc).isoformat()),
            "priority": priority,
            "reason_codes": list(wake_payload.get("reason_codes", [])),
            "required_domains": list(wake_payload.get("required_domains", [])),
            "parent_cio_action_id": wake_payload.get("parent_cio_action_id"),
            "parent_handoff_id": wake_payload.get("parent_handoff_id"),
            "health_decision_id": wake_payload.get("health_decision_id"),
            "source_snapshot_id": wake_payload.get("source_snapshot_id"),
            "idempotency_key": idempotency_key,
        }

        event = build_event(
            event_type="CIO_WAKE_ENQUEUED",
            stream_id=wake_job_id,
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
        wake_job_id: str,
        claim_token: str,
        actor_id: str = "cio_detector",
        actor_type: str = "system",
        authority: str = "system",
    ) -> dict[str, Any]:
        """Claim a wake job for processing."""
        wake = self.get_wake_job(wake_job_id)
        if wake is None:
            raise ValueError(f"Wake job not found: {wake_job_id}")

        current_status = wake["current_status"]
        allowed = TRANSITIONS.get(current_status, set())
        if "CLAIMED" not in allowed:
            raise ValueError(f"Cannot claim wake in status: {current_status}")

        payload: dict[str, Any] = {
            "wake_job_id": wake_job_id,
            "claim_token": claim_token,
            "claimed_at": datetime.now(timezone.utc).isoformat(),
        }

        event = build_event(
            event_type="CIO_WAKE_CLAIMED",
            stream_id=wake_job_id,
            payload=payload,
            actor_type=actor_type,
            actor_id=actor_id,
            authority=authority,
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    def dispatch(
        self,
        wake_job_id: str,
        actor_id: str = "cio_detector",
        actor_type: str = "system",
        authority: str = "system",
    ) -> dict[str, Any]:
        """Dispatch a claimed wake job for execution."""
        wake = self.get_wake_job(wake_job_id)
        if wake is None:
            raise ValueError(f"Wake job not found: {wake_job_id}")

        current_status = wake["current_status"]
        allowed = TRANSITIONS.get(current_status, set())
        if "DISPATCHED" not in allowed:
            raise ValueError(f"Cannot dispatch wake in status: {current_status}")

        payload: dict[str, Any] = {
            "wake_job_id": wake_job_id,
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
        }

        event = build_event(
            event_type="CIO_WAKE_DISPATCHED",
            stream_id=wake_job_id,
            payload=payload,
            actor_type=actor_type,
            actor_id=actor_id,
            authority=authority,
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    def acknowledge(
        self,
        wake_job_id: str,
        actor_id: str = "cio_detector",
        actor_type: str = "system",
        authority: str = "system",
    ) -> dict[str, Any]:
        """Acknowledge a dispatched wake job as received."""
        wake = self.get_wake_job(wake_job_id)
        if wake is None:
            raise ValueError(f"Wake job not found: {wake_job_id}")

        current_status = wake["current_status"]
        allowed = TRANSITIONS.get(current_status, set())
        if "ACKNOWLEDGED" not in allowed:
            raise ValueError(f"Cannot acknowledge wake in status: {current_status}")

        payload: dict[str, Any] = {
            "wake_job_id": wake_job_id,
            "acknowledged_at": datetime.now(timezone.utc).isoformat(),
        }

        event = build_event(
            event_type="CIO_WAKE_ACKNOWLEDGED",
            stream_id=wake_job_id,
            payload=payload,
            actor_type=actor_type,
            actor_id=actor_id,
            authority=authority,
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    def complete(
        self,
        wake_job_id: str,
        completion_payload: Optional[dict[str, Any]] = None,
        actor_id: str = "cio_detector",
        actor_type: str = "system",
        authority: str = "system",
    ) -> dict[str, Any]:
        """Mark a wake job as completed."""
        wake = self.get_wake_job(wake_job_id)
        if wake is None:
            raise ValueError(f"Wake job not found: {wake_job_id}")

        current_status = wake["current_status"]
        allowed = TRANSITIONS.get(current_status, set())
        if "COMPLETED" not in allowed:
            raise ValueError(f"Cannot complete wake in status: {current_status}")

        payload: dict[str, Any] = {
            "wake_job_id": wake_job_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "completion_details": completion_payload or {},
        }

        event = build_event(
            event_type="CIO_WAKE_COMPLETED",
            stream_id=wake_job_id,
            payload=payload,
            actor_type=actor_type,
            actor_id=actor_id,
            authority=authority,
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    def release(
        self,
        wake_job_id: str,
        actor_id: str = "cio_detector",
        actor_type: str = "system",
        authority: str = "system",
    ) -> dict[str, Any]:
        """Release a claimed/dispatched wake job back to PENDING."""
        wake = self.get_wake_job(wake_job_id)
        if wake is None:
            raise ValueError(f"Wake job not found: {wake_job_id}")

        current_status = wake["current_status"]
        allowed = TRANSITIONS.get(current_status, set())
        if "RELEASED" not in allowed:
            raise ValueError(f"Cannot release wake in status: {current_status}")

        payload: dict[str, Any] = {
            "wake_job_id": wake_job_id,
            "released_at": datetime.now(timezone.utc).isoformat(),
        }

        event = build_event(
            event_type="CIO_WAKE_RELEASED",
            stream_id=wake_job_id,
            payload=payload,
            actor_type=actor_type,
            actor_id=actor_id,
            authority=authority,
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    # ── Validation helpers ─────────────────────────────────────────────────

    def _check_idempotency(
        self, idempotency_key: str, event_type: str, stream_id: str
    ) -> Optional[dict[str, Any]]:
        events = self.list_events(stream_id)
        for e in events:
            if e.get("payload", {}).get("idempotency_key") == idempotency_key:
                if e["event_type"] == event_type:
                    return e
        return None

    # ── Read APIs (projection via replay) ──────────────────────────────────

    def list_events(self, stream_id: str) -> list[dict[str, Any]]:
        """Return all events for a given stream, in insertion order."""
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

    def get_wake_job(self, wake_job_id: str) -> Optional[dict[str, Any]]:
        """Rebuild the current state of a wake job from its event stream."""
        events = self.list_events(wake_job_id)
        if not events:
            return None
        return self._replay_state(events)

    def _replay_state(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Rebuild current state by folding over the event stream."""
        state: dict[str, Any] = {
            "current_status": None,
            "event_count": 0,
            "last_event_id": None,
            "last_event_hash": None,
        }

        for event in events:
            state["event_count"] += 1
            state["last_event_id"] = event["event_id"]
            state["last_event_hash"] = event["event_hash"]

            event_type = event["event_type"]
            payload = event.get("payload", {})

            if event_type == "CIO_WAKE_ENQUEUED":
                state.update({
                    "wake_job_id": payload.get("wake_job_id"),
                    "current_status": "PENDING",
                    "trigger_type": payload.get("trigger_type"),
                    "trigger_ref": payload.get("trigger_ref"),
                    "trigger_hash": payload.get("trigger_hash"),
                    "scheduled_slot": payload.get("scheduled_slot"),
                    "created_at": payload.get("created_at"),
                    "due_at": payload.get("due_at"),
                    "priority": payload.get("priority"),
                    "reason_codes": list(payload.get("reason_codes", [])),
                    "required_domains": list(payload.get("required_domains", [])),
                    "parent_cio_action_id": payload.get("parent_cio_action_id"),
                    "parent_handoff_id": payload.get("parent_handoff_id"),
                    "health_decision_id": payload.get("health_decision_id"),
                    "source_snapshot_id": payload.get("source_snapshot_id"),
                    "idempotency_key": payload.get("idempotency_key", ""),
                    "updated_at": event["occurred_at"],
                })

            elif event_type in STATUS_EVENTS:
                target_status = STATUS_EVENTS[event_type]
                state["current_status"] = target_status
                state["updated_at"] = event["occurred_at"]

                if event_type == "CIO_WAKE_CLAIMED":
                    state["claim_token"] = payload.get("claim_token")
                    state["claimed_at"] = payload.get("claimed_at")
                elif event_type == "CIO_WAKE_DISPATCHED":
                    state["dispatched_at"] = payload.get("dispatched_at")
                elif event_type == "CIO_WAKE_ACKNOWLEDGED":
                    state["acknowledged_at"] = payload.get("acknowledged_at")
                elif event_type == "CIO_WAKE_RELEASED":
                    state["released_at"] = payload.get("released_at")
                elif event_type == "CIO_WAKE_COMPLETED":
                    state["completed_at"] = payload.get("completed_at")
                    state["completion_details"] = payload.get("completion_details", {})
                elif event_type == "CIO_WAKE_CANCELLED":
                    state["cancelled_at"] = payload.get("cancelled_at")
                elif event_type == "CIO_WAKE_EXPIRED":
                    state["expired_at"] = payload.get("expired_at")

        return state

    def list_wakes(
        self,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List wake jobs, optionally filtered by status and/or priority."""
        stream_ids: set[str] = set()
        if self.event_store_path.exists():
            with open(self.event_store_path, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    event = json.loads(stripped)
                    sid = event["stream_id"]
                    if sid != "wake-store-genesis":
                        stream_ids.add(sid)

        wakes: list[dict[str, Any]] = []
        for sid in stream_ids:
            wake = self.get_wake_job(sid)
            if wake is None:
                continue
            if status is not None and wake.get("current_status") != status:
                continue
            if priority is not None and wake.get("priority") != priority:
                continue
            wakes.append(wake)

        wakes.sort(key=lambda w: str(w.get("created_at", "")), reverse=True)
        return wakes[:limit]

    # ── Integrity verification ─────────────────────────────────────────────

    def verify_integrity(self) -> dict[str, Any]:
        """Verify the entire store's hash chain, payload hashes, and event hashes."""
        result: dict[str, Any] = {
            "valid": True,
            "total_events": 0,
            "valid_events": 0,
            "corrupt_events": [],
            "chain_breaks": [],
        }

        if not self.event_store_path.exists() or self.event_store_path.stat().st_size == 0:
            return result

        prev_hash: Optional[str] = None

        with open(self.event_store_path, "r") as f:
            for line_num, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped:
                    continue
                result["total_events"] += 1

                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError as e:
                    result["valid"] = False
                    result["corrupt_events"].append({
                        "line": line_num,
                        "error": f"JSON decode error: {e}",
                    })
                    continue

                # Verify payload hash
                payload = event.get("payload", {})
                expected_payload_hash = compute_payload_hash(payload)
                actual_payload_hash = event.get("payload_hash")
                if expected_payload_hash != actual_payload_hash:
                    result["valid"] = False
                    result["corrupt_events"].append({
                        "line": line_num,
                        "event_id": event.get("event_id"),
                        "error": "Payload hash mismatch",
                    })
                    continue

                # Verify event hash
                event_without_hash = {k: v for k, v in event.items() if k != "event_hash"}
                expected_event_hash = compute_event_hash(event_without_hash)
                actual_event_hash = event.get("event_hash")
                if expected_event_hash != actual_event_hash:
                    result["valid"] = False
                    result["corrupt_events"].append({
                        "line": line_num,
                        "event_id": event.get("event_id"),
                        "error": "Event hash mismatch",
                    })
                    continue

                # Verify chain integrity
                if prev_hash is not None:
                    if event["prev_event_hash"] != prev_hash:
                        result["valid"] = False
                        result["chain_breaks"].append({
                            "line": line_num,
                            "event_id": event.get("event_id"),
                            "expected_prev": prev_hash,
                            "actual_prev": event["prev_event_hash"],
                        })

                prev_hash = event["event_hash"]
                result["valid_events"] += 1

        return result
