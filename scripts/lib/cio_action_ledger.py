"""
CIO Action Ledger — Deterministic append-only event store for CIO actions.

This is a LAB service (P-1.3). The event log is authoritative; projections are
derived and rebuildable. No mutation of prior records. Hash-chained with SHA-256.

Legacy pipeline records (cio_decisions, cio_decision_responses, alex_hygiene_log)
remain preserved in PostgreSQL and are NOT migrated into this ledger.
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
    "CIO_ACTION_CREATED",
    "CIO_ACTION_ACKNOWLEDGED",
    "CIO_ACTION_DEFERRED",
    "CIO_ACTION_DONE",
    "CIO_ACTION_EXPIRED",
    "CIO_ACTION_SUPERSEDED",
    "CIO_ACTION_CANCELLED",
    "CIO_ACTION_BLOCKED",
    "CIO_ACTION_UNBLOCKED",
    "CIO_ACTION_FOLLOWUP_SCHEDULED",
    "CIO_ACTION_EVIDENCE_ATTACHED",
    "CIO_ACTION_OPERATOR_DECISION_RECORDED",
    # Internal housekeeping events
    "CIO_ACTION_LEDGER_GENESIS",
})

STATE_TRANSITIONS: dict[str, set[str]] = {
    "OPEN": {"ACKNOWLEDGED", "DEFERRED", "DONE", "EXPIRED", "SUPERSEDED", "CANCELLED", "BLOCKED", "EVIDENCE_ATTACHED", "FOLLOWUP_SCHEDULED", "OPERATOR_DECISION_RECORDED"},
    "ACKNOWLEDGED": {"DEFERRED", "DONE", "EXPIRED", "SUPERSEDED", "CANCELLED", "BLOCKED", "EVIDENCE_ATTACHED", "FOLLOWUP_SCHEDULED", "OPERATOR_DECISION_RECORDED"},
    "DEFERRED": {"OPEN", "DONE", "EXPIRED", "SUPERSEDED", "CANCELLED", "BLOCKED"},
    "BLOCKED": {"OPEN", "CANCELLED", "EXPIRED", "SUPERSEDED", "UNBLOCKED"},
    "DONE": {"SUPERSEDED"},
    "EXPIRED": {"SUPERSEDED"},
    "CANCELLED": {"SUPERSEDED"},
    "SUPERSEDED": set(),
}

TERMINAL_STATUSES = frozenset({"DONE", "EXPIRED", "SUPERSEDED", "CANCELLED"})

STATUS_TRANSITION_EVENTS: dict[str, str] = {
    "CIO_ACTION_CREATED": "OPEN",
    "CIO_ACTION_ACKNOWLEDGED": "ACKNOWLEDGED",
    "CIO_ACTION_DEFERRED": "DEFERRED",
    "CIO_ACTION_DONE": "DONE",
    "CIO_ACTION_EXPIRED": "EXPIRED",
    "CIO_ACTION_SUPERSEDED": "SUPERSEDED",
    "CIO_ACTION_CANCELLED": "CANCELLED",
    "CIO_ACTION_BLOCKED": "BLOCKED",
    "CIO_ACTION_UNBLOCKED": "OPEN",
}

GENESIS_PREV_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

ALLOWED_ACTOR_TYPES = frozenset({"agent", "operator", "system"})

# ═══════════════════════════════════════════════════════════════════════════════
# Deterministic serialization and hashing
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

    event_hash = compute_event_hash(envelope)
    envelope["event_hash"] = event_hash

    return envelope


# ═══════════════════════════════════════════════════════════════════════════════
# CIO Action Ledger
# ═══════════════════════════════════════════════════════════════════════════════


class CIOActionLedger:
    """Deterministic append-only CIO Action Ledger backed by a JSONL file.

    Every write is wrapped in fcntl exclusive lock + fsync. The event log is
    authoritative; projections are derived on read via replay.
    """

    def __init__(self, event_store_path: Optional[Path] = None):
        if event_store_path is None:
            event_store_path = (
                Path(__file__).resolve().parent.parent.parent
                / "data"
                / "cio"
                / "cio_action_ledger.jsonl"
            )
        self.event_store_path = Path(event_store_path)
        self.event_store_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = Path(str(event_store_path) + ".lock")

        if not self.event_store_path.exists() or self.event_store_path.stat().st_size == 0:
            self._initialize_genesis()

    # ── Locking ────────────────────────────────────────────────────────────

    def _acquire_lock(self) -> int:
        """Acquire an exclusive (write) lock on the ledger lock file."""
        lock_fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return lock_fd

    def _release_lock(self, lock_fd: int) -> None:
        """Release the lock and close the file descriptor."""
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

    # ── Genesis ────────────────────────────────────────────────────────────

    def _initialize_genesis(self) -> None:
        """Create the genesis event if the ledger is empty."""
        genesis = build_event(
            event_type="CIO_ACTION_LEDGER_GENESIS",
            stream_id="ledger-genesis",
            payload={
                "message": "CIO Action Ledger initialized",
                "schema_version": "1.0.0",
            },
            actor_type="system",
            actor_id="p1_3_init",
            authority="system",
            prev_event_hash=GENESIS_PREV_HASH,
        )
        self._append_event(genesis)

    # ── Low-level append ───────────────────────────────────────────────────

    def _get_last_event(self) -> Optional[dict[str, Any]]:
        """Return the most recent event in the ledger, or None if empty."""
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
        """Append ONE event with exclusive lock, hash-chain continuity, and fsync.

        The prev_event_hash is set from the *current* chain head inside the lock,
        eliminating any read-before-lock TOCTOU race.  The event_hash is
        recomputed after the real prev_event_hash is assigned.
        """
        lock_fd = self._acquire_lock()
        try:
            current_head_hash = self._get_last_event_hash()
            event["prev_event_hash"] = current_head_hash

            # Recompute event_hash with the authoritative prev_event_hash
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

    def create_action(
        self,
        action: dict[str, Any],
        actor_id: str = "alex",
        actor_type: str = "agent",
        authority: str = "advisory",
    ) -> dict[str, Any]:
        """Create a new CIO action.

        Required fields: cio_action_id, title
        All other fields are optional with sensible defaults.
        """
        # Idempotency guard — check BEFORE validation so duplicate keys
        # short-circuit without raising "already exists".
        idempotency_key = str(action.get("idempotency_key", ""))
        if idempotency_key:
            existing = self._check_idempotency(
                idempotency_key, "CIO_ACTION_CREATED", action["cio_action_id"]
            )
            if existing is not None:
                return existing

        self._validate_action_create(action)

        payload: dict[str, Any] = {
            "cio_action_id": action["cio_action_id"],
            "status": "OPEN",
            "priority": action.get("priority", "MEDIUM"),
            "domain": action.get("domain", "GENERAL"),
            "title": action["title"],
            "recommendation": action.get("recommendation", ""),
            "why_now": action.get("why_now", ""),
            "evidence_refs": action.get("evidence_refs", []),
            "affected_accounts": action.get("affected_accounts", []),
            "affected_symbols": action.get("affected_symbols", []),
            "estimated_financial_impact": action.get("estimated_financial_impact", ""),
            "estimated_tax_impact": action.get("estimated_tax_impact", ""),
            "risk_if_done": action.get("risk_if_done", ""),
            "risk_if_not_done": action.get("risk_if_not_done", ""),
            "dependencies": action.get("dependencies", []),
            "operator_decision_required": action.get("operator_decision_required", True),
            "deadline": action.get("deadline"),
            "expiry": action.get("expiry"),
            "next_check_at": action.get("next_check_at"),
            "followup_condition": action.get("followup_condition", ""),
            "source_snapshot_id": action.get("source_snapshot_id", ""),
            "source_hash": action.get("source_hash", ""),
            "specialist_artifact_refs": action.get("specialist_artifact_refs", []),
            "cio_artifact_id": action.get("cio_artifact_id", ""),
            "origin_run_id": action.get("origin_run_id", ""),
            "legacy_cio_decision_id": action.get("legacy_cio_decision_id"),
            "cio_decision_id": action.get("cio_decision_id", ""),
            "idempotency_key": idempotency_key,
        }

        event = build_event(
            event_type="CIO_ACTION_CREATED",
            stream_id=action["cio_action_id"],
            payload=payload,
            actor_type=actor_type,
            actor_id=actor_id,
            authority=authority,
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    def transition_action(
        self,
        cio_action_id: str,
        new_event_type: str,
        payload: dict[str, Any],
        actor_id: str = "alex",
        actor_type: str = "agent",
        authority: str = "advisory",
    ) -> dict[str, Any]:
        """Transition an action to a new status.

        Validates the state machine, terminal-status gating, and
        stream hash-chain continuity.
        """
        current = self.get_action(cio_action_id)
        if current is None:
            raise ValueError(f"Action not found: {cio_action_id}")

        current_status = current["current_status"]

        # Validate state transition
        if new_event_type in STATUS_TRANSITION_EVENTS:
            target_status = STATUS_TRANSITION_EVENTS[new_event_type]
            allowed = STATE_TRANSITIONS.get(current_status, set())
            if target_status not in allowed:
                raise ValueError(
                    f"Invalid transition: {current_status} -> {target_status} "
                    f"(via {new_event_type})"
                )

        # Terminal guard (only SUPERSEDED can override a terminal state)
        if current_status in TERMINAL_STATUSES and new_event_type != "CIO_ACTION_SUPERSEDED":
            raise ValueError(
                f"Action {cio_action_id} is in terminal state {current_status}"
            )

        # Idempotency
        idempotency_key = str(payload.get("idempotency_key", ""))
        if idempotency_key:
            existing = self._check_idempotency(
                idempotency_key, new_event_type, cio_action_id
            )
            if existing is not None:
                return existing

        # The global chain head is determined inside _append_event under lock.
        # We pass a placeholder so build_event validates the envelope shape.
        payload_with_id = dict(payload)
        payload_with_id["cio_action_id"] = cio_action_id

        event = build_event(
            event_type=new_event_type,
            stream_id=cio_action_id,
            payload=payload_with_id,
            actor_type=actor_type,
            actor_id=actor_id,
            authority=authority,
            prev_event_hash="__TO_BE_SET_UNDER_LOCK__",
        )

        self._append_event(event)
        return event

    # ── Validation helpers ─────────────────────────────────────────────────

    def _validate_action_create(self, action: dict[str, Any]) -> None:
        required = ["cio_action_id", "title"]
        for field in required:
            if field not in action:
                raise ValueError(f"Missing required field: {field}")

        existing = self.get_action(action["cio_action_id"])
        if existing is not None:
            raise ValueError(f"Action already exists: {action['cio_action_id']}")

    def _check_idempotency(
        self, idempotency_key: str, event_type: str, stream_id: str
    ) -> Optional[dict[str, Any]]:
        events = self.list_events(stream_id)
        for e in events:
            if e.get("payload", {}).get("idempotency_key") == idempotency_key:
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

    def get_action(self, cio_action_id: str) -> Optional[dict[str, Any]]:
        """Rebuild the current state of an action from its event stream."""
        events = self.list_events(cio_action_id)
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

            if event_type == "CIO_ACTION_CREATED":
                state.update(
                    {
                        "cio_action_id": payload.get("cio_action_id"),
                        "current_status": "OPEN",
                        "priority": payload.get("priority"),
                        "domain": payload.get("domain"),
                        "title": payload.get("title"),
                        "recommendation": payload.get("recommendation"),
                        "why_now": payload.get("why_now"),
                        "evidence_refs": list(payload.get("evidence_refs", [])),
                        "affected_accounts": list(payload.get("affected_accounts", [])),
                        "affected_symbols": list(payload.get("affected_symbols", [])),
                        "estimated_financial_impact": payload.get("estimated_financial_impact"),
                        "estimated_tax_impact": payload.get("estimated_tax_impact"),
                        "risk_if_done": payload.get("risk_if_done"),
                        "risk_if_not_done": payload.get("risk_if_not_done"),
                        "dependencies": list(payload.get("dependencies", [])),
                        "operator_decision_required": payload.get("operator_decision_required"),
                        "deadline": payload.get("deadline"),
                        "expiry": payload.get("expiry"),
                        "next_check_at": payload.get("next_check_at"),
                        "followup_condition": payload.get("followup_condition"),
                        "source_snapshot_id": payload.get("source_snapshot_id"),
                        "source_hash": payload.get("source_hash"),
                        "specialist_artifact_refs": list(
                            payload.get("specialist_artifact_refs", [])
                        ),
                        "cio_artifact_id": payload.get("cio_artifact_id"),
                        "origin_run_id": payload.get("origin_run_id"),
                        "legacy_cio_decision_id": payload.get("legacy_cio_decision_id"),
                        "cio_decision_id": payload.get("cio_decision_id"),
                        "created_at": event["occurred_at"],
                        "updated_at": event["occurred_at"],
                        "operator_decision": None,
                        "operator_decision_at": None,
                    }
                )

            elif event_type in STATUS_TRANSITION_EVENTS:
                target_status = STATUS_TRANSITION_EVENTS[event_type]
                state["current_status"] = target_status
                state["updated_at"] = event["occurred_at"]

            elif event_type == "CIO_ACTION_EVIDENCE_ATTACHED":
                new_refs = payload.get("evidence_refs", [])
                existing = state.setdefault("evidence_refs", [])
                existing.extend(new_refs)
                state["updated_at"] = event["occurred_at"]

            elif event_type == "CIO_ACTION_OPERATOR_DECISION_RECORDED":
                state["operator_decision"] = payload.get("decision")
                state["operator_decision_at"] = event["occurred_at"]
                state["updated_at"] = event["occurred_at"]

            elif event_type == "CIO_ACTION_FOLLOWUP_SCHEDULED":
                state["next_check_at"] = payload.get("next_check_at")
                state["followup_condition"] = payload.get("followup_condition", "")
                state["updated_at"] = event["occurred_at"]

        return state

    def list_actions(
        self,
        status: Optional[str] = None,
        domain: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List actions, optionally filtered by status and/or domain."""
        stream_ids: set[str] = set()
        if self.event_store_path.exists():
            with open(self.event_store_path, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    event = json.loads(stripped)
                    sid = event["stream_id"]
                    if sid != "ledger-genesis":
                        stream_ids.add(sid)

        actions: list[dict[str, Any]] = []
        for sid in stream_ids:
            action = self.get_action(sid)
            if action is None:
                continue
            if status is not None and action.get("current_status") != status:
                continue
            if domain is not None and action.get("domain") != domain:
                continue
            actions.append(action)

        actions.sort(key=lambda a: str(a.get("created_at", "")), reverse=True)
        return actions[:limit]

    # ── Integrity verification ─────────────────────────────────────────────

    def verify_integrity(self) -> dict[str, Any]:
        """Verify the entire ledger's hash chain, payload hashes, and event hashes."""
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
                except json.JSONDecodeError:
                    result["corrupt_events"].append({"line": line_num, "reason": "invalid_json"})
                    result["valid"] = False
                    continue

                # Verify payload hash
                if "payload" in event and "payload_hash" in event:
                    computed_ph = compute_payload_hash(event["payload"])
                    if computed_ph != event["payload_hash"]:
                        result["corrupt_events"].append(
                            {
                                "line": line_num,
                                "reason": "payload_hash_mismatch",
                                "expected": event["payload_hash"],
                                "computed": computed_ph,
                            }
                        )
                        result["valid"] = False

                # Verify event hash
                if "event_hash" in event:
                    event_without_hash = {k: v for k, v in event.items() if k != "event_hash"}
                    computed_eh = compute_event_hash(event_without_hash)
                    if computed_eh != event["event_hash"]:
                        result["corrupt_events"].append(
                            {
                                "line": line_num,
                                "reason": "event_hash_mismatch",
                                "expected": event["event_hash"],
                                "computed": computed_eh,
                            }
                        )
                        result["valid"] = False

                # Verify chain link
                if "prev_event_hash" in event and prev_hash is not None:
                    if event["prev_event_hash"] != prev_hash:
                        result["chain_breaks"].append(
                            {
                                "line": line_num,
                                "expected_prev": prev_hash,
                                "actual_prev": event["prev_event_hash"],
                            }
                        )
                        result["valid"] = False

                if "event_hash" in event:
                    prev_hash = event["event_hash"]

                if "payload_hash" in event:
                    result["valid_events"] += 1

        if not result["corrupt_events"] and not result["chain_breaks"]:
            result["valid_events"] = result["total_events"]

        return result


# ═══════════════════════════════════════════════════════════════════════════════
# Public API — write-authority gate
# ═══════════════════════════════════════════════════════════════════════════════


def create_cio_action(
    action: dict[str, Any],
    actor_id: str = "alex",
    actor_type: str = "agent",
) -> dict[str, Any]:
    """Public API for creating a CIO action with authority validation.

    Alex (agent type) gets advisory authority.
    Operators get operator authority.
    """
    ledger = CIOActionLedger()

    if actor_type == "agent" and actor_id == "alex":
        authority = "advisory"
    elif actor_type == "operator":
        authority = "operator"
    else:
        raise ValueError(f"Unauthorized actor: {actor_type}/{actor_id}")

    return ledger.create_action(
        action, actor_id=actor_id, actor_type=actor_type, authority=authority
    )
