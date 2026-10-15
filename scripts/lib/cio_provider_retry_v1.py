"""Durable provider request journal and canonical retry dispositions.

The journal records metadata and hashes only. It never persists prompts,
responses, credentials, or other provider payloads.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any, Iterator

RETRY_SCHEMA = "RetryDisposition@v1"
JOURNAL_SCHEMA = "ProviderRequestJournal@v1"

RETRYABLE_TRANSIENT = "RETRYABLE_TRANSIENT"
NON_RETRYABLE_COST = "NON_RETRYABLE_COST"
NON_RETRYABLE_POLICY = "NON_RETRYABLE_POLICY"
NON_RETRYABLE_VALIDATION = "NON_RETRYABLE_VALIDATION"
AMBIGUOUS_PROVIDER_RESULT = "AMBIGUOUS_PROVIDER_RESULT"
CIRCUIT_OPEN = "CIRCUIT_OPEN"
DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"

HARD_DISPOSITIONS = frozenset(
    {
        NON_RETRYABLE_COST,
        NON_RETRYABLE_POLICY,
        NON_RETRYABLE_VALIDATION,
        AMBIGUOUS_PROVIDER_RESULT,
        CIRCUIT_OPEN,
        DEADLINE_EXCEEDED,
    }
)

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
        "MODEL_MISMATCH",
        "LEGACY_MODEL_REJECTED",
        "MALFORMED_RESEARCH",
        "VALIDATION_ERROR",
        "INVALID_RESPONSE",
    }:
        disposition = NON_RETRYABLE_VALIDATION
    elif normalized == "CIRCUIT_OPEN":
        disposition = CIRCUIT_OPEN
    elif normalized in {"DEADLINE_EXCEEDED", "TIME_BUDGET_EXCEEDED"}:
        disposition = DEADLINE_EXCEEDED
    elif http_status in {408, 425, 429, 500, 502, 503, 504} or normalized in {
        "HTTP_408",
        "HTTP_425",
        "HTTP_429",
        "HTTP_500",
        "HTTP_502",
        "HTTP_503",
        "HTTP_504",
        "NETWORK_ERROR",
        "PROVIDER_UNAVAILABLE",
        "RESERVATION_FAILED",
        "GOVERNANCE_UNAVAILABLE",
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


#: latest() reads the journal backwards in chunks of this size; peak memory is about
#: chunk + one carried line, independent of the journal's size.
_SCAN_CHUNK_BYTES = 1 << 20
#: A journal row is metadata only (< 4 KB). A "line" longer than this is corrupt and is skipped
#: rather than buffered, so a file with no newlines cannot grow the carry without bound.
_MAX_LINE_BYTES = 1 << 20


def _parse_row(raw: bytes, semantic_key: str) -> dict[str, Any] | None:
    try:
        row = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(row, dict) and row.get("semantic_key") == semantic_key:
        return row
    return None


def _scan_latest(
    handle: IO[bytes],
    end: int,
    semantic_key: str,
    *,
    chunk_bytes: int = _SCAN_CHUNK_BYTES,
    max_line_bytes: int = _MAX_LINE_BYTES,
) -> dict[str, Any] | None:
    """Return the last row in ``handle[0:end]`` whose semantic_key matches, scanning from EOF.

    Each step reads ``[start, pos)`` and appends ``carry`` (the head-truncated tail of the line
    that straddles ``pos``). Everything after the first newline of that buffer is whole lines;
    the bytes before it continue a line that starts earlier and become the next carry. Within
    the whole-line region, ``rfind`` locates candidate lines newest-first; only those are parsed.
    """
    needle = semantic_key.encode("utf-8")
    if not needle:
        return None
    pos = end
    carry = b""
    skipping = False  # inside an over-long (corrupt) line: discard bytes until its start
    while pos > 0:
        start = max(0, pos - chunk_bytes)
        handle.seek(start)
        buf = handle.read(pos - start)
        pos = start
        if skipping:
            nl = buf.rfind(b"\n")
            if nl < 0:
                continue
            buf = buf[:nl]
            skipping = False
        data = buf + carry
        if start > 0:
            first_nl = data.find(b"\n")
            if first_nl < 0:
                carry = data
                if len(carry) > max_line_bytes:
                    carry, skipping = b"", True
                continue
            carry = data[:first_nl]
            if len(carry) > max_line_bytes:
                carry, skipping = b"", True
            lo = first_nl + 1
        else:
            carry = b""
            lo = 0
        hi = len(data)
        while hi > lo:
            hit = data.rfind(needle, lo, hi)
            if hit < 0:
                break
            line_start = max(data.rfind(b"\n", lo, hit) + 1, lo)
            line_end = data.find(b"\n", hit, hi)
            if line_end < 0:
                line_end = hi
            row = _parse_row(data[line_start:line_end], semantic_key)
            if row is not None:
                return row
            hi = line_start
    return None


class ProviderRequestJournal:
    """Append-only, flock-guarded provider side-effect journal."""

    _BLOCKING_STATES = frozenset(
        {
            "DISPATCHED",
            "AMBIGUOUS",
            "COMPLETED",
            "NON_RETRYABLE",
        }
    )

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_journal_path()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        """Hold the journal's exclusive flock (the same lock reserve(), record() and rotation take)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _append_locked(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def latest(self, semantic_key: str) -> dict[str, Any] | None:
        """Newest well-formed row for ``semantic_key``, or None.

        2026-10-15 (bridge OOM): this used to read and json-parse the WHOLE journal (71 MB, 147k
        rows, ~400 MB peak per call, >= 3 calls per governed request) and the kernel OOM-killed
        the bridge at MemoryMax=768M. It now scans backwards from EOF in fixed-size chunks and
        json-parses only lines that contain the key's bytes. Memory is bounded by
        ``_SCAN_CHUNK_BYTES + _MAX_LINE_BYTES`` whatever the journal size.

        Correctness: the scan has no window cut-off -- when the key is absent it reads to byte 0 --
        so the first verified match walking backwards is by construction the last matching row in
        file order, exactly what the old forward parse returned. The end offset is fixed at open
        (fstat), so a concurrent append past it is simply newer than this snapshot; an append caught
        mid-write is a torn tail that fails json and is skipped, as before. Unparseable or
        non-object lines are skipped, as before.
        """
        try:
            handle = self.path.open("rb")
        except FileNotFoundError:
            return None
        with handle:
            end = os.fstat(handle.fileno()).st_size
            return _scan_latest(handle, end, semantic_key)

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
        with self.locked():
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

    def record(self, semantic_key: str, *, state: str, **fields: Any) -> dict[str, Any]:
        """Append a state row for ``semantic_key``.

        Takes the same exclusive flock as reserve() around BOTH the read of the current row and
        the append (2026-10-15): the read-modify-write is atomic against reserve(), other
        record() calls and rotation, and two request threads can no longer scan concurrently.
        """
        with self.locked():
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
            self._append_locked(row)
        return row
