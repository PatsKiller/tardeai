"""agent_tool_trace.py — governed tool-call trace (Phase 2.2).

READ_ONLY_ADVISORY. Records every approved agent tool call with capability
class, read/write classification, request/response digests, timing, provider,
and source-as-of. Secrets are redacted before persist.

Never logs OAuth tokens, API tokens, session cookies, broker credentials,
private signing keys, or full sensitive documents.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.agent_context_envelope import redact_secrets, sha256_hex

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOOL_TRACE_PATH = PROJECT_ROOT / "data" / "cio" / "agent_tool_traces.jsonl"

# ── Capability classes ─────────────────────────────────────────────────────
CAP_READ = "read"
CAP_WRITE = "write"
CAP_UNKNOWN = "unknown"

# Tool name → (capability_class, read/write). Denylist is enforced elsewhere
# (Phase 3 MCP gateway); here we only classify + trace.
_WRITE_TOKENS = (
    "write", "create", "update", "delete", "send", "execute", "submit",
    "place", "cancel", "mutate", "stop", "order",
)
_READ_TOKENS = ("get", "read", "search", "list", "query", "snapshot", "fetch")


def classify_tool(tool_name: str) -> tuple[str, str]:
    """Return (capability_class, read/write) for a tool name."""
    name = str(tool_name or "").lower()
    for tok in _WRITE_TOKENS:
        if tok in name:
            return CAP_WRITE, "write"
    for tok in _READ_TOKENS:
        if tok in name:
            return CAP_READ, "read"
    return CAP_UNKNOWN, "read"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ms() -> int:
    return int(time.time() * 1000)


def request_digest(payload: Any) -> str:
    """Content digest of a tool request (secrets redacted first)."""
    clean = redact_secrets(payload)
    raw = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str)
    return "req_" + sha256_hex(raw, 16)


def response_digest(payload: Any) -> str:
    """Content digest of a tool response (secrets redacted first)."""
    clean = redact_secrets(payload)
    raw = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str)
    return "rsp_" + sha256_hex(raw, 16)


def build_tool_call(
    *,
    tool_name: str,
    trace_id: str,
    wake_id: str,
    agent: str,
    request: Any = None,
    response: Any = None,
    provider: Optional[str] = None,
    source_asof: Optional[str] = None,
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
    success: bool = True,
) -> dict[str, Any]:
    """Build a tool-call trace record. Request/response are digested, not stored raw."""
    cap, rw = classify_tool(tool_name)
    return {
        "tool_name": tool_name,
        "capability_class": cap,
        "read_write": rw,
        "trace_id": trace_id,
        "wake_id": wake_id,
        "agent": agent,
        "request_digest": request_digest(request),
        "response_digest": response_digest(response),
        "started_at": started_at or _now_iso(),
        "ended_at": ended_at or _now_iso(),
        "success": bool(success),
        "provider": provider,
        "source_asof": source_asof,
    }


def append_tool_call(record: dict[str, Any], path: Path | str | None = None) -> bool:
    """Append one sanitized tool-call trace row. Fail-soft; never raises."""
    try:
        p = Path(path) if path else DEFAULT_TOOL_TRACE_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        clean = redact_secrets(record)
        clean = {k: v for k, v in clean.items() if v is not None}
        line = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str) + "\n"
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
        return True
    except Exception:
        return False


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


def query_tool_calls(
    *,
    trace_id: Optional[str] = None,
    wake_id: Optional[str] = None,
    capability_class: Optional[str] = None,
    limit: int = 100,
    path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Query tool-call traces. Newest first. Fail-soft."""
    try:
        p = Path(path) if path else DEFAULT_TOOL_TRACE_PATH
        rows = _read_rows(p)
        out: list[dict[str, Any]] = []
        for r in rows:
            if trace_id and str(r.get("trace_id") or "") != str(trace_id):
                continue
            if wake_id and str(r.get("wake_id") or "") != str(wake_id):
                continue
            if capability_class and str(r.get("capability_class") or "") != str(capability_class):
                continue
            out.append(r)
        out.reverse()
        lim = max(1, min(int(limit or 100), 1000))
        return out[:lim]
    except Exception:
        return []


def count_write_attempts(path: Path | str | None = None) -> int:
    """Count recorded write-classified tool calls (for audit)."""
    return len(query_tool_calls(capability_class=CAP_WRITE, limit=1000, path=path))
