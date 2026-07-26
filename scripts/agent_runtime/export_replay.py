"""Deterministic JSONL export, replay and tamper detection for run journals.

Authoritative replay/verification requires a trusted manifest (or explicit expected
run id, event count, head hash, schema version and journal contract). The verifier
never crashes on hostile JSON — it returns deterministic findings. Replay is model-
and provider-free and byte-compatible with the in-memory ``ShadowRunJournal`` JSONL.
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
_CONNECTION_KEYS = frozenset({"dsn", "host", "port", "password", "user", "conninfo", "sslmode", "hostaddr"})


class ReplayError(ValueError):
    """Raised when a stream cannot be authoritatively replayed."""


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    event_count: int
    head_hash: str
    run_id: str | None = None
    issues: tuple[str, ...] = field(default_factory=tuple)


def export_manifest(persistence: RunPersistence, run_id: str) -> dict[str, Any]:
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
    lines: list[str] = []
    for event in persistence.journal(run_id):
        record = event.as_dict()
        _reject_connection_metadata(record)
        lines.append(canonical_json({key: record[key] for key in _EVENT_KEYS}))
    return lines


def _reject_connection_metadata(record: Any) -> None:
    if isinstance(record, Mapping):
        for key, child in record.items():
            if str(key).lower() in _CONNECTION_KEYS:
                raise ValueError(f"connection metadata must never be exported: {key}")
            _reject_connection_metadata(child)
    elif isinstance(record, (list, tuple)):
        for child in record:
            _reject_connection_metadata(child)


def verify_jsonl(lines: Sequence[str], *, manifest: Mapping[str, Any] | None = None) -> VerificationResult:
    """Detect missing, reordered, duplicated, modified, malformed or mixed-run records.

    Never raises on hostile input — returns deterministic findings. When ``manifest`` is
    supplied it also enforces run id, event count, head hash, schema version and journal
    contract (catching truncated/padded/unknown-contract/mixed-run streams).
    """

    issues: list[str] = []
    previous = GENESIS_HASH
    head = GENESIS_HASH
    seen_sequences: set[Any] = set()
    expected_sequence = 1
    run_id: str | None = None
    if manifest is not None:
        run_id = manifest.get("run_id")
        if manifest.get("schema_version") != SCHEMA_VERSION:
            issues.append("manifest schema_version does not match this runtime")
        if manifest.get("journal_contract") != JOURNAL_CONTRACT:
            issues.append("manifest journal_contract is unknown or incompatible")

    for index, raw in enumerate(lines, start=1):
        if not isinstance(raw, str):
            issues.append(f"line {index}: not a JSON string")
            break
        try:
            event = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            issues.append(f"line {index}: malformed JSON")
            break
        if not isinstance(event, dict):
            issues.append(f"line {index}: event is not a JSON object")
            break
        missing = [k for k in _EVENT_KEYS if k not in event]
        if missing:
            issues.append(f"line {index}: missing required keys {missing}")
            break
        seq = event["sequence"]
        if not isinstance(seq, int) or isinstance(seq, bool):
            issues.append(f"line {index}: sequence is not an integer")
            break
        this_run = event["run_id"]
        if run_id is None:
            run_id = this_run
        elif this_run != run_id:
            issues.append(f"line {index}: mixed-run stream (expected {run_id}, saw {this_run})")
        if seq in seen_sequences:
            issues.append(f"line {index}: duplicated sequence {seq}")
        seen_sequences.add(seq)
        if seq != expected_sequence:
            issues.append(f"line {index}: out-of-order or missing record (expected {expected_sequence}, saw {seq})")
        if event["previous_hash"] != previous:
            issues.append(f"line {index}: broken chain link (previous_hash mismatch)")
        if not isinstance(event["payload"], dict):
            issues.append(f"line {index}: payload is not an object")
            break
        try:
            recomputed = compute_event_hash(event_body(event["run_id"], seq, event["event_type"], event["payload"], event["created_at"], event["previous_hash"]))
        except Exception:
            issues.append(f"line {index}: uncomputable event body")
            break
        if recomputed != event["event_hash"]:
            issues.append(f"line {index}: modified record (event_hash mismatch)")
        previous = event["event_hash"]
        head = previous
        expected_sequence = seq + 1

    if manifest is not None:
        if manifest.get("event_count") != len(lines):
            issues.append(f"manifest event_count {manifest.get('event_count')} != {len(lines)} (truncated or padded)")
        if manifest.get("head_hash") != head:
            issues.append("manifest head_hash does not match the stream head (tampered tail)")
    return VerificationResult(ok=not issues, event_count=len(lines), head_hash=head, run_id=run_id, issues=tuple(issues))


def replay_jsonl(lines: Sequence[str], *, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Authoritatively fold the event stream into run state. Requires a trusted manifest.

    No model or provider call occurs. Raises ReplayError on any integrity failure.
    """

    if manifest is None:
        raise ReplayError("authoritative replay requires a trusted manifest")
    verification = verify_jsonl(lines, manifest=manifest)
    if not verification.ok:
        raise ReplayError(f"cannot replay a tampered journal: {verification.issues[0]}")
    state: dict[str, Any] = {"run_id": manifest.get("run_id"), "sequence": 0, "status": "UNKNOWN"}
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
    return state
