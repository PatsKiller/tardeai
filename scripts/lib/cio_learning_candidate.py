"""
CIO Learning Candidate Store — Records proposed learning improvements.

P-2.8 component. Records lessons learned from CIO advisory outcomes.
Allowed effects: retrieval weighting, confidence calibration, research checklists,
communication improvements, routing proposals.

NEVER changes: broker authority, risk policy, model portfolio, tax strategy,
execution rules, provider budget, process registry, scheduler, tool authority.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def canonicalize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize_payload(payload).encode("utf-8")).hexdigest()


GENESIS_PREV_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

ALLOWED_EFFECTS = frozenset({
    "retrieval_weighting",
    "confidence_calibration",
    "research_checklist",
    "communication_improvement",
    "routing_proposal",
})

FORBIDDEN_EFFECTS = frozenset({
    "broker_authority",
    "risk_policy",
    "model_portfolio",
    "tax_strategy",
    "execution_rules",
    "provider_budget",
    "process_registry",
    "scheduler",
    "tool_authority",
})


class CIOLearningCandidateStore:
    """Event-sourced store for proposed learning improvements."""

    def __init__(self, store_path: str = "data/cio/cio_learning_candidates.jsonl"):
        self.store_path = Path(store_path)
        self.lock_path = Path(str(store_path) + ".lock")
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._genesis()

    def _last_hash(self) -> str:
        if not self.store_path.exists():
            return GENESIS_PREV_HASH
        with open(self.store_path) as f:
            last = None
            for line in f:
                if line.strip():
                    last = line.strip()
            if last:
                return json.loads(last).get("event_hash", GENESIS_PREV_HASH)
            return GENESIS_PREV_HASH

    def _lock(self) -> int:
        fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _unlock(self, fd: int):
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    def _append(self, event: dict[str, Any]):
        line = json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n"
        with open(self.store_path, "a") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def _genesis(self):
        if self.store_path.exists():
            return
        payload = {"message": "CIO Learning Candidate Store initialized"}
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "LEARNING_STORE_GENESIS",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "prev_event_hash": GENESIS_PREV_HASH,
            "payload_hash": compute_payload_hash(payload),
            "payload": payload,
        }
        event["event_hash"] = compute_payload_hash(
            {k: v for k, v in event.items() if k != "event_hash"}
        )
        self._append(event)

    def create_candidate(
        self,
        *,
        lesson_title: str,
        description: str,
        proposed_effect: str,
        parent_outcome_id: str = "",
        parent_action_id: str = "",
        evidence: Optional[list[str]] = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        """Create a learning candidate.

        Args:
            proposed_effect: Must be one of ALLOWED_EFFECTS.
            Raises ValueError if effect is forbidden or unknown.
        """
        if proposed_effect in FORBIDDEN_EFFECTS:
            raise ValueError(
                f"Forbidden learning effect: {proposed_effect}. "
                f"Learning candidates cannot modify {proposed_effect}."
            )
        if proposed_effect not in ALLOWED_EFFECTS:
            raise ValueError(
                f"Unknown learning effect: {proposed_effect}. "
                f"Allowed: {sorted(ALLOWED_EFFECTS)}"
            )

        payload = {
            "lesson_title": lesson_title,
            "description": description,
            "proposed_effect": proposed_effect,
            "parent_outcome_id": parent_outcome_id,
            "parent_action_id": parent_action_id,
            "evidence": evidence or [],
            "status": "PROPOSED",
        }

        fd = self._lock()
        try:
            prev = self._last_hash()
            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": "LEARNING_CANDIDATE_CREATED",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "prev_event_hash": prev,
                "payload_hash": compute_payload_hash(payload),
                "actor": actor,
                "payload": payload,
            }
            event["event_hash"] = compute_payload_hash(
                {k: v for k, v in event.items() if k != "event_hash"}
            )
            self._append(event)
            return event
        finally:
            self._unlock(fd)

    def list_candidates(self) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        if not self.store_path.exists():
            return candidates
        with open(self.store_path) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e["event_type"] == "LEARNING_CANDIDATE_CREATED":
                    candidates.append(e)
        return candidates
