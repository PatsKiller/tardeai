"""
CIO Hermes Challenge Queue — Deterministic append-only event store for Hermes challenges.

Hermes is an independent research challenger. This queue bridges Hermes challenge
artifacts into the CIO platform so Alex can incorporate adversarial evidence
without treating Hermes as production truth.

This is a LAB service (P-1.9). The event log is authoritative; projections are
derived and rebuildable. No mutation of prior records. Hash-chained with SHA-256.

Event store path: data/cio/hermes_challenge_queue.jsonl
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
# Canonical constants
# ═══════════════════════════════════════════════════════════════════════════════

VALID_EVENT_TYPES = frozenset({
    "HERMES_CHALLENGE_ENQUEUED",
    "HERMES_CHALLENGE_CLAIMED",
    "HERMES_CHALLENGE_STARTED",
    "HERMES_CHALLENGE_RESOLVED",
    "HERMES_CHALLENGE_FAILED",
    "HERMES_CHALLENGE_EXPIRED",
    "HERMES_CHALLENGE_CANCELLED",
    "HERMES_CHALLENGE_RELEASED",
    "HERMES_CHALLENGE_GENESIS",
})

CHALLENGE_TYPES = frozenset({
    "research_gap",
    "contradiction",
    "freshness_decay",
    "source_quality",
})

CHALLENGE_STATUSES = frozenset({
    "PENDING",
    "CLAIMED",
    "IN_PROGRESS",
    "RESOLVED",
    "FAILED",
    "EXPIRED",
    "CANCELLED",
})

TERMINAL_CHALLENGE_STATUSES = frozenset({
    "RESOLVED",
    "FAILED",
    "EXPIRED",
    "CANCELLED",
})

STATUS_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"CLAIMED", "EXPIRED", "CANCELLED"},
    "CLAIMED": {"IN_PROGRESS", "EXPIRED", "CANCELLED", "RELEASED"},
    "IN_PROGRESS": {"RESOLVED", "FAILED", "EXPIRED", "CANCELLED"},
    "RELEASED": {"CLAIMED", "EXPIRED", "CANCELLED"},
    "RESOLVED": set(),
    "FAILED": set(),
    "EXPIRED": set(),
    "CANCELLED": set(),
}

STATUS_TRANSITION_EVENTS: dict[str, str] = {
    "HERMES_CHALLENGE_ENQUEUED": "PENDING",
    "HERMES_CHALLENGE_CLAIMED": "CLAIMED",
    "HERMES_CHALLENGE_STARTED": "IN_PROGRESS",
    "HERMES_CHALLENGE_RESOLVED": "RESOLVED",
    "HERMES_CHALLENGE_FAILED": "FAILED",
    "HERMES_CHALLENGE_EXPIRED": "EXPIRED",
    "HERMES_CHALLENGE_CANCELLED": "CANCELLED",
    "HERMES_CHALLENGE_RELEASED": "RELEASED",
}

ALLOWED_ACTOR_TYPES = frozenset({
    "hermes_system",
    "cio_agent",
    "operator",
    "cio_governance",
})


# ═══════════════════════════════════════════════════════════════════════════════
# Hash-chain helpers
# ═══════════════════════════════════════════════════════════════════════════════

def canonicalize_payload(payload: dict[str, Any]) -> str:
    """Deterministic JSON serialization (sorted keys, no trailing whitespace)."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


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

    event_hash = compute_event_hash(envelope)
    envelope["event_hash"] = event_hash

    return envelope


# ═══════════════════════════════════════════════════════════════════════════════
# Hermes Challenge Queue
# ═══════════════════════════════════════════════════════════════════════════════


