"""Durable provider request journal and canonical retry dispositions.

The journal records metadata and hashes only. It never persists prompts,
responses, credentials, or other provider payloads.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RETRY_SCHEMA = "RetryDisposition@v1"
JOURNAL_SCHEMA = "ProviderRequestJournal@v1"

RETRYABLE_TRANSIENT = "RETRYABLE_TRANSIENT"
NON_RETRYABLE_COST = "NON_RETRYABLE_COST"
NON_RETRYABLE_POLICY = "NON_RETRYABLE_POLICY"
NON_RETRYABLE_VALIDATION = "NON_RETRYABLE_VALIDATION"
AMBIGUOUS_PROVIDER_RESULT = "AMBIGUOUS_PROVIDER_RESULT"
CIRCUIT_OPEN = "CIRCUIT_OPEN"
DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"

HARD_DISPOSITIONS = frozenset({
    NON_RETRYABLE_COST,
    NON_RETRYABLE_POLICY,
    NON_RETRYABLE_VALIDATION,
    AMBIGUOUS_PROVIDER_RESULT,
    CIRCUIT_OPEN,
    DEADLINE_EXCEEDED,
})

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_journal_path() -> Path:
    configured = os.environ.get("CIO_PROVIDER_REQUEST_JOURNAL_JSONL")
    if configured:
        return Path(configured)
    cio_dir = os.environ.get("TRADEAI_CIO_DIR")
    if cio_dir:
        return Path(cio_dir) / "provider_request_journal.jsonl"
    return PROJECT_ROOT / "data" / "cio" / "provider_request_journal.jsonl"


def semantic_request_key(*, request_id: str, process_id: str, model_id: str) -> str:
    """Build a stable key without retaining request content."""
    material = f"{process_id}\0{model_id}\0{request_id}".encode("utf-8")
    return "prj_" + hashlib.sha256(material).hexdigest()


def classify_failure(
    code: str | None,
    *,
    request_sent: bool = False,
    http_status: int | None = None,
) -> dict[str, Any]:
    """Map one failure to the sole authoritative retry policy."""
    normalized = str(code or "").upper()
    if request_sent:
        disposition = AMBIGUOUS_PROVIDER_RESULT
    elif normalized in {"COST_CONFIGURATION_INVALID", "COST_CAP_EXCEEDED"}:
        disposition = NON_RETRYABLE_COST
    elif normalized in {"POLICY_NOT_ALLOWED", "PROCESS_NOT_REGISTERED", "UNKNOWN_PROCESS"}:
        disposition = NON_RETRYABLE_POLICY
    elif normalized in {
        "MODEL_MISMATCH", "LEGACY_MODEL_REJECTED", "MALFORMED_RESEARCH",
        "VALIDATION_ERROR", "INVALID_RESPONSE",
    }:
        disposition = NON_RETRYABLE_VALIDATION
    elif normalized == "CIRCUIT_OPEN":
        disposition = CIRCUIT_OPEN
    elif normalized in {"DEADLINE_EXCEEDED", "TIME_BUDGET_EXCEEDED"}:
        disposition = DEADLINE_EXCEEDED
    elif http_status in {408, 425, 429, 500, 502, 503, 504} or normalized in {
        "HTTP_408", "HTTP_425", "HTTP_429", "HTTP_500", "HTTP_502",
        "HTTP_503", "HTTP_504", "NETWORK_ERROR", "PROVIDER_UNAVAILABLE",
        "RESERVATION_FAILED", "GOVERNANCE_UNAVAILABLE",
    }:
        disposition = RETRYABLE_TRANSIENT
    else:
        disposition = NON_RETRYABLE_VALIDATION

    retryable = disposition == RETRYABLE_TRANSIENT
    return {
        "schema": RETRY_SCHEMA,
        "disposition": disposition,
        "retryable": retryable,
        "max_attempts": 3 if retryable else 0,
        "initial_interval_seconds": 2 if retryable else None,
        "backoff_coefficient": 2.0 if retryable else None,
        "maximum_interval_seconds": 30 if retryable else None,
        "jitter": "full" if retryable else None,
        "honor_retry_after": retryable,
        "requires_explicit_resolution": disposition == AMBIGUOUS_PROVIDER_RESULT,
    }


class ProviderRequestJournal:
    """Append-only, flock-guarded provider side-effect journal."""

    _BLOCKING_STATES = frozenset({
        "DISPATCHED", "AMBIGUOUS", "COMPLETED", "NON_RETRYABLE",
    })

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_journal_path()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def _read_rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def _append_locked(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def latest(self, semantic_key: str) -> dict[str, Any] | None:
        rows = self._read_rows()
        for row in reversed(rows):
            if row.get("semantic_key") == semantic_key:
                return row
        return None

    def reserve(
        self,
        *,
        semantic_key: str,
        request_id: str,
        process_id: str,
        provider: str,
        model_id: str,
        task: str,
        projected_cost_usd: float | None,
    ) -> dict[str, Any]:
        """Atomically reserve a provider request or return a blocking state."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                current = self.latest(semantic_key)
                if current and current.get("state") in self._BLOCKING_STATES:
                    return {"allowed": False, "current": current}
                attempt = int((current or {}).get("attempt") or 0) + 1
                if attempt > 3:
                    return {"allowed": False, "current": current, "reason": "ATTEMPTS_EXHAUSTED"}
                row = {
                    "schema": JOURNAL_SCHEMA,
                    "event": "REQUEST_RESERVED",
                    "state": "RESERVED",
                    "recorded_at": _now(),
                    "semantic_key": semantic_key,
                    "request_id": request_id,
                    "process_id": process_id,
                    "provider": provider,
                    "model_id": model_id,
                    "task": task,
                    "projected_cost_usd": projected_cost_usd,
                    "attempt": attempt,
                    "authority": "READ_ONLY_ADVISORY",
                }
                self._append_locked(row)
                return {"allowed": True, "current": row}
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def record(self, semantic_key: str, *, state: str, **fields: Any) -> dict[str, Any]:
        current = self.latest(semantic_key) or {}
        row = {
            "schema": JOURNAL_SCHEMA,
            "event": f"REQUEST_{state}",
            "state": state,
            "recorded_at": _now(),
            "semantic_key": semantic_key,
            "request_id": current.get("request_id"),
            "process_id": current.get("process_id"),
            "provider": current.get("provider"),
            "model_id": current.get("model_id"),
            "task": current.get("task"),
            "attempt": current.get("attempt"),
            "authority": "READ_ONLY_ADVISORY",
            **{k: v for k, v in fields.items() if v is not None},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                self._append_locked(row)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return row

