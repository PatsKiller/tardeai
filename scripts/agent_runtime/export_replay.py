"""Deterministic JSONL export, replay and tamper detection for run journals.

The export is a stable, hash-chained event stream that reconstructs run state without
any model or provider call. It excludes secrets and connection metadata, and it is
byte-compatible with the in-memory ``ShadowRunJournal`` JSONL so existing journal
tests keep working. Tamper detection catches missing, reordered, duplicated or
modified records purely from the chain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .contracts import canonical_json
from .persistence import (
    GENESIS_HASH,
    JOURNAL_CONTRACT,
    SCHEMA_VERSION,
    RunPersistence,
    compute_event_hash,
    event_body,
)

_EVENT_KEYS = ("run_id", "sequence", "event_type", "payload", "created_at", "previous_hash", "event_hash")
_CONNECTION_KEYS = frozenset({"dsn", "host", "port", "password", "user", "conninfo", "sslmode"})


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    event_count: int
    head_hash: str
    issues: tuple[str, ...] = field(default_factory=tuple)


def export_manifest(persistence: RunPersistence, run_id: str) -> dict[str, Any]:
    """Portable, secret-free manifest describing the exported stream."""

    events = persistence.journal(run_id)
    head = events[-1].event_hash if events else GENESIS_HASH
    return {
        "schema_version": SCHEMA_VERSION,
        "journal_contract": JOURNAL_CONTRACT,
        "run_id": run_id,
        "event_count": len(events),
        "head_hash": head,
    }


def export_run_jsonl(persistence: RunPersistence, run_id: str) -> list[str]:
    """Return the run journal as deterministic canonical-JSON lines, in stable order."""

    lines: list[str] = []
    for event in persistence.journal(run_id):
        record = event.as_dict()
        _reject_connection_metadata(record)
        # Canonical, sorted-key serialization -> identical bytes for identical events.
        lines.append(canonical_json({key: record[key] for key in _EVENT_KEYS}))
    return lines


def _reject_connection_metadata(record: Mapping[str, Any]) -> None:
    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if str(key).lower() in _CONNECTION_KEYS:
                    raise ValueError(f"connection metadata must never be exported: {key}")
                walk(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                walk(child)

    walk(record)


def replay_jsonl(lines: Sequence[str]) -> dict[str, Any]:
    """Fold the event stream into run state. No model or provider call occurs."""

    verification = verify_jsonl(lines)
    if not verification.ok:
        raise ValueError(f"cannot replay a tampered journal: {verification.issues[0]}")
    state: dict[str, Any] = {"run_id": None, "sequence": 0, "status": "UNKNOWN"}
    for raw in lines:
        event = json.loads(raw)
        state["run_id"] = event["run_id"]
        state["sequence"] = event["sequence"]
        state["last_event_type"] = event["event_type"]
        state["last_event_hash"] = event["event_hash"]
        state["updated_at"] = event["created_at"]
        payload = event.get("payload") or {}
        if "status" in payload:
            state["status"] = payload["status"]
        state["checkpoint"] = payload.get("checkpoint", state.get("checkpoint"))
    return state


def verify_jsonl(lines: Sequence[str], *, manifest: Mapping[str, Any] | None = None) -> VerificationResult:
    """Detect missing, reordered, duplicated or modified records from the chain alone."""

    issues: list[str] = []
    previous = GENESIS_HASH
    seen_sequences: set[int] = set()
    head = GENESIS_HASH
    expected_sequence = 1
    for index, raw in enumerate(lines, start=1):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            issues.append(f"line {index}: not valid JSON ({exc})")
            break
        sequence = event.get("sequence")
        if sequence in seen_sequences:
            issues.append(f"line {index}: duplicated sequence {sequence}")
        seen_sequences.add(sequence)
        if sequence != expected_sequence:
            issues.append(f"line {index}: out-of-order or missing record (expected sequence {expected_sequence}, saw {sequence})")
        if event.get("previous_hash") != previous:
            issues.append(f"line {index}: broken chain link (previous_hash mismatch)")
        recomputed = compute_event_hash(event_body(
            event.get("run_id"), event.get("sequence"), event.get("event_type"),
            event.get("payload") or {}, event.get("created_at"), event.get("previous_hash"),
        ))
        if recomputed != event.get("event_hash"):
            issues.append(f"line {index}: modified record (event_hash mismatch)")
        previous = event.get("event_hash")
        head = previous
        expected_sequence = (sequence or expected_sequence) + 1
    if manifest is not None:
        if manifest.get("event_count") != len(lines):
            issues.append(f"manifest event_count {manifest.get('event_count')} != {len(lines)} (truncated or padded)")
        if manifest.get("head_hash") != head:
            issues.append("manifest head_hash does not match the stream head (tampered tail)")
    return VerificationResult(ok=not issues, event_count=len(lines), head_hash=head, issues=tuple(issues))