class HermesChallengeQueue:
    """Deterministic append-only Hermes Challenge Queue backed by a JSONL file.

    Every write is wrapped in fcntl exclusive lock + fsync. The event log is
    authoritative; projections are derived on read via replay.
    """

    def __init__(self, event_store_path: Optional[Path] = None):
        if event_store_path is None:
            event_store_path = (
                Path(__file__).resolve().parent.parent.parent
                / "data"
                / "cio"
                / "hermes_challenge_queue.jsonl"
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
            event_type="HERMES_CHALLENGE_GENESIS",
            stream_id="hermes_challenge_queue",
            payload={"description": "Hermes challenge queue genesis"},
            actor_type="cio_governance",
            actor_id="system",
            authority="cio_governance",
            prev_event_hash="0" * 64,
            schema_version="1.0.0",
        )
        self._append_event(genesis)

    # ── Append ─────────────────────────────────────────────────────────────

    def _append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        lock_fd = self._acquire_lock()
        try:
            with open(self.event_store_path, "a") as f:
                f.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            return event
        finally:
            self._release_lock(lock_fd)

    # ── Read / replay ──────────────────────────────────────────────────────

    def _read_all_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if not self.event_store_path.exists():
            return events
        with open(self.event_store_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return events

    def _last_event_hash(self) -> str:
        events = self._read_all_events()
        if not events:
            return "0" * 64
        return events[-1].get("event_hash", "0" * 64)

    def _build_projection(self) -> dict[str, dict[str, Any]]:
        """Replay all events to build the current challenge state projection."""
        challenges: dict[str, dict[str, Any]] = {}
        for event in self._read_all_events():
            stream_id = event.get("stream_id", "")
            if stream_id == "hermes_challenge_queue":
                continue  # Skip genesis

            if event["event_type"] == "HERMES_CHALLENGE_ENQUEUED":
                challenges[stream_id] = {
                    "challenge_id": stream_id,
                    "challenge_type": event["payload"].get("challenge_type", ""),
                    "status": "PENDING",
                    "payload": event["payload"],
                    "events": [event],
                    "resolved_at": None,
                    "artifact": None,
                }
            elif stream_id in challenges:
                challenges[stream_id]["events"].append(event)
                new_status = STATUS_TRANSITION_EVENTS.get(event["event_type"])
                if new_status:
                    challenges[stream_id]["status"] = new_status
                if event["event_type"] == "HERMES_CHALLENGE_RESOLVED":
                    challenges[stream_id]["resolved_at"] = event["occurred_at"]
                    challenges[stream_id]["artifact"] = event["payload"].get("artifact")
        return challenges

    # ── Challenge operations ───────────────────────────────────────────────

    def enqueue(
        self,
        challenge_type: str,
        description: str,
        source: str,
        priority: str = "normal",
        evidence_refs: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        actor_id: str = "hermes_system",
    ) -> dict[str, Any]:
        """Enqueue a new Hermes challenge.

        Args:
            challenge_type: One of research_gap, contradiction, freshness_decay, source_quality
            description: Human-readable description of the challenge
            source: Source of the challenge (e.g., Hermes query ID)
            priority: normal or high
            evidence_refs: References to supporting evidence
            metadata: Optional additional metadata
            actor_id: Actor creating the challenge
        """
        if challenge_type not in CHALLENGE_TYPES:
            raise ValueError(f"Invalid challenge_type: {challenge_type}")

        challenge_id = f"hermes-challenge-{uuid.uuid4().hex[:12]}"
        prev_hash = self._last_event_hash()

        payload = {
            "challenge_type": challenge_type,
            "description": description,
            "source": source,
            "priority": priority,
            "evidence_refs": evidence_refs or [],
            "status": "PENDING",
        }

        event = build_event(
            event_type="HERMES_CHALLENGE_ENQUEUED",
            stream_id=challenge_id,
            payload=payload,
            actor_type="hermes_system",
            actor_id=actor_id,
            authority="hermes_system",
            prev_event_hash=prev_hash,
            metadata=metadata,
        )
        return self._append_event(event)

    def claim(
        self,
        challenge_id: str,
        claimed_by: str,
        claim_ttl_seconds: int = 3600,
        actor_id: str = "cio_agent",
    ) -> dict[str, Any]:
        """Claim a challenge for processing."""
        challenges = self._build_projection()
        if challenge_id not in challenges:
            raise ValueError(f"Challenge not found: {challenge_id}")

        ch = challenges[challenge_id]
        if ch["status"] not in ("PENDING", "RELEASED"):
            raise ValueError(f"Cannot claim challenge in status: {ch['status']}")

        prev_hash = self._last_event_hash()

        payload = {
            "claimed_by": claimed_by,
            "claim_ttl_seconds": claim_ttl_seconds,
            "claimed_at": datetime.now(timezone.utc).isoformat(),
            "previous_status": ch["status"],
        }

        event = build_event(
            event_type="HERMES_CHALLENGE_CLAIMED",
            stream_id=challenge_id,
            payload=payload,
            actor_type="cio_agent",
            actor_id=actor_id,
            authority="cio_governance",
            prev_event_hash=prev_hash,
        )
        return self._append_event(event)

    def resolve(
        self,
        challenge_id: str,
        artifact: dict[str, Any],
        resolution_note: str = "",
        actor_id: str = "cio_agent",
    ) -> dict[str, Any]:
        """Resolve a challenge with an artifact (evidence, finding, etc.)."""
        if not artifact:
            raise ValueError("Resolved challenge must have an artifact")

        challenges = self._build_projection()
        if challenge_id not in challenges:
            raise ValueError(f"Challenge not found: {challenge_id}")

        ch = challenges[challenge_id]
        if ch["status"] != "IN_PROGRESS":
            raise ValueError(f"Cannot resolve challenge in status: {ch['status']}")

        prev_hash = self._last_event_hash()

        payload = {
            "artifact": artifact,
            "resolution_note": resolution_note,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }

        event = build_event(
            event_type="HERMES_CHALLENGE_RESOLVED",
            stream_id=challenge_id,
            payload=payload,
            actor_type="cio_agent",
            actor_id=actor_id,
            authority="cio_governance",
            prev_event_hash=prev_hash,
        )
        return self._append_event(event)

    def start(
        self,
        challenge_id: str,
        actor_id: str = "cio_agent",
    ) -> dict[str, Any]:
        """Mark a challenge as started (in progress)."""
        challenges = self._build_projection()
        if challenge_id not in challenges:
            raise ValueError(f"Challenge not found: {challenge_id}")

        ch = challenges[challenge_id]
        if ch["status"] != "CLAIMED":
            raise ValueError(f"Cannot start challenge in status: {ch['status']}")

        prev_hash = self._last_event_hash()

        payload = {
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        event = build_event(
            event_type="HERMES_CHALLENGE_STARTED",
            stream_id=challenge_id,
            payload=payload,
            actor_type="cio_agent",
            actor_id=actor_id,
            authority="cio_governance",
            prev_event_hash=prev_hash,
        )
        return self._append_event(event)

    def fail(
        self,
        challenge_id: str,
        reason: str,
        actor_id: str = "cio_agent",
    ) -> dict[str, Any]:
        """Mark a challenge as failed."""
        challenges = self._build_projection()
        if challenge_id not in challenges:
            raise ValueError(f"Challenge not found: {challenge_id}")

        ch = challenges[challenge_id]
        if ch["status"] in TERMINAL_CHALLENGE_STATUSES:
            raise ValueError(f"Challenge already terminal: {ch['status']}")

        prev_hash = self._last_event_hash()

        payload = {
            "failure_reason": reason,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "previous_status": ch["status"],
        }

        event = build_event(
            event_type="HERMES_CHALLENGE_FAILED",
            stream_id=challenge_id,
            payload=payload,
            actor_type="cio_agent",
            actor_id=actor_id,
            authority="cio_governance",
            prev_event_hash=prev_hash,
        )
        return self._append_event(event)

    def expire(
        self,
        challenge_id: str,
        actor_id: str = "hermes_system",
    ) -> dict[str, Any]:
        """Mark a challenge as expired."""
        challenges = self._build_projection()
        if challenge_id not in challenges:
            raise ValueError(f"Challenge not found: {challenge_id}")

        ch = challenges[challenge_id]
        if ch["status"] in TERMINAL_CHALLENGE_STATUSES:
            raise ValueError(f"Challenge already terminal: {ch['status']}")

        prev_hash = self._last_event_hash()

        payload = {
            "expired_at": datetime.now(timezone.utc).isoformat(),
            "previous_status": ch["status"],
        }

        event = build_event(
            event_type="HERMES_CHALLENGE_EXPIRED",
            stream_id=challenge_id,
            payload=payload,
            actor_type="hermes_system",
            actor_id=actor_id,
            authority="hermes_system",
            prev_event_hash=prev_hash,
        )
        return self._append_event(event)

    def cancel(
        self,
        challenge_id: str,
        reason: str = "",
        actor_id: str = "operator",
    ) -> dict[str, Any]:
        """Cancel a challenge."""
        challenges = self._build_projection()
        if challenge_id not in challenges:
            raise ValueError(f"Challenge not found: {challenge_id}")

        ch = challenges[challenge_id]
        if ch["status"] in TERMINAL_CHALLENGE_STATUSES:
            raise ValueError(f"Challenge already terminal: {ch['status']}")

        prev_hash = self._last_event_hash()

        payload = {
            "cancellation_reason": reason,
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
            "previous_status": ch["status"],
        }

        event = build_event(
            event_type="HERMES_CHALLENGE_CANCELLED",
            stream_id=challenge_id,
            payload=payload,
            actor_type="operator",
            actor_id=actor_id,
            authority="operator",
            prev_event_hash=prev_hash,
        )
        return self._append_event(event)

    def release(
        self,
        challenge_id: str,
        reason: str = "",
        actor_id: str = "cio_agent",
    ) -> dict[str, Any]:
        """Release a claimed challenge back to pending."""
        challenges = self._build_projection()
        if challenge_id not in challenges:
            raise ValueError(f"Challenge not found: {challenge_id}")

        ch = challenges[challenge_id]
        if ch["status"] != "CLAIMED":
            raise ValueError(f"Cannot release challenge in status: {ch['status']}")

        prev_hash = self._last_event_hash()

        payload = {
            "release_reason": reason,
            "released_at": datetime.now(timezone.utc).isoformat(),
        }

        event = build_event(
            event_type="HERMES_CHALLENGE_RELEASED",
            stream_id=challenge_id,
            payload=payload,
            actor_type="cio_agent",
            actor_id=actor_id,
            authority="cio_governance",
            prev_event_hash=prev_hash,
        )
        return self._append_event(event)

    # ── Query methods ──────────────────────────────────────────────────────

    def get_challenge(self, challenge_id: str) -> Optional[dict[str, Any]]:
        """Get the current state of a single challenge."""
        challenges = self._build_projection()
        return challenges.get(challenge_id)

    def list_challenges(
        self,
        status: Optional[str] = None,
        challenge_type: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List challenges, optionally filtered by status and/or type."""
        challenges = self._build_projection()
        result = list(challenges.values())

        if status:
            result = [c for c in result if c["status"] == status]
        if challenge_type:
            result = [c for c in result if c["challenge_type"] == challenge_type]

        result.sort(key=lambda c: c.get("payload", {}).get("priority", "normal") == "high", reverse=True)
        return result[:limit]

    # ── Integrity verification ─────────────────────────────────────────────

    def verify_integrity(self) -> dict[str, Any]:
        """Verify hash chain integrity of the event store."""
        events = self._read_all_events()
        issues: list[dict[str, Any]] = []
        hash_chain_valid = True

        prev_event_hash = None
        for i, event in enumerate(events):
            # Extract the stored hash
            stored_hash = event.pop("event_hash", None)
            if stored_hash is None:
                issues.append({"index": i, "event_id": event.get("event_id"), "issue": "missing event_hash"})
                hash_chain_valid = False
                event["event_hash"] = None
                continue

            # Compute expected hash
            expected_hash = compute_event_hash(event)

            # Check hash match
            if stored_hash != expected_hash:
                issues.append({
                    "index": i,
                    "event_id": event.get("event_id"),
                    "issue": "hash_mismatch",
                    "stored": stored_hash,
                    "expected": expected_hash,
                })
                hash_chain_valid = False

            # Check chain link
            if prev_event_hash is not None and event["prev_event_hash"] != prev_event_hash:
                issues.append({
                    "index": i,
                    "event_id": event.get("event_id"),
                    "issue": "chain_break",
                    "expected_prev": prev_event_hash,
                    "actual_prev": event["prev_event_hash"],
                })
                hash_chain_valid = False

            prev_event_hash = stored_hash
            event["event_hash"] = stored_hash

        return {
            "valid": hash_chain_valid and len(issues) == 0,
            "total_events": len(events),
            "issues": issues,
        }
