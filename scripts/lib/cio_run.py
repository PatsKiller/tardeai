"""
CIO Run / Case Orchestrator — Durable CIO run lifecycle management.

Event-sourced append-only store for CIO advisory runs. Each run tracks:
- Lifecycle from QUEUED through COMPLETED
- Budget enforcement (calls, cost, time, specialist, hermes)
- Health gating
- Specialist and Hermes coordination
- Action and notification creation

Event store path: data/cio/cio_runs.jsonl
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# ═══════════════════════════════════════════════════════════════════════════════
# Canonical constants
# ═══════════════════════════════════════════════════════════════════════════════

VALID_EVENT_TYPES = frozenset({
    "CIO_RUN_CREATED",
    "CIO_RUN_STARTED",
    "CIO_RUN_RESUMED",
    "CIO_RUN_HEALTH_CHECKED",
    "CIO_RUN_EVIDENCE_BUILT",
    "CIO_RUN_WAITING_SPECIALISTS",
    "CIO_RUN_WAITING_HERMES",
    "CIO_RUN_SPECIALIST_REQUESTED",
    "CIO_RUN_SPECIALIST_COMPLETED",
    "CIO_RUN_HERMES_REQUESTED",
    "CIO_RUN_HERMES_COMPLETED",
    "CIO_RUN_SYNTHESIS_STARTED",
    "CIO_RUN_SYNTHESIS_COMPLETED",
    "CIO_RUN_ACTION_CREATED",
    "CIO_RUN_NOTIFICATION_ENQUEUED",
    "CIO_RUN_COMPLETED",
    "CIO_RUN_BLOCKED",
    "CIO_RUN_UNBLOCKED",
    "CIO_RUN_FAILED",
    "CIO_RUN_CANCELLED",
    "CIO_RUN_EXPIRED",
    "CIO_RUN_COST_RESERVED",
    "CIO_RUN_COST_SETTLED",
    "CIO_RUN_MODEL_CALL_RECORDED",
    "CIO_RUN_GENESIS",
})

RUN_STATUSES = frozenset({
    "QUEUED",
    "HEALTH_CHECK",
    "EVIDENCE_BUILD",
    "WAITING_FOR_SPECIALISTS",
    "WAITING_FOR_HERMES",
    "SPECIALIST_REVIEW",
    "HERMES_CHALLENGE",
    "CIO_SYNTHESIS",
    "ACTION_WRITE",
    "NOTIFICATION_ENQUEUE",
    "COMPLETED",
    "BLOCKED",
    "FAILED",
    "CANCELLED",
    "EXPIRED",
})

TERMINAL_STATUSES = frozenset({"COMPLETED", "BLOCKED", "FAILED", "CANCELLED", "EXPIRED"})

# Valid lifecycle transitions
STATE_TRANSITIONS: dict[str, set[str]] = {
    "QUEUED": {"HEALTH_CHECK", "CANCELLED", "EXPIRED"},
    "HEALTH_CHECK": {"EVIDENCE_BUILD", "BLOCKED", "FAILED", "CANCELLED"},
    "EVIDENCE_BUILD": {"WAITING_FOR_SPECIALISTS", "WAITING_FOR_HERMES", "SPECIALIST_REVIEW", "CIO_SYNTHESIS", "BLOCKED", "FAILED", "CANCELLED", "EXPIRED"},
    "WAITING_FOR_SPECIALISTS": {"EVIDENCE_BUILD", "CIO_SYNTHESIS", "BLOCKED", "FAILED", "CANCELLED", "EXPIRED"},
    "WAITING_FOR_HERMES": {"EVIDENCE_BUILD", "CIO_SYNTHESIS", "BLOCKED", "FAILED", "CANCELLED", "EXPIRED"},
    "SPECIALIST_REVIEW": {"WAITING_FOR_SPECIALISTS", "HERMES_CHALLENGE", "CIO_SYNTHESIS", "BLOCKED", "FAILED", "CANCELLED", "EXPIRED"},
    "HERMES_CHALLENGE": {"WAITING_FOR_HERMES", "CIO_SYNTHESIS", "BLOCKED", "FAILED", "CANCELLED", "EXPIRED"},
    "CIO_SYNTHESIS": {"ACTION_WRITE", "HERMES_CHALLENGE", "WAITING_FOR_SPECIALISTS", "WAITING_FOR_HERMES", "COMPLETED", "BLOCKED", "FAILED", "CANCELLED", "EXPIRED", "SPECIALIST_REVIEW"},
    "ACTION_WRITE": {"NOTIFICATION_ENQUEUE", "COMPLETED", "BLOCKED", "FAILED", "CANCELLED", "EXPIRED"},
    "NOTIFICATION_ENQUEUE": {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED", "EXPIRED"},
    "COMPLETED": set(),
    "BLOCKED": {"QUEUED", "CANCELLED", "EXPIRED", "FAILED"},
    "FAILED": set(),
    "CANCELLED": set(),
    "EXPIRED": set(),
}

TRANSITION_EVENT_MAP: dict[str, str] = {
    "QUEUED": "CIO_RUN_CREATED",
    "HEALTH_CHECK": "CIO_RUN_HEALTH_CHECKED",
    "EVIDENCE_BUILD": "CIO_RUN_EVIDENCE_BUILT",
    "WAITING_FOR_SPECIALISTS": "CIO_RUN_WAITING_SPECIALISTS",
    "WAITING_FOR_HERMES": "CIO_RUN_WAITING_HERMES",
    "SPECIALIST_REVIEW": "CIO_RUN_SPECIALIST_REQUESTED",
    "HERMES_CHALLENGE": "CIO_RUN_HERMES_REQUESTED",
    "CIO_SYNTHESIS": "CIO_RUN_SYNTHESIS_STARTED",
    "ACTION_WRITE": "CIO_RUN_ACTION_CREATED",
    "NOTIFICATION_ENQUEUE": "CIO_RUN_NOTIFICATION_ENQUEUED",
    "COMPLETED": "CIO_RUN_COMPLETED",
    "BLOCKED": "CIO_RUN_BLOCKED",
    "FAILED": "CIO_RUN_FAILED",
    "CANCELLED": "CIO_RUN_CANCELLED",
    "EXPIRED": "CIO_RUN_EXPIRED",
}

VALID_TRIGGER_TYPES = frozenset({
    "SCHEDULED_DAILY",
    "SCHEDULED_WEEKLY",
    "ACTION_FOLLOWUP",
    "HEALTH_EVENT",
    "SPECIALIST_COMPLETION",
    "HERMES_RESOLVED",
    "OPERATOR_MESSAGE",
    "MANUAL",
    "SYSTEM",
    "OPPORTUNITY_QUEUE",
})

VALID_PRIORITIES = frozenset({"LOW", "NORMAL", "HIGH", "CRITICAL"})

GENESIS_PREV_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

# Default budget limits
DEFAULT_MAX_PROVIDER_CALLS = 10
DEFAULT_MAX_COST_USD = 0.05
DEFAULT_MAX_WALL_TIME_MINUTES = 30
DEFAULT_MAX_SPECIALIST_CALLS = 5
DEFAULT_MAX_HERMES_CHALLENGES = 3

# Hard server-side caps (cannot be exceeded even if run requests more)
HARD_MAX_PROVIDER_CALLS = 20
HARD_MAX_COST_USD = 0.25
HARD_MAX_WALL_TIME_MINUTES = 60
HARD_MAX_SPECIALIST_CALLS = 10
HARD_MAX_HERMES_CHALLENGES = 5


# ═══════════════════════════════════════════════════════════════════════════════
# Deterministic serialization and hashing
# ═══════════════════════════════════════════════════════════════════════════════


def canonicalize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize_payload(payload).encode("utf-8")).hexdigest()


def compute_event_hash(
    event_id: str,
    event_type: str,
    occurred_at: str,
    prev_event_hash: str,
    payload_hash: str,
) -> str:
    raw = f"{event_id}|{event_type}|{occurred_at}|{prev_event_hash}|{payload_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_event(
    event_type: str,
    payload: dict[str, Any],
    prev_event_hash: str,
    *,
    actor: str = "system",
) -> dict[str, Any]:
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Invalid event type: {event_type}")
    event_id = str(uuid.uuid4())
    occurred_at = datetime.now(timezone.utc).isoformat()
    payload_hash = compute_payload_hash(payload)
    event_hash = compute_event_hash(event_id, event_type, occurred_at, prev_event_hash, payload_hash)
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "prev_event_hash": prev_event_hash,
        "payload_hash": payload_hash,
        "event_hash": event_hash,
        "actor": actor,
        "payload": payload,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CIORunStore
# ═══════════════════════════════════════════════════════════════════════════════


class CIORunStore:
    """Durable CIO run/case orchestrator with lifecycle and budget enforcement."""

    def __init__(self, store_path: str = "data/cio/cio_runs.jsonl"):
        self.store_path = Path(store_path)
        self.lock_path = Path(str(store_path) + ".lock")
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def _last_event_hash(self) -> str:
        if not self.store_path.exists():
            return GENESIS_PREV_HASH
        with open(self.store_path, "r") as f:
            last_line = None
            for line in f:
                stripped = line.strip()
                if stripped:
                    last_line = stripped
            if last_line is None:
                return GENESIS_PREV_HASH
            return json.loads(last_line)["event_hash"]

    def _acquire_lock(self) -> int:
        fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _release_lock(self, fd: int):
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    def _append_event(self, event: dict[str, Any]):
        line = json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n"
        with open(self.store_path, "a") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def _genesis(self):
        if self.store_path.exists():
            return
        event = build_event("CIO_RUN_GENESIS", {"message": "CIO run store initialized"}, GENESIS_PREV_HASH)
        self._append_event(event)

    def initialize(self):
        fd = self._acquire_lock()
        try:
            self._genesis()
        finally:
            self._release_lock(fd)

    # ── Budget helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _clamp_budget(
        max_provider_calls: int = DEFAULT_MAX_PROVIDER_CALLS,
        max_cost_usd: float = DEFAULT_MAX_COST_USD,
        max_wall_time_minutes: int = DEFAULT_MAX_WALL_TIME_MINUTES,
        max_specialist_calls: int = DEFAULT_MAX_SPECIALIST_CALLS,
        max_hermes_challenges: int = DEFAULT_MAX_HERMES_CHALLENGES,
    ) -> dict[str, Any]:
        """Clamp budget values to hard caps."""
        return {
            "max_provider_calls": min(max_provider_calls, HARD_MAX_PROVIDER_CALLS),
            "max_cost_usd": min(max_cost_usd, HARD_MAX_COST_USD),
            "max_wall_time_minutes": min(max_wall_time_minutes, HARD_MAX_WALL_TIME_MINUTES),
            "max_specialist_calls": min(max_specialist_calls, HARD_MAX_SPECIALIST_CALLS),
            "max_hermes_challenges": min(max_hermes_challenges, HARD_MAX_HERMES_CHALLENGES),
        }

    def _is_budget_exceeded(self, run: dict[str, Any]) -> Optional[str]:
        """Check if any budget limit is exceeded. Returns failure reason or None."""
        budget = run.get("budget", {})
        counters = run.get("counters", {})

        if counters.get("provider_calls", 0) >= budget.get("max_provider_calls", DEFAULT_MAX_PROVIDER_CALLS):
            return "BUDGET_EXCEEDED:provider_calls"
        if counters.get("cost_usd", 0.0) >= budget.get("max_cost_usd", DEFAULT_MAX_COST_USD):
            return "BUDGET_EXCEEDED:cost_usd"
        if counters.get("specialist_calls", 0) >= budget.get("max_specialist_calls", DEFAULT_MAX_SPECIALIST_CALLS):
            return "BUDGET_EXCEEDED:specialist_calls"
        if counters.get("hermes_challenges", 0) >= budget.get("max_hermes_challenges", DEFAULT_MAX_HERMES_CHALLENGES):
            return "BUDGET_EXCEEDED:hermes_challenges"
        return None

    def _project_run(self, run_id: str) -> Optional[dict[str, Any]]:
        """Rebuild current run state from all events for the given run_id."""
        if not self.store_path.exists():
            return None
        run = None
        with open(self.store_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                payload = event.get("payload", {})
                if payload.get("run_id") != run_id:
                    continue

                etype = event["event_type"]
                if etype == "CIO_RUN_CREATED":
                    run = {
                        "run_id": run_id,
                        "case_id": payload.get("case_id"),
                        "trigger_type": payload.get("trigger_type"),
                        "trigger_ref": payload.get("trigger_ref"),
                        "trigger_hash": payload.get("trigger_hash"),
                        "created_at": event["occurred_at"],
                        "started_at": None,
                        "completed_at": None,
                        "status": "QUEUED",
                        "priority": payload.get("priority", "NORMAL"),
                        "required_domains": payload.get("required_domains", []),
                        "health_decision_id": None,
                        "input_snapshot_id": None,
                        "input_hash": payload.get("input_hash"),
                        "operator_profile_version": payload.get("operator_profile_version"),
                        "ips_version": payload.get("ips_version"),
                        "budget": self._clamp_budget(
                            max_provider_calls=payload.get("max_provider_calls", DEFAULT_MAX_PROVIDER_CALLS),
                            max_cost_usd=payload.get("max_cost_usd", DEFAULT_MAX_COST_USD),
                            max_wall_time_minutes=payload.get("max_wall_time_minutes", DEFAULT_MAX_WALL_TIME_MINUTES),
                            max_specialist_calls=payload.get("max_specialist_calls", DEFAULT_MAX_SPECIALIST_CALLS),
                            max_hermes_challenges=payload.get("max_hermes_challenges", DEFAULT_MAX_HERMES_CHALLENGES),
                        ),
                        "counters": {
                            "provider_calls": 0,
                            "cost_usd": 0.0,
                            "specialist_calls": 0,
                            "hermes_challenges": 0,
                        },
                        "parent_action_ids": payload.get("parent_action_ids", []),
                        "parent_handoff_ids": payload.get("parent_handoff_ids", []),
                        "specialist_requests": [],
                        "specialist_artifact_refs": [],
                        "hermes_challenge_ids": [],
                        "model_process_ids": [],
                        "model_call_refs": [],
                        "cost_reserved": 0.0,
                        "cost_settled": 0.0,
                        "cio_artifact_id": None,
                        "created_action_ids": [],
                        "notification_ids": [],
                        "failure_code": None,
                        "next_check_at": None,
                        "context": payload.get("context") or {},
                        "last_event_hash": event["event_hash"],
                        "last_event_type": etype,
                    }
                elif run is not None:
                    self._apply_event(run, event)
        return run

    def _apply_event(self, run: dict[str, Any], event: dict[str, Any]):
        """Apply a single event to a run projection."""
        etype = event["event_type"]
        payload = event.get("payload", {})

        if etype == "CIO_RUN_STARTED":
            run["started_at"] = event["occurred_at"]
        elif etype == "CIO_RUN_RESUMED":
            run["status"] = "EVIDENCE_BUILD"
            run["resumed_at"] = event["occurred_at"]
            run["resume_count"] = run.get("resume_count", 0) + 1
        elif etype == "CIO_RUN_HEALTH_CHECKED":
            run["status"] = "HEALTH_CHECK"
            run["health_decision_id"] = payload.get("health_decision_id")
            if run.get("started_at") is None:
                run["started_at"] = event["occurred_at"]
        elif etype == "CIO_RUN_EVIDENCE_BUILT":
            run["status"] = "EVIDENCE_BUILD"
            run["input_snapshot_id"] = payload.get("input_snapshot_id")
            if payload.get("health_decision_id"):
                run["health_decision_id"] = payload["health_decision_id"]
        elif etype == "CIO_RUN_WAITING_SPECIALISTS":
            run["status"] = "WAITING_FOR_SPECIALISTS"
            run["waiting_since"] = event["occurred_at"]
        elif etype == "CIO_RUN_WAITING_HERMES":
            run["status"] = "WAITING_FOR_HERMES"
            run["waiting_since"] = event["occurred_at"]
        elif etype == "CIO_RUN_SPECIALIST_REQUESTED":
            run["status"] = "SPECIALIST_REVIEW"
            if payload.get("input_snapshot_id"):
                run["input_snapshot_id"] = payload["input_snapshot_id"]
            hid = payload.get("handoff_id")
            if hid:
                run["specialist_requests"].append(hid)
                run["counters"]["specialist_calls"] += 1
        elif etype == "CIO_RUN_SPECIALIST_COMPLETED":
            run["specialist_artifact_refs"].append(payload.get("artifact_id"))
        elif etype == "CIO_RUN_HERMES_REQUESTED":
            run["status"] = "HERMES_CHALLENGE"
            run["hermes_challenge_ids"].append(payload.get("challenge_id"))
            run["counters"]["hermes_challenges"] += 1
        elif etype == "CIO_RUN_HERMES_COMPLETED":
            pass
        elif etype == "CIO_RUN_SYNTHESIS_STARTED":
            run["status"] = "CIO_SYNTHESIS"
            if payload.get("input_snapshot_id"):
                run["input_snapshot_id"] = payload["input_snapshot_id"]
        elif etype == "CIO_RUN_SYNTHESIS_COMPLETED":
            run["cio_artifact_id"] = payload.get("cio_artifact_id")
        elif etype == "CIO_RUN_ACTION_CREATED":
            run["status"] = "ACTION_WRITE"
            action_id = payload.get("action_id")
            if action_id:
                run["created_action_ids"].append(action_id)
        elif etype == "CIO_RUN_NOTIFICATION_ENQUEUED":
            run["status"] = "NOTIFICATION_ENQUEUE"
            nid = payload.get("notification_id")
            if nid:
                run["notification_ids"].append(nid)
        elif etype == "CIO_RUN_COMPLETED":
            run["status"] = "COMPLETED"
            run["completed_at"] = event["occurred_at"]
            if payload.get("cio_artifact_id"):
                run["cio_artifact_id"] = payload["cio_artifact_id"]
        elif etype == "CIO_RUN_BLOCKED":
            run["status"] = "BLOCKED"
            run["failure_code"] = payload.get("reason")
        elif etype == "CIO_RUN_UNBLOCKED":
            run["status"] = "QUEUED"
            run["failure_code"] = None
        elif etype == "CIO_RUN_FAILED":
            run["status"] = "FAILED"
            run["completed_at"] = event["occurred_at"]
            run["failure_code"] = payload.get("reason")
        elif etype == "CIO_RUN_CANCELLED":
            run["status"] = "CANCELLED"
            run["completed_at"] = event["occurred_at"]
        elif etype == "CIO_RUN_EXPIRED":
            run["status"] = "EXPIRED"
            run["completed_at"] = event["occurred_at"]
        elif etype == "CIO_RUN_COST_RESERVED":
            run["cost_reserved"] += payload.get("amount_usd", 0.0)
        elif etype == "CIO_RUN_COST_SETTLED":
            run["cost_settled"] += payload.get("amount_usd", 0.0)
        elif etype == "CIO_RUN_MODEL_CALL_RECORDED":
            run["counters"]["provider_calls"] += 1
            run["counters"]["cost_usd"] += payload.get("cost_usd", 0.0)
            run["model_call_refs"].append(payload.get("call_ref"))

        run["last_event_hash"] = event["event_hash"]
        run["last_event_type"] = etype

    # ── Public API ──────────────────────────────────────────────────────────

    def create_run(
        self,
        *,
        trigger_type: str,
        trigger_ref: str = "",
        case_id: Optional[str] = None,
        priority: str = "NORMAL",
        required_domains: Optional[list[str]] = None,
        input_hash: Optional[str] = None,
        operator_profile_version: Optional[int] = None,
        ips_version: Optional[int] = None,
        parent_action_ids: Optional[list[str]] = None,
        parent_handoff_ids: Optional[list[str]] = None,
        max_provider_calls: int = DEFAULT_MAX_PROVIDER_CALLS,
        max_cost_usd: float = DEFAULT_MAX_COST_USD,
        max_wall_time_minutes: int = DEFAULT_MAX_WALL_TIME_MINUTES,
        max_specialist_calls: int = DEFAULT_MAX_SPECIALIST_CALLS,
        max_hermes_challenges: int = DEFAULT_MAX_HERMES_CHALLENGES,
        context: Optional[dict[str, Any]] = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        """Create a new CIO advisory run."""
        if trigger_type not in VALID_TRIGGER_TYPES:
            raise ValueError(f"Invalid trigger_type: {trigger_type}. Valid: {sorted(VALID_TRIGGER_TYPES)}")
        if priority not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {priority}. Valid: {sorted(VALID_PRIORITIES)}")

        run_id = str(uuid.uuid4())
        if case_id is None:
            case_id = run_id

        trigger_hash = hashlib.sha256(
            f"{trigger_type}:{trigger_ref}:{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()

        payload = {
            "run_id": run_id,
            "case_id": case_id,
            "trigger_type": trigger_type,
            "trigger_ref": trigger_ref,
            "trigger_hash": trigger_hash,
            "priority": priority,
            "required_domains": required_domains or [],
            "input_hash": input_hash,
            "operator_profile_version": operator_profile_version,
            "ips_version": ips_version,
            "parent_action_ids": parent_action_ids or [],
            "parent_handoff_ids": parent_handoff_ids or [],
            "max_provider_calls": max_provider_calls,
            "max_cost_usd": max_cost_usd,
            "max_wall_time_minutes": max_wall_time_minutes,
            "max_specialist_calls": max_specialist_calls,
            "max_hermes_challenges": max_hermes_challenges,
            "context": context or {},
        }

        fd = self._acquire_lock()
        try:
            prev_hash = self._last_event_hash()
            event = build_event("CIO_RUN_CREATED", payload, prev_hash, actor=actor)
            self._append_event(event)
            return event
        finally:
            self._release_lock(fd)

    def transition(
        self,
        run_id: str,
        to_status: str,
        *,
        actor: str = "system",
        **payload_kwargs,
    ) -> dict[str, Any]:
        """Transition a run to a new status, validating the lifecycle."""
        if to_status not in RUN_STATUSES:
            raise ValueError(f"Invalid status: {to_status}")

        current = self.get_run(run_id)
        if current is None:
            raise ValueError(f"Run not found: {run_id}")

        current_status = current["status"]
        allowed = STATE_TRANSITIONS.get(current_status, set())
        if to_status not in allowed:
            raise ValueError(
                f"Invalid transition: {current_status} -> {to_status}. "
                f"Allowed: {sorted(allowed)}"
            )

        # Check budget before non-terminal transitions
        if to_status not in TERMINAL_STATUSES:
            exceeded = self._is_budget_exceeded(current)
            if exceeded:
                raise ValueError(f"Cannot transition: {exceeded}")

        # Check wall time
        if current.get("started_at"):
            started = datetime.fromisoformat(current["started_at"])
            budget = current.get("budget", {})
            max_minutes = budget.get("max_wall_time_minutes", DEFAULT_MAX_WALL_TIME_MINUTES)
            elapsed = (datetime.now(timezone.utc) - started).total_seconds() / 60.0
            if elapsed > max_minutes and to_status not in TERMINAL_STATUSES:
                raise ValueError(f"BUDGET_EXCEEDED:wall_time ({elapsed:.1f}m > {max_minutes}m)")

        payload = {
            "run_id": run_id,
            "from_status": current_status,
            "to_status": to_status,
            **payload_kwargs,
        }

        event_type = TRANSITION_EVENT_MAP.get(to_status, f"CIO_RUN_{to_status}")
        if event_type not in VALID_EVENT_TYPES:
            event_type = "CIO_RUN_COMPLETED"  # fallback: treat unknown as completion

        fd = self._acquire_lock()
        try:
            prev_hash = self._last_event_hash()
            event = build_event(event_type, payload, prev_hash, actor=actor)
            self._append_event(event)
            return event
        finally:
            self._release_lock(fd)

    def start(self, run_id: str, *, actor: str = "system") -> dict[str, Any]:
        """Start a run (QUEUED -> HEALTH_CHECK)."""
        return self.transition(run_id, "HEALTH_CHECK", actor=actor)

    def health_checked(
        self, run_id: str, health_decision_id: str, *, actor: str = "system"
    ) -> dict[str, Any]:
        """Record health check result."""
        return self.transition(
            run_id, "EVIDENCE_BUILD",
            health_decision_id=health_decision_id,
            actor=actor,
        )

    def evidence_built(
        self, run_id: str, input_snapshot_id: str, *, actor: str = "system"
    ) -> dict[str, Any]:
        """Record evidence build completion. Must be in EVIDENCE_BUILD state."""
        run = self.get_run(run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")
        if run["status"] != "EVIDENCE_BUILD":
            raise ValueError(f"Cannot build evidence from {run['status']} state. Must be EVIDENCE_BUILD.")
        next_status = "SPECIALIST_REVIEW" if run.get("specialist_requests") else "CIO_SYNTHESIS"
        return self.transition(
            run_id, next_status,
            input_snapshot_id=input_snapshot_id,
            actor=actor,
        )

    def wait_for_specialists(
        self, run_id: str, outstanding_handoff_ids: list[str], *, actor: str = "system"
    ) -> dict[str, Any]:
        """Transition run to WAITING_FOR_SPECIALISTS. Alex call count = 0, action = 0."""
        return self.transition(
            run_id, "WAITING_FOR_SPECIALISTS",
            outstanding_handoff_ids=outstanding_handoff_ids,
            actor=actor,
        )

    def wait_for_hermes(
        self, run_id: str, outstanding_challenge_ids: list[str], *, actor: str = "system"
    ) -> dict[str, Any]:
        """Transition run to WAITING_FOR_HERMES. No Alex synthesis until resolved."""
        return self.transition(
            run_id, "WAITING_FOR_HERMES",
            outstanding_challenge_ids=outstanding_challenge_ids,
            actor=actor,
        )

    def resume(
        self, run_id: str, resume_reason: str, *, actor: str = "system"
    ) -> dict[str, Any]:
        """Resume a run from WAITING_FOR_SPECIALISTS or WAITING_FOR_HERMES.
        
        Replays state back to EVIDENCE_BUILD so the worker can re-evaluate
        with newly completed specialists/challenges.
        """
        current = self.get_run(run_id)
        if current is None:
            raise ValueError(f"Run not found: {run_id}")
        if current["status"] not in ("WAITING_FOR_SPECIALISTS", "WAITING_FOR_HERMES"):
            raise ValueError(f"Cannot resume run in status: {current['status']}")
        return self.transition(
            run_id, "EVIDENCE_BUILD",
            resume_reason=resume_reason,
            actor=actor,
        )

    def block(self, run_id: str, reason: str, *, actor: str = "system") -> dict[str, Any]:
        """Block a run (health issue, missing data, etc.)."""
        return self.transition(run_id, "BLOCKED", reason=reason, actor=actor)

    def unblock(self, run_id: str, *, actor: str = "system") -> dict[str, Any]:
        """Unblock a run, returning to QUEUED."""
        return self.transition(run_id, "QUEUED", actor=actor)

    def fail(self, run_id: str, reason: str, *, actor: str = "system") -> dict[str, Any]:
        """Fail a run with a reason."""
        return self.transition(run_id, "FAILED", reason=reason, actor=actor)

    def cancel(self, run_id: str, *, actor: str = "system") -> dict[str, Any]:
        """Cancel a run."""
        return self.transition(run_id, "CANCELLED", actor=actor)

    def complete(self, run_id: str, cio_artifact_id: str = "", *, actor: str = "system") -> dict[str, Any]:
        """Complete a run successfully."""
        return self.transition(run_id, "COMPLETED", cio_artifact_id=cio_artifact_id, actor=actor)

    def record_model_call(
        self, run_id: str, call_ref: str, cost_usd: float, *, actor: str = "system"
    ) -> dict[str, Any]:
        """Record a governed model call against the run budget."""
        current = self.get_run(run_id)
        if current is None:
            raise ValueError(f"Run not found: {run_id}")
        exceeded = self._is_budget_exceeded(current)
        if exceeded:
            raise ValueError(f"Cannot record model call: {exceeded}")

        payload = {
            "run_id": run_id,
            "call_ref": call_ref,
            "cost_usd": cost_usd,
        }
        fd = self._acquire_lock()
        try:
            prev_hash = self._last_event_hash()
            event = build_event("CIO_RUN_MODEL_CALL_RECORDED", payload, prev_hash, actor=actor)
            self._append_event(event)
            return event
        finally:
            self._release_lock(fd)

    def record_specialist_request(
        self, run_id: str, handoff_id: str, *, actor: str = "system"
    ) -> dict[str, Any]:
        """Record a specialist handoff request. Transitions to SPECIALIST_REVIEW if not already there."""
        current = self.get_run(run_id)
        if current is None:
            raise ValueError(f"Run not found: {run_id}")
        exceeded = self._is_budget_exceeded(current)
        if exceeded:
            raise ValueError(f"Cannot record specialist request: {exceeded}")

        if current["status"] == "SPECIALIST_REVIEW":
            # Already in specialist review — just append as a direct event
            payload = {"run_id": run_id, "handoff_id": handoff_id}
            fd = self._acquire_lock()
            try:
                prev_hash = self._last_event_hash()
                event = build_event("CIO_RUN_SPECIALIST_REQUESTED", payload, prev_hash, actor=actor)
                self._append_event(event)
                return event
            finally:
                self._release_lock(fd)
        else:
            return self.transition(
                run_id, "SPECIALIST_REVIEW",
                handoff_id=handoff_id,
                actor=actor,
            )

    def record_hermes_request(
        self, run_id: str, challenge_id: str, *, actor: str = "system"
    ) -> dict[str, Any]:
        """Record a Hermes challenge request. Transitions to HERMES_CHALLENGE if not already there."""
        current = self.get_run(run_id)
        if current is None:
            raise ValueError(f"Run not found: {run_id}")
        exceeded = self._is_budget_exceeded(current)
        if exceeded:
            raise ValueError(f"Cannot record Hermes request: {exceeded}")

        if current["status"] == "HERMES_CHALLENGE":
            # Already in hermes challenge — just append as a direct event
            payload = {"run_id": run_id, "challenge_id": challenge_id}
            fd = self._acquire_lock()
            try:
                prev_hash = self._last_event_hash()
                event = build_event("CIO_RUN_HERMES_REQUESTED", payload, prev_hash, actor=actor)
                self._append_event(event)
                return event
            finally:
                self._release_lock(fd)
        else:
            return self.transition(
                run_id, "HERMES_CHALLENGE",
                challenge_id=challenge_id,
                actor=actor,
            )

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        """Get current run projection."""
        return self._project_run(run_id)

    def list_runs(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List runs, optionally filtered by status."""
        seen = set()
        runs = []
        if not self.store_path.exists():
            return runs

        with open(self.store_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                payload = event.get("payload", {})
                rid = payload.get("run_id")
                if not rid or rid in seen:
                    continue
                if event["event_type"] != "CIO_RUN_CREATED":
                    continue
                seen.add(rid)

        for rid in seen:
            run = self._project_run(rid)
            if run is not None:
                if status is None or run["status"] == status:
                    runs.append(run)
                    if len(runs) >= limit:
                        break

        return runs

    def verify_integrity(self) -> tuple[bool, str]:
        """Verify hash chain integrity."""
        if not self.store_path.exists():
            return True, "No event store exists"

        prev_hash = GENESIS_PREV_HASH
        line_num = 0
        with open(self.store_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                line_num += 1
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError:
                    return False, f"Line {line_num}: JSON decode error"

                expected_prev = event.get("prev_event_hash")
                if expected_prev != prev_hash:
                    return False, f"Line {line_num}: Chain broken"

                event_id = event["event_id"]
                event_type = event["event_type"]
                occurred_at = event["occurred_at"]
                payload_hash = event["payload_hash"]
                computed = compute_event_hash(event_id, event_type, occurred_at, expected_prev, payload_hash)
                if computed != event["event_hash"]:
                    return False, f"Line {line_num}: Hash mismatch"

                prev_hash = event["event_hash"]

        return True, f"Chain verified ({line_num} events)"


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience functions
# ═══════════════════════════════════════════════════════════════════════════════


def create_cio_run(
    store_path: str = "data/cio/cio_runs.jsonl",
    *,
    trigger_type: str,
    **kwargs,
) -> dict[str, Any]:
    """Convenience: create a CIO run."""
    store = CIORunStore(store_path)
    store.initialize()
    return store.create_run(trigger_type=trigger_type, **kwargs)
