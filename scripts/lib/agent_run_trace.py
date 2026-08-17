"""agent_run_trace.py — AgentRunTrace@v1 + append-only trace storage (Phase 1).

READ_ONLY_ADVISORY. Structured, redacted, append-only trace of one agent run.

Guarantees:
  * every wake/trace is traceable (wake_id + trace_id + parent_trace_id)
  * chain-of-thought is never persisted
  * secrets are redacted before persist
  * append-safe, crash-safe JSONL (same durable pattern as cio_wake_traces)
  * queryable by wake_id / decision_id / case_id

Storage: data/cio/agent_run_traces.jsonl
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.agent_context_envelope import redact_secrets, sha256_hex

TRACE_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRACE_PATH = PROJECT_ROOT / "data" / "cio" / "agent_run_traces.jsonl"

# ── Status enums ───────────────────────────────────────────────────────────
STATUS_STARTED = "started"
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"
STATUS_SUPERSEDED = "superseded"

# Fields that must NEVER be persisted (chain-of-thought + raw secrets).
_FORBIDDEN_FIELDS = frozenset({
    "chain_of_thought",
    "cot",
    "reasoning",
    "internal_monologue",
    "scratchpad",
})

# Fields stripped/redacted before persist.
_SECRET_FIELDS = frozenset({
    "api_key", "token", "secret", "password", "credential",
    "authorization", "bearer", "cookie", "private_key",
})

_REQUIRED_TOP = (
    "trace_version",
    "trace_id",
    "wake_id",
    "agent",
    "role",
    "started_at",
    "status",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_trace_id(wake_id: str = "") -> str:
    if wake_id:
        return f"tr_{wake_id}"[:96]
    return f"tr_{uuid.uuid4().hex[:16]}"


def _strip_forbidden(value: Any) -> Any:
    """Recursively remove forbidden (chain-of-thought) fields. Never mutates."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key_l = str(k).lower().replace("-", "_").replace(" ", "_")
            if key_l in _FORBIDDEN_FIELDS:
                continue
            out[str(k)] = _strip_forbidden(v)
        return out
    if isinstance(value, list):
        return [_strip_forbidden(item) for item in value]
    return value


def sanitize_trace(trace: dict[str, Any]) -> dict[str, Any]:
    """Remove chain-of-thought + redact secrets. Returns a clean copy."""
    cleaned = _strip_forbidden(trace)
    return redact_secrets(cleaned)


def build_trace(
    *,
    trace_id: str,
    wake_id: str,
    agent: str,
    role: str,
    parent_trace_id: Optional[str] = None,
    trigger: Optional[str] = None,
    trigger_digest: Optional[str] = None,
    context_digest: Optional[str] = None,
    status: str = STATUS_STARTED,
    **extra: Any,
) -> dict[str, Any]:
    """Build a minimal AgentRunTrace@v1 record."""
    trace: dict[str, Any] = {
        "trace_version": TRACE_VERSION,
        "trace_id": trace_id,
        "wake_id": wake_id,
        "parent_trace_id": parent_trace_id,
        "trigger": trigger,
        "trigger_digest": trigger_digest,
        "agent": agent,
        "role": role,
        "started_at": _now_iso(),
        "status": status,
    }
    if context_digest:
        trace["context"] = {"context_digest": context_digest}
    for k, v in extra.items():
        if v is not None:
            trace[k] = v
    return trace


def validate_trace(trace: Any) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(trace, dict):
        return False, ["trace is not a dict"]
    for key in _REQUIRED_TOP:
        if key not in trace:
            errors.append(f"missing field: {key}")
    if trace.get("trace_version") != TRACE_VERSION:
        errors.append(f"bad trace_version: {trace.get('trace_version')!r}")
    # Ensure forbidden fields never appear (post-sanitize invariant).
    flat = json.dumps(trace, default=str)
    if re.search(r"chain[_-]?of[_-]?thought|internal[_-]?monologue", flat, re.IGNORECASE):
        errors.append("chain-of-thought present in trace")
    return (len(errors) == 0, errors)


def append_trace(trace: dict[str, Any], path: Path | str | None = None) -> bool:
    """Append one sanitized trace row as JSONL. Fail-soft; never raises."""
    try:
        p = Path(path) if path else DEFAULT_TRACE_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        clean = sanitize_trace(trace)
        clean = {k: v for k, v in clean.items() if v is not None}
        line = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str) + "\n"
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
        return True
    except Exception:
        return False


def close_trace(
    trace: dict[str, Any],
    *,
    ended_at: Optional[str] = None,
    status: str = STATUS_COMPLETED,
    decision: Optional[dict[str, Any]] = None,
    notification: Optional[dict[str, Any]] = None,
    operator: Optional[dict[str, Any]] = None,
    performance: Optional[dict[str, Any]] = None,
    security: Optional[dict[str, Any]] = None,
    **extra: Any,
) -> dict[str, Any]:
    """Return a completed trace (not persisted — caller decides whether to append)."""
    out = dict(trace)
    out["status"] = status
    out["ended_at"] = ended_at or _now_iso()
    if decision is not None:
        out["decision"] = decision
    if notification is not None:
        out["notification"] = notification
    if operator is not None:
        out["operator"] = operator
    if performance is not None:
        out["performance"] = performance
    if security is not None:
        out["security"] = security
    for k, v in extra.items():
        if v is not None:
            out[k] = v
    return out


def _read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return rows
    return rows


def query_traces(
    *,
    wake_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    case_id: Optional[str] = None,
    agent: Optional[str] = None,
    limit: int = 50,
    path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Query stored traces. Newest first. Deterministic, fail-soft."""
    try:
        p = Path(path) if path else DEFAULT_TRACE_PATH
        rows = _read_rows(p)
        out: list[dict[str, Any]] = []
        for r in rows:
            if wake_id and str(r.get("wake_id") or "") != str(wake_id):
                continue
            if trace_id and str(r.get("trace_id") or "") != str(trace_id):
                continue
            dec = r.get("decision") or {}
            if decision_id and isinstance(dec, dict) and str(dec.get("decision_id") or "") != str(decision_id):
                continue
            if case_id:
                learning = r.get("learning") or {}
                if isinstance(learning, dict) and str(learning.get("case_id") or "") != str(case_id):
                    continue
                # Also allow top-level case_id for convenience.
                if str(r.get("case_id") or "") != str(case_id) and not isinstance(learning, dict):
                    continue
            if agent and str(r.get("agent") or "") != str(agent):
                continue
            out.append(r)
        out.reverse()
        lim = max(1, min(int(limit or 50), 500))
        return out[:lim]
    except Exception:
        return []


def trace_digest(trace: dict[str, Any]) -> str:
    """Stable content digest of a trace (excludes timestamps)."""
    body = {
        "trace_id": trace.get("trace_id"),
        "wake_id": trace.get("wake_id"),
        "parent_trace_id": trace.get("parent_trace_id"),
        "agent": trace.get("agent"),
        "role": trace.get("role"),
        "trigger": trace.get("trigger"),
        "trigger_digest": trace.get("trigger_digest"),
        "status": trace.get("status"),
        "decision": trace.get("decision"),
        "notification": trace.get("notification"),
        "operator": trace.get("operator"),
        "learning": trace.get("learning"),
        "security": trace.get("security"),
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return "trh_" + sha256_hex(raw, 16)
