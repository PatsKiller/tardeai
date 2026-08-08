"""
CIO Outcome Store — Event-sourced outcome records for CIO actions.

P-2.8 component. Records operator dispositions and outcomes for CIO actions.
Each outcome is hash-chained. Never modifies policy, broker authority, or risk rules.
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


def compute_event_hash(envelope_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize_payload(envelope_without_hash).encode("utf-8")).hexdigest()


GENESIS_PREV_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

VALID_OUTCOME_STATUSES = frozenset({"POSITIVE", "NEGATIVE", "MIXED", "UNKNOWN", "NOT_MEASURABLE"})

VALID_DISPOSITIONS = frozenset({
    "ACKNOWLEDGED", "ACCEPTED", "DEFERRED", "REJECTED", "DONE", "CANCELLED",
})


class CIOOutcomeStore:
    """Event-sourced store for CIO action outcomes."""

    def __init__(self, store_path: str = "data/cio/cio_outcomes.jsonl"):
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
                return json.loads(last)["event_hash"]
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
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "OUTCOME_STORE_GENESIS",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "prev_event_hash": GENESIS_PREV_HASH,
            "payload_hash": compute_payload_hash({"message": "CIO Outcome Store initialized"}),
            "event_hash": "",
            "payload": {"message": "CIO Outcome Store initialized"},
        }
        event["event_hash"] = compute_event_hash({k: v for k, v in event.items() if k != "event_hash"})
        self._append(event)

    def record_outcome(
        self,
        *,
        cio_action_id: str,
        operator_disposition: str,
        confirmed_operator_action: str = "",
        outcome_status: str = "UNKNOWN",
        measurement_window: str = "",
        context_refs: Optional[list[str]] = None,
        result_summary: str = "",
        what_was_right: str = "",
        what_was_wrong: str = "",
        unknowns: str = "",
        actor: str = "system",
    ) -> dict[str, Any]:
        """Record an outcome for a CIO action."""
        if operator_disposition not in VALID_DISPOSITIONS:
            raise ValueError(f"Invalid disposition: {operator_disposition}")
        if outcome_status not in VALID_OUTCOME_STATUSES:
            raise ValueError(f"Invalid outcome status: {outcome_status}")

        payload = {
            "cio_action_id": cio_action_id,
            "operator_disposition": operator_disposition,
            "confirmed_operator_action": confirmed_operator_action,
            "outcome_status": outcome_status,
            "measurement_window": measurement_window,
            "context_refs": context_refs or [],
            "result_summary": result_summary,
            "what_was_right": what_was_right,
            "what_was_wrong": what_was_wrong,
            "unknowns": unknowns,
            "outcome_hash": compute_payload_hash({
                "cio_action_id": cio_action_id,
                "disposition": operator_disposition,
                "status": outcome_status,
            }),
        }

        fd = self._lock()
        try:
            prev = self._last_hash()
            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": "OUTCOME_RECORDED",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "prev_event_hash": prev,
                "payload_hash": compute_payload_hash(payload),
                "event_hash": "",
                "actor": actor,
                "payload": payload,
            }
            event["event_hash"] = compute_event_hash({k: v for k, v in event.items() if k != "event_hash"})
            self._append(event)
            return event
        finally:
            self._unlock(fd)

    def get_outcomes(self, cio_action_id: Optional[str] = None) -> list[dict[str, Any]]:
        outcomes: list[dict[str, Any]] = []
        if not self.store_path.exists():
            return outcomes
        with open(self.store_path) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e["event_type"] == "OUTCOME_RECORDED":
                    if cio_action_id is None or e["payload"].get("cio_action_id") == cio_action_id:
                        outcomes.append(e)
        return outcomes
