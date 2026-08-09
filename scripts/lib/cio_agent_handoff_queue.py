"""
Agent Handoff Queue — Deterministic append-only event store for Alex ↔ specialist handoffs.

This is a LAB service (P-1.4). The event log is authoritative; projections are
derived and rebuildable via in-memory replay. No mutation of prior records.
Hash-chained with SHA-256. Lease-safe with claim tokens.

Dependencies: Primitive serialization/hashing functions (canonicalize_payload,
compute_payload_hash, compute_event_hash, build_event) are replicated from
scripts/lib/cio_action_ledger.py (P-1.3) with identical semantics. The P-1.3
build_event validates against a CIO-specific VALID_EVENT_TYPES set, making
direct import infeasible without parameterizing that validation.
See CIO P-1.3 for the canonical definition of these primitives.

Separated from: CIO Action Ledger (P-1.3), Notification Outbox, Hermes research.
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
# Agent Registry and Maturity
# ═══════════════════════════════════════════════════════════════════════════════

AGENT_REGISTRY: dict[str, dict[str, str]] = {
    "alex": {"status": "REGISTERED", "role": "cio"},
    "maria": {"status": "AVAILABLE", "role": "research"},
    "steph": {"status": "AVAILABLE", "role": "allocation"},
    "guardian": {"status": "NOT_READY", "role": "risk"},
    "ledger": {"status": "NOT_READY", "role": "tax"},
    "morgan": {"status": "AVAILABLE", "role": "wealth"},
}

ALLOWED_TASK_TYPES = frozenset({
    "cio_question",
    "fundamental_research",
    "allocation_review",
    "risk_review",
    "tax_account_review",
    "retirement_review",
    "evidence_review",
    "specialist_reconciliation",
    "wake",
    "wealth_synthesis",
    "goal_tracking",
    "liquidity_planning",
    "tax_coordination",
    "estate_review",
    "multi_account_coordination",
})

TARGET_NOT_READY_POLICY = "BLOCKED"  # Not-ready agents: BLOCKED (not REJECTED)

ALLOWED_TASK_TYPES = frozenset({
    "cio_question",
    "fundamental_research",
    "allocation_review",
    "risk_review",
    "tax_account_review",
    "retirement_review",
    "evidence_review",
    "specialist_reconciliation",
    "wake",
})

FORBIDDEN_TASK_TYPES = frozenset({
    "execute_trade",
    "submit_order",
    "modify_position",
    "approve_risk",
    "change_stop",
    "run_shell",
    "restart_service",
    "deploy_code",
    "modify_config",
    "send_telegram",
})

# ═══════════════════════════════════════════════════════════════════════════════
# Event types
# ═══════════════════════════════════════════════════════════════════════════════

VALID_EVENT_TYPES = frozenset({
    "HANDOFF_QUEUE_GENESIS",
    "HANDOFF_ENQUEUED",
    "HANDOFF_BLOCKED",
    "HANDOFF_CLAIMED",
    "HANDOFF_STARTED",
    "HANDOFF_HEARTBEAT",
    "HANDOFF_RETRY_SCHEDULED",
    "HANDOFF_COMPLETED",
    "HANDOFF_FAILED",
    "HANDOFF_EXPIRED",
    "HANDOFF_CANCELLED",
    "HANDOFF_RELEASED",
})

ALLOWED_ACTOR_TYPES = frozenset({"agent", "system"})

# Status-modifying event type mapping
STATUS_EVENTS: dict[str, str] = {
    "HANDOFF_ENQUEUED": "PENDING",
    "HANDOFF_BLOCKED": "BLOCKED",
    "HANDOFF_CLAIMED": "CLAIMED",
    "HANDOFF_STARTED": "STARTED",
    "HANDOFF_RETRY_SCHEDULED": "RETRY_SCHEDULED",
    "HANDOFF_COMPLETED": "COMPLETED",
    "HANDOFF_FAILED": "FAILED",
    "HANDOFF_EXPIRED": "EXPIRED",
    "HANDOFF_CANCELLED": "CANCELLED",
    "HANDOFF_RELEASED": "PENDING",
}

# State machine: from_status -> allowed target statuses
STATE_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"BLOCKED", "CLAIMED", "CANCELLED", "EXPIRED"},
    "BLOCKED": {"PENDING", "CANCELLED", "EXPIRED"},
    "CLAIMED": {"STARTED", "PENDING", "EXPIRED", "CANCELLED", "FAILED", "RETRY_SCHEDULED", "COMPLETED"},
    "STARTED": {"COMPLETED", "FAILED", "EXPIRED", "CANCELLED", "RETRY_SCHEDULED"},
    "RETRY_SCHEDULED": {"CLAIMED", "EXPIRED", "CANCELLED", "FAILED"},
    "COMPLETED": set(),   # terminal
    "FAILED": {"RETRY_SCHEDULED", "CANCELLED"},  # can retry or cancel
    "EXPIRED": set(),    # terminal
    "CANCELLED": set(),  # terminal
}

TERMINAL_STATUSES = frozenset({"COMPLETED", "EXPIRED", "CANCELLED"})

# ═══════════════════════════════════════════════════════════════════════════════
# Lease and retry configuration
# ═══════════════════════════════════════════════════════════════════════════════

# Default retry backoff (minutes): 1, 5, 15, 60
RETRY_BACKOFF = [1, 5, 15, 60]

# Default lease duration in minutes
LEASE_DURATION_MINUTES = 5

# Maximum retry attempts before final FAILED
MAX_RETRY_ATTEMPTS = 3

GENESIS_PREV_HASH = "0000000000000000000000000000000000000000000000000000000000000000"


# ═══════════════════════════════════════════════════════════════════════════════
# AgentHandoffQueue — event-sourced, hash-chained, lease-safe handoff store
# ═══════════════════════════════════════════════════════════════════════════════


class AgentHandoffQueue:
    """Durable, event-sourced Agent Handoff Queue for Alex <-> specialist work.

    Every state transition is recorded as an append-only event. The current
    state of any handoff is a projection replayed from the full event stream.
    Claims are lease-protected with claim tokens. Retries follow exponential
    backoff. Hash-chain integrity is verifiable at any time.
    """

    def __init__(self, event_store_path: Path | None = None):
        if event_store_path is None:
            event_store_path = (
                Path(__file__).resolve().parent.parent.parent
                / "data" / "cio" / "agent_handoff_queue.jsonl"
            )
        self.event_store_path = Path(event_store_path)
        self.event_store_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = Path(str(event_store_path) + ".lock")

        if not self.event_store_path.exists() or self.event_store_path.stat().st_size == 0:
            self._initialize_genesis()

    def _initialize_genesis(self) -> None:
        """Write the HANDOFF_QUEUE_GENESIS event as the first record."""
        genesis = build_event(
            "HANDOFF_QUEUE_GENESIS",
            "queue-genesis",
            {"message": "Agent Handoff Queue initialized", "schema_version": "1.0.0"},
            "system",
            "p1_4_init",
            "system",
            GENESIS_PREV_HASH,
        )
        self._append_event(genesis)

    # ── File locking ──────────────────────────────────────────────────────

    def _acquire_lock(self) -> int:
        """Acquire an exclusive lock on the event store."""
        lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return lock_fd

    def _release_lock(self, lock_fd: int) -> None:
        """Release the exclusive lock and close the file descriptor."""
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

    # ── Low-level event store primitives ──────────────────────────────────

    def _get_last_event(self) -> dict[str, Any] | None:
        """Return the last event in the event store, or None if empty."""
        if not self.event_store_path.exists():
            return None
        with open(self.event_store_path, "r") as f:
            lines = f.readlines()
        if not lines:
            return None
        return json.loads(lines[-1].strip())

    def _get_last_event_hash(self) -> str:
        """Return the event_hash of the last event, or the genesis placeholder."""
        last = self._get_last_event()
        if last is None:
            return GENESIS_PREV_HASH
        return last["event_hash"]

    def _append_event(self, event: dict[str, Any]) -> None:
        """Append an event to the event store with exclusive lock and fsync.

        prev_event_hash is recomputed inside the lock to prevent TOCTOU races
        during concurrent writes. The event_hash is also recomputed to reflect
        the corrected chain link.
        """
        lock_fd = self._acquire_lock()
        try:
            # Set prev_event_hash to the ACTUAL current chain tip (inside lock)
            current_head_hash = self._get_last_event_hash()
            event["prev_event_hash"] = current_head_hash

            # Recompute event_hash since prev_event_hash may have changed
            event_wo_hash = {k: v for k, v in event.items() if k != "event_hash"}
            event["event_hash"] = compute_event_hash(event_wo_hash)

            line = json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n"
            with open(self.event_store_path, "a") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        finally:
            self._release_lock(lock_fd)

    def _get_stream_events(self, stream_id: str) -> list[dict[str, Any]]:
        """Return all events for a given stream_id, in append order."""
        events: list[dict[str, Any]] = []
        if not self.event_store_path.exists():
            return events
        with open(self.event_store_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                if event["stream_id"] == stream_id:
                    events.append(event)
        return events

    def _check_idempotency(
        self, idempotency_key: str, handoff_id: str
    ) -> dict[str, Any] | None:
        """Return the existing event if an idempotency key was already used."""
        if not idempotency_key:
            return None
        events = self._get_stream_events(handoff_id)
        for e in events:
            if e.get("payload", {}).get("idempotency_key") == idempotency_key:
                return e
        return None

    def _validate_agent(self, agent_id: str) -> dict[str, str]:
        """Validate that an agent exists in the registry."""
        agent = AGENT_REGISTRY.get(agent_id)
        if not agent:
            raise ValueError(f"Unknown agent: {agent_id}")
        return agent

    # ── Projection / replay ───────────────────────────────────────────────

    def _replay(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Replay a stream of events to build the current projection."""
        state: dict[str, Any] = {
            "current_status": None,
            "event_count": 0,
            "last_event_id": None,
            "last_event_hash": None,
            "attempt_number": 0,
        }

        for event in events:
            state["event_count"] += 1
            state["last_event_id"] = event["event_id"]
            state["last_event_hash"] = event["event_hash"]

            et = event["event_type"]
            p = event.get("payload", {})

            if et in ("HANDOFF_ENQUEUED", "HANDOFF_BLOCKED"):
                state.update({
                    "handoff_id": p.get("handoff_id"),
                    "parent_run_id": p.get("parent_run_id"),
                    "parent_cio_action_id": p.get("parent_cio_action_id"),
                    "operator_request_id": p.get("operator_request_id"),
                    "from_agent": p.get("from_agent"),
                    "to_agent": p.get("to_agent"),
                    "task_type": p.get("task_type"),
                    "task_summary": p.get("task_summary"),
                    "priority": p.get("priority"),
                    "current_status": STATUS_EVENTS.get(et),
                    "created_at": p.get("created_at"),
                    "updated_at": event["occurred_at"],
                    "deadline": p.get("deadline"),
                    "max_budget_usd": p.get("max_budget_usd"),
                    "worker_id": None,
                    "lease_expires_at": None,
                    "claim_token": None,
                    "retry_after": None,
                    "artifact_id": None,
                    "artifact_hash": None,
                    "failure_code": None,
                    "failure_class": None,
                })

            elif et == "HANDOFF_CLAIMED":
                state["worker_id"] = p.get("worker_id")
                state["claim_token"] = p.get("claim_token")
                state["lease_expires_at"] = p.get("lease_expires_at")
                state["attempt_number"] = p.get("attempt_number", 1)
                state["current_status"] = "CLAIMED"
                state["updated_at"] = event["occurred_at"]

            elif et == "HANDOFF_STARTED":
                state["current_status"] = "STARTED"
                state["updated_at"] = event["occurred_at"]

            elif et == "HANDOFF_COMPLETED":
                state["current_status"] = "COMPLETED"
                state["artifact_id"] = p.get("artifact_id")
                state["artifact_hash"] = p.get("artifact_hash")
                state["updated_at"] = event["occurred_at"]

            elif et == "HANDOFF_FAILED":
                state["current_status"] = "FAILED"
                state["failure_code"] = p.get("failure_code")
                state["failure_class"] = p.get("failure_class")
                state["updated_at"] = event["occurred_at"]

            elif et == "HANDOFF_RETRY_SCHEDULED":
                state["current_status"] = "RETRY_SCHEDULED"
                state["retry_after"] = p.get("retry_after")
                state["failure_code"] = p.get("failure_code")
                state["updated_at"] = event["occurred_at"]

            elif et in ("HANDOFF_EXPIRED", "HANDOFF_CANCELLED"):
                state["current_status"] = STATUS_EVENTS[et]
                state["updated_at"] = event["occurred_at"]

            elif et == "HANDOFF_RELEASED":
                state["current_status"] = "PENDING"
                state["worker_id"] = None
                state["claim_token"] = None
                state["lease_expires_at"] = None
                state["updated_at"] = event["occurred_at"]

        return state

    def get_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        """Get current projection state for a handoff by replaying its event stream."""
        events = self._get_stream_events(handoff_id)
        if not events:
            return None
        return self._replay(events)

    def _get_active_claim(self, handoff_id: str) -> str | None:
        """Return the worker_id of the active claim, or None if no active lease.

        An active claim exists when the handoff is CLAIMED or STARTED and the
        lease has not expired.
        """
        handoff = self.get_handoff(handoff_id)
        if not handoff or handoff["current_status"] not in ("CLAIMED", "STARTED"):
            return None

        lease_expires = handoff.get("lease_expires_at")
        if lease_expires:
            try:
                expires = datetime.fromisoformat(lease_expires)
                if expires > datetime.now(timezone.utc):
                    return handoff.get("worker_id")
            except (ValueError, TypeError):
                pass
        return None

    # ── Transition validation ─────────────────────────────────────────────

    def _validate_transition(
        self, from_status: str | None, target_status: str, handoff_id: str
    ) -> None:
        """Raise ValueError if the transition is not allowed by the state machine."""
        if from_status is None:
            # First event for this handoff; enqueue/blocked are the only valid entry points
            if target_status not in ("PENDING", "BLOCKED"):
                raise ValueError(
                    f"Invalid initial status for {handoff_id}: {target_status}"
                )
            return

        if from_status in TERMINAL_STATUSES:
            raise ValueError(
                f"Handoff {handoff_id} is in terminal status {from_status}; "
                f"cannot transition to {target_status}"
            )

        allowed = STATE_TRANSITIONS.get(from_status, set())
        if target_status not in allowed:
            raise ValueError(
                f"Invalid transition for {handoff_id}: "
                f"{from_status} -> {target_status} (allowed: {sorted(allowed)})"
            )

    # ── Public API ────────────────────────────────────────────────────────

    def enqueue(self, handoff: dict[str, Any], actor_id: str = "alex") -> dict[str, Any]:
        """Enqueue a new handoff. Validates agents, task type, budget, and input.

        Required fields:
            handoff_id, from_agent, to_agent, task_type, task_summary
        Must also provide input_hash or input_snapshot_id.

        If the target agent is NOT_READY, the handoff is BLOCKED (not rejected).
        """
        # Validate required fields
        required = ["handoff_id", "from_agent", "to_agent", "task_type", "task_summary"]
        for field in required:
            if field not in handoff:
                raise ValueError(f"Missing required field: {field}")

        # Validate agents exist
        self._validate_agent(handoff["from_agent"])
        self._validate_agent(handoff["to_agent"])

        # Validate task type
        task_type = handoff["task_type"]
        if task_type in FORBIDDEN_TASK_TYPES:
            raise ValueError(f"Forbidden task type: {task_type}")
        if task_type not in ALLOWED_TASK_TYPES:
            raise ValueError(f"Unknown task type: {task_type}")

        # Validate budget
        max_budget = handoff.get("max_budget_usd", 0)
        if not isinstance(max_budget, (int, float)) or max_budget < 0:
            raise ValueError(
                f"Invalid max_budget_usd: {max_budget} (must be non-negative number)"
            )

        # Validate input reference
        input_hash = handoff.get("input_hash", "")
        input_snapshot_id = handoff.get("input_snapshot_id", "")
        if not input_hash and not input_snapshot_id:
            raise ValueError("Must provide input_hash or input_snapshot_id")

        # Check target readiness
        to_agent_id = handoff["to_agent"]
        agent_info = AGENT_REGISTRY.get(to_agent_id, {})
        target_status = agent_info.get("status", "UNKNOWN")

        # Idempotency check
        idempotency_key = handoff.get("idempotency_key", "")
        if idempotency_key:
            existing = self._check_idempotency(idempotency_key, handoff["handoff_id"])
            if existing:
                return existing

        # Check for duplicate handoff_id
        existing = self._get_stream_events(handoff["handoff_id"])
        if existing:
            raise ValueError(f"Handoff already exists: {handoff['handoff_id']}")

        payload = {
            "handoff_id": handoff["handoff_id"],
            "parent_run_id": handoff.get("parent_run_id", ""),
            "parent_cio_action_id": handoff.get("parent_cio_action_id"),
            "operator_request_id": handoff.get("operator_request_id", ""),
            "from_agent": handoff["from_agent"],
            "to_agent": handoff["to_agent"],
            "task_type": handoff["task_type"],
            "task_summary": handoff["task_summary"],
            "input_snapshot_id": input_snapshot_id,
            "input_hash": input_hash,
            "evidence_refs": handoff.get("evidence_refs", []),
            "priority": handoff.get("priority", "MEDIUM"),
            "deadline": handoff.get("deadline"),
            "max_budget_usd": max_budget,
            "required_artifact_type": handoff.get("required_artifact_type", "any"),
            "required_schema_version": handoff.get("required_schema_version", ""),
            "idempotency_key": idempotency_key,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        event_type = "HANDOFF_ENQUEUED"
        if target_status == "NOT_READY":
            event_type = "HANDOFF_BLOCKED"
            payload["block_reason"] = f"Target agent {to_agent_id} has status NOT_READY"

        stream_events = self._get_stream_events(handoff["handoff_id"])
        prev_hash = (
            stream_events[-1]["event_hash"]
            if stream_events
            else self._get_last_event_hash()
        )

        event = build_event(
            event_type, handoff["handoff_id"], payload,
            "agent", actor_id, "advisory", prev_hash,
        )
        self._append_event(event)
        return event

    def claim(
        self,
        handoff_id: str,
        worker_id: str,
        claim_token: str | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Claim a handoff for work. Creates a time-limited lease with a claim token.

        Only PENDING handoffs can be claimed. The claim includes a lease that
        expires after LEASE_DURATION_MINUTES. The claim_token must be presented
        for subsequent operations (complete, fail, start, release).
        """
        current = self.get_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff not found: {handoff_id}")

        # Validate state transition
        self._validate_transition(current["current_status"], "CLAIMED", handoff_id)

        # Check deadline
        deadline = current.get("deadline")
        if deadline:
            try:
                deadline_dt = datetime.fromisoformat(deadline)
            except TypeError:
                pass
            else:
                if deadline_dt < datetime.now(timezone.utc):
                    raise ValueError(
                        f"Handoff {handoff_id} has passed its deadline ({deadline})"
                    )

        # Idempotency
        if idempotency_key:
            existing = self._check_idempotency(idempotency_key, handoff_id)
            if existing:
                return existing

        # Check no active claim already exists
        active_claim = self._get_active_claim(handoff_id)
        if active_claim:
            raise ValueError(
                f"Handoff {handoff_id} already claimed by {active_claim}"
            )

        if not claim_token:
            claim_token = uuid.uuid4().hex

        now = datetime.now(timezone.utc)
        lease_expires = now + timedelta(minutes=LEASE_DURATION_MINUTES)
        attempt_number = current.get("attempt_number", 0) + 1

        payload = {
            "handoff_id": handoff_id,
            "worker_id": worker_id,
            "claim_token": claim_token,
            "claimed_at": now.isoformat(),
            "lease_expires_at": lease_expires.isoformat(),
            "attempt_number": attempt_number,
            "idempotency_key": idempotency_key,
        }

        stream_events = self._get_stream_events(handoff_id)
        prev_hash = (
            stream_events[-1]["event_hash"]
            if stream_events
            else self._get_last_event_hash()
        )

        event = build_event(
            "HANDOFF_CLAIMED", handoff_id, payload,
            "agent", worker_id, "advisory", prev_hash,
        )
        self._append_event(event)
        return event

    def start(
        self,
        handoff_id: str,
        worker_id: str,
        claim_token: str,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Start work on a claimed handoff. Transitions CLAIMED -> STARTED."""
        current = self.get_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff not found: {handoff_id}")

        self._validate_transition(current["current_status"], "STARTED", handoff_id)

        # Validate claim token
        stored_token = current.get("claim_token")
        if stored_token and stored_token != claim_token:
            raise ValueError(
                f"Invalid claim token for {handoff_id}: "
                f"expected={stored_token[:12]}..., got={claim_token[:12]}..."
            )

        # Idempotency
        if idempotency_key:
            existing = self._check_idempotency(idempotency_key, handoff_id)
            if existing:
                return existing

        payload = {
            "handoff_id": handoff_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "idempotency_key": idempotency_key,
        }

        stream_events = self._get_stream_events(handoff_id)
        prev_hash = (
            stream_events[-1]["event_hash"]
            if stream_events
            else self._get_last_event_hash()
        )

        event = build_event(
            "HANDOFF_STARTED", handoff_id, payload,
            "agent", worker_id, "advisory", prev_hash,
        )
        self._append_event(event)
        return event

    def complete(
        self,
        handoff_id: str,
        artifact: dict[str, Any],
        claim_token: str,
        worker_id: str,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Complete a handoff with an artifact. Transitions CLAIMED/STARTED -> COMPLETED.

        Requires claim_token match and valid artifact with artifact_id and artifact_hash.
        """
        current = self.get_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff not found: {handoff_id}")

        self._validate_transition(
            current["current_status"], "COMPLETED", handoff_id
        )

        # Validate claim token
        stored_token = current.get("claim_token")
        if stored_token and stored_token != claim_token:
            raise ValueError(
                f"Invalid claim token for {handoff_id}: "
                f"expected={stored_token[:12]}..., got={claim_token[:12]}..."
            )

        # Check lease ownership
        active = self._get_active_claim(handoff_id)
        if not active:
            raise ValueError(f"No active claim for {handoff_id}")
        if worker_id != active:
            raise ValueError(
                f"Worker {worker_id} does not hold claim for {handoff_id} "
                f"(held by {active})"
            )

        # Validate artifact
        if not artifact.get("artifact_id"):
            raise ValueError("Artifact must have artifact_id")
        if not artifact.get("artifact_hash"):
            raise ValueError("Artifact must have artifact_hash")

        # Idempotency
        if idempotency_key:
            existing = self._check_idempotency(idempotency_key, handoff_id)
            if existing:
                return existing

        payload = {
            "handoff_id": handoff_id,
            "artifact_id": artifact["artifact_id"],
            "artifact_type": artifact.get("artifact_type", "unknown"),
            "artifact_hash": artifact["artifact_hash"],
            "artifact_schema_version": artifact.get("artifact_schema_version", ""),
            "summary": artifact.get("summary", ""),
            "evidence_refs": artifact.get("evidence_refs", []),
            "model_provenance_ref": artifact.get("model_provenance_ref", ""),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "idempotency_key": idempotency_key,
        }

        stream_events = self._get_stream_events(handoff_id)
        prev_hash = (
            stream_events[-1]["event_hash"]
            if stream_events
            else self._get_last_event_hash()
        )

        event = build_event(
            "HANDOFF_COMPLETED", handoff_id, payload,
            "agent", worker_id, "advisory", prev_hash,
        )
        self._append_event(event)
        return event

    def fail(
        self,
        handoff_id: str,
        failure_code: str,
        worker_id: str,
        claim_token: str = "",
        failure_class: str = "error",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Mark a handoff as failed. If retry attempts remain, schedules retry.

        Attempts < MAX_RETRY_ATTEMPTS -> HANDOFF_RETRY_SCHEDULED
        Attempts >= MAX_RETRY_ATTEMPTS -> HANDOFF_FAILED (terminal with retry option)
        """
        current = self.get_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff not found: {handoff_id}")

        # Validate claim token if provided
        stored_token = current.get("claim_token")
        if stored_token and claim_token and stored_token != claim_token:
            raise ValueError(
                f"Invalid claim token for {handoff_id}"
            )

        # Idempotency
        if idempotency_key:
            existing = self._check_idempotency(idempotency_key, handoff_id)
            if existing:
                return existing

        attempt_number = current.get("attempt_number", 1)

        # Determine if can retry
        if attempt_number < MAX_RETRY_ATTEMPTS:
            retry_after = datetime.now(timezone.utc) + timedelta(
                minutes=RETRY_BACKOFF[min(attempt_number - 1, len(RETRY_BACKOFF) - 1)]
            )
            actual_event = "HANDOFF_RETRY_SCHEDULED"
        else:
            retry_after = None
            actual_event = "HANDOFF_FAILED"

        # Validate transition
        self._validate_transition(
            current["current_status"],
            STATUS_EVENTS[actual_event],
            handoff_id,
        )

        payload = {
            "handoff_id": handoff_id,
            "failure_code": failure_code,
            "failure_class": failure_class,
            "attempt_number": attempt_number,
            "retry_after": retry_after.isoformat() if retry_after else None,
            "idempotency_key": idempotency_key,
        }

        stream_events = self._get_stream_events(handoff_id)
        prev_hash = (
            stream_events[-1]["event_hash"]
            if stream_events
            else self._get_last_event_hash()
        )

        event = build_event(
            actual_event, handoff_id, payload,
            "agent", worker_id, "advisory", prev_hash,
        )
        self._append_event(event)
        return event

    def expire(
        self,
        handoff_id: str,
        reason: str = "",
        actor_id: str = "system",
    ) -> dict[str, Any]:
        """Mark a handoff as expired (deadline passed). Terminal state."""
        current = self.get_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff not found: {handoff_id}")

        self._validate_transition(current["current_status"], "EXPIRED", handoff_id)

        payload = {
            "handoff_id": handoff_id,
            "reason": reason or f"Deadline passed: {current.get('deadline', 'unknown')}",
            "expired_at": datetime.now(timezone.utc).isoformat(),
        }

        stream_events = self._get_stream_events(handoff_id)
        prev_hash = (
            stream_events[-1]["event_hash"]
            if stream_events
            else self._get_last_event_hash()
        )

        event = build_event(
            "HANDOFF_EXPIRED", handoff_id, payload,
            "system", actor_id, "system", prev_hash,
        )
        self._append_event(event)
        return event

    def cancel(
        self,
        handoff_id: str,
        reason: str = "",
        actor_id: str = "alex",
    ) -> dict[str, Any]:
        """Cancel a handoff. Terminal state."""
        current = self.get_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff not found: {handoff_id}")

        self._validate_transition(current["current_status"], "CANCELLED", handoff_id)

        payload = {
            "handoff_id": handoff_id,
            "reason": reason,
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }

        stream_events = self._get_stream_events(handoff_id)
        prev_hash = (
            stream_events[-1]["event_hash"]
            if stream_events
            else self._get_last_event_hash()
        )

        event = build_event(
            "HANDOFF_CANCELLED", handoff_id, payload,
            "agent", actor_id, "advisory", prev_hash,
        )
        self._append_event(event)
        return event

    def release(
        self,
        handoff_id: str,
        claim_token: str,
        worker_id: str,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Release a claim, returning the handoff to PENDING. Re-claimable."""
        current = self.get_handoff(handoff_id)
        if not current:
            raise ValueError(f"Handoff not found: {handoff_id}")

        self._validate_transition(current["current_status"], "PENDING", handoff_id)

        # Validate claim token
        stored_token = current.get("claim_token")
        if stored_token and stored_token != claim_token:
            raise ValueError(
                f"Invalid claim token for {handoff_id}"
            )

        # Idempotency
        if idempotency_key:
            existing = self._check_idempotency(idempotency_key, handoff_id)
            if existing:
                return existing

        payload = {
            "handoff_id": handoff_id,
            "released_at": datetime.now(timezone.utc).isoformat(),
            "idempotency_key": idempotency_key,
        }

        stream_events = self._get_stream_events(handoff_id)
        prev_hash = (
            stream_events[-1]["event_hash"]
            if stream_events
            else self._get_last_event_hash()
        )

        event = build_event(
            "HANDOFF_RELEASED", handoff_id, payload,
            "agent", worker_id, "advisory", prev_hash,
        )
        self._append_event(event)
        return event

    # ── Query API ─────────────────────────────────────────────────────────

    def list_handoffs(
        self,
        status: str | None = None,
        from_agent: str | None = None,
        to_agent: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List handoffs with optional filtering by status, from_agent, or to_agent."""
        stream_ids: set[str] = set()
        if self.event_store_path.exists():
            with open(self.event_store_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    event = json.loads(line)
                    sid = event["stream_id"]
                    if sid != "queue-genesis" and sid not in stream_ids:
                        stream_ids.add(sid)

        results: list[dict[str, Any]] = []
        for sid in stream_ids:
            h = self.get_handoff(sid)
            if h is None:
                continue
            if status and h.get("current_status") != status:
                continue
            if from_agent and h.get("from_agent") != from_agent:
                continue
            if to_agent and h.get("to_agent") != to_agent:
                continue
            results.append(h)

        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results[:limit]

    # ── Integrity verification ────────────────────────────────────────────

    def verify_integrity(self) -> dict[str, Any]:
        """Verify hash chain integrity of the event log.

        Returns a dict with:
            valid: bool       — overall validity
            total_events: int — number of events in the log
            valid_events: int — number of valid events
            corrupt_events: list — events with corrupted hashes
            chain_breaks: list   — locations where prev_event_hash doesn't match
        """
        result: dict[str, Any] = {
            "valid": True,
            "total_events": 0,
            "valid_events": 0,
            "corrupt_events": [],
            "chain_breaks": [],
        }

        if not self.event_store_path.exists():
            return result

        prev_hash: str | None = None
        with open(self.event_store_path, "r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                result["total_events"] += 1

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    result["corrupt_events"].append({
                        "line": line_num,
                        "reason": "invalid_json",
                    })
                    result["valid"] = False
                    continue

                # Verify payload hash
                if "payload" in event and "payload_hash" in event:
                    computed = compute_payload_hash(event["payload"])
                    if computed != event["payload_hash"]:
                        result["corrupt_events"].append({
                            "line": line_num,
                            "reason": "payload_hash_mismatch",
                        })
                        result["valid"] = False

                # Verify event hash
                event_wo_hash = {k: v for k, v in event.items() if k != "event_hash"}
                computed_eh = compute_event_hash(event_wo_hash)
                if "event_hash" in event and computed_eh != event["event_hash"]:
                    result["corrupt_events"].append({
                        "line": line_num,
                        "reason": "event_hash_mismatch",
                    })
                    result["valid"] = False

                # Verify chain link
                if prev_hash is not None and event.get("prev_event_hash") != prev_hash:
                    result["chain_breaks"].append({"line": line_num})
                    result["valid"] = False

                prev_hash = event.get("event_hash")
                result["valid_events"] += 1

        if not result["corrupt_events"] and not result["chain_breaks"]:
            result["valid_events"] = result["total_events"]
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# Public convenience API
# ═══════════════════════════════════════════════════════════════════════════════


def enqueue_handoff(handoff: dict[str, Any], actor_id: str = "alex") -> dict[str, Any]:
    """Public API — authority-gated handoff creation.

    Convenience wrapper that creates a queue instance and enqueues the handoff.
    Only registered agents may enqueue.
    """
    q = AgentHandoffQueue()
    if actor_id not in AGENT_REGISTRY:
        raise ValueError(f"Unauthorized actor: {actor_id}")
    return q.enqueue(handoff, actor_id=actor_id)
