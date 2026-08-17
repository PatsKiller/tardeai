"""mcp_read_only_gateway.py — Read-only MCP gateway (Phase 3).

READ_ONLY_ADVISORY. Single chokepoint for every agent MCP tool call.

This is an INTERNAL gateway, not the upstream ``mcp`` SDK. It enforces a
read-only allowlist locally and routes only to registered, in-memory provider
adapters. External backends (Google Calendar / Documents) are represented as
NOT_CONFIGURED until credentials exist; no network call ever leaves this
module.

Guarantees:
  * exact-tool allowlist + substring denylist, enforced locally (fail closed)
  * server-side read-only: no write tool can pass, regardless of any metadata
  * SSRF guard: private/metadata hosts are always blocked; only an explicit
    safe-host allowlist is permitted
  * path-traversal guard: "..", absolute paths, and root escapes are blocked
  * response size bound + secret redaction before anything is returned
  * full receipt binding (trace/wake/agent/tool/provider/digests/timing/status)
  * fail-soft: missing/error provider => ok=False, never raises
"""
from __future__ import annotations

import ipaddress
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from scripts.lib.agent_context_envelope import redact_secrets
from scripts.lib.agent_tool_trace import append_tool_call, build_tool_call

# ── Authority / status (MCP_READ_ONLY constants) ───────────────────────────
MCP_READ_ONLY_AUTHORITY = "READ_ONLY_ADVISORY"

MCP_READ_ONLY_STATUS_OK = "OK"
MCP_READ_ONLY_STATUS_DENIED = "DENIED"
MCP_READ_ONLY_STATUS_ERROR = "ERROR"
MCP_READ_ONLY_STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
MCP_READ_ONLY_STATUS_BOUNDED = "BOUNDED"
MCP_READ_ONLY_STATUS_TIMEOUT = "TIMEOUT"
MCP_READ_ONLY_STATUS_LIMITED = "LIMITED"

MCP_READ_ONLY = {
    "authority": MCP_READ_ONLY_AUTHORITY,
    "status_ok": MCP_READ_ONLY_STATUS_OK,
    "status_denied": MCP_READ_ONLY_STATUS_DENIED,
    "status_error": MCP_READ_ONLY_STATUS_ERROR,
    "status_not_configured": MCP_READ_ONLY_STATUS_NOT_CONFIGURED,
    "status_bounded": MCP_READ_ONLY_STATUS_BOUNDED,
    "status_timeout": MCP_READ_ONLY_STATUS_TIMEOUT,
    "status_limited": MCP_READ_ONLY_STATUS_LIMITED,
}

# ── Timeout / rate governance (bounded, deterministic, in-process) ─────────
# The current adapters are synchronous + read-only, so a timed-out call cannot
# mutate anything (no orphan background mutation). A cooperative per-call
# deadline is enforced via a short-lived worker thread; on timeout the result
# is discarded and a TIMEOUT status is returned.
DEFAULT_TIMEOUT_MS = 2000
DEFAULT_MAX_CALLS_PER_WAKE = 50
DEFAULT_MAX_CALLS_PER_TOOL = 10

_TIMEOUT = object()
_NO_RESULT = object()


def _call_with_timeout(
    fn: Callable[..., Any],
    timeout_ms: int,
    **kwargs: Any,
) -> Any:
    """Call ``fn(**kwargs)`` with a per-call deadline. Returns ``_TIMEOUT``
    on deadline exceeded. ``timeout_ms <= 0`` means no deadline (direct call).

    A TRUE deadline: the caller regains control at the deadline rather than
    waiting for the underlying (read-only) function to finish. The worker runs
    on a daemon thread; on timeout its result is discarded and it is reclaimed
    when it eventually returns (never blocking the caller or process exit).
    """
    if timeout_ms is None or timeout_ms <= 0:
        return fn(**kwargs)

    box: dict[str, Any] = {"value": _NO_RESULT, "error": None}

    def _run() -> None:
        try:
            box["value"] = fn(**kwargs)
        except Exception as exc:  # noqa: BLE001 — surfaced to caller
            box["error"] = exc

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout=timeout_ms / 1000.0)
    if worker.is_alive():
        # Deadline reached: do NOT wait for the worker; discard its result.
        return _TIMEOUT
    if box["error"] is not None:
        raise box["error"]
    return box["value"]


class MCPRateGovernor:
    """Simple bounded per-wake / per-tool request budget + optional rate limit.

    Deterministic and in-process. One wake issuing an unbounded call fanout is
    blocked once it exceeds ``max_calls_per_wake`` or ``max_calls_per_tool``.
    """

    def __init__(
        self,
        *,
        max_calls_per_wake: int = DEFAULT_MAX_CALLS_PER_WAKE,
        max_calls_per_tool: int = DEFAULT_MAX_CALLS_PER_TOOL,
        min_interval_ms: float = 0.0,
    ) -> None:
        self.max_calls_per_wake = int(max_calls_per_wake)
        self.max_calls_per_tool = int(max_calls_per_tool)
        self.min_interval_ms = float(min_interval_ms or 0.0)
        self._wake_counts: dict[str, int] = {}
        self._tool_counts: dict[tuple[str, str], int] = {}
        self._last_call_ms: dict[str, int] = {}

    def allow(self, wake_id: Any, tool: Any) -> tuple[bool, str]:
        """Return (allowed, reason). Records the call only when allowed."""
        now = _now_ms()
        wid = str(wake_id or "")
        t = str(tool or "").lower()

        if self.min_interval_ms > 0 and wid in self._last_call_ms:
            delta = now - self._last_call_ms[wid]
            if delta < self.min_interval_ms:
                return False, f"rate limit: min interval {self.min_interval_ms}ms"

        wake_count = self._wake_counts.get(wid, 0)
        if wake_count >= self.max_calls_per_wake:
            return False, f"wake budget exceeded: {self.max_calls_per_wake}"

        tool_count = self._tool_counts.get((wid, t), 0)
        if tool_count >= self.max_calls_per_tool:
            return False, f"tool budget exceeded: {self.max_calls_per_tool}"

        self._wake_counts[wid] = wake_count + 1
        self._tool_counts[(wid, t)] = tool_count + 1
        self._last_call_ms[wid] = now
        return True, ""

    def reset(self) -> None:
        self._wake_counts.clear()
        self._tool_counts.clear()
        self._last_call_ms.clear()


# Shared governed default so the chokepoint ALWAYS applies budget governance.
# ``call_mcp_tool(governor=None)`` uses this shared governor rather than
# bypassing the budget: a caller cannot disable governance by omitting it.
_DEFAULT_GOVERNOR = MCPRateGovernor()


def get_default_governor() -> MCPRateGovernor:
    """Return the shared default rate/budget governor for the chokepoint."""
    return _DEFAULT_GOVERNOR


def reset_default_governor() -> None:
    """Reset the shared default governor (used by tests to be deterministic)."""
    _DEFAULT_GOVERNOR.reset()

# ── Read-only allowlist (exact tool name -> capability class) ──────────────
# Every entry is read-only. Capability classes are domain scopes, never verbs.
ALLOWED_TOOLS: dict[str, str] = {
    "portfolio.get_verified_snapshot": "portfolio",
    "portfolio.get_cash_snapshot": "portfolio",
    "portfolio.get_risk_snapshot": "portfolio",
    "decisions.get": "decisions",
    "decisions.search_history": "decisions",
    "research.search": "research",
    "research.get_source": "research",
    "documents.search": "documents",
    "documents.get": "documents",
    "calendar.search": "calendar",
    "calendar.get_event": "calendar",
    "goals.list": "goals",
    "plans.get": "plans",
}

# ── Denylist (substrings that ALWAYS deny, even if allowlisted) ────────────
# Broker/order/stop/trade/email writes, calendar+document writes, shell/exec,
# filesystem write, generic http fetch, risk-policy write, credentials/auth.
DENIED_SUBSTRINGS: tuple[str, ...] = (
    "broker",
    "order",
    "stop",
    "trade",
    "email",
    "create",
    "update",
    "delete",
    "edit",
    "shell",
    "exec",
    "write",
    "fetch",
    "http",
    "risk_policy",
    "credential",
    "auth",
    "2fa",
    "token",
    "place",
    "cancel",
    "submit",
    "mutate",
    "send",
)

DEFAULT_MAX_RESPONSE_BYTES = 65536

# Request schema: known request fields per known tool. Unknown fields deny.
_TOOL_REQUEST_FIELDS: dict[str, set[str]] = {
    "portfolio.get_verified_snapshot": {"account_id", "symbols", "asof"},
    "portfolio.get_cash_snapshot": {"account_id", "asof"},
    "portfolio.get_risk_snapshot": {"account_id", "asof"},
    "decisions.get": {"decision_id"},
    "decisions.search_history": {"query", "decision_id", "limit", "symbols"},
    "research.search": {"query", "symbols", "limit"},
    "research.get_source": {"source_id", "source_ref", "source_url"},
    "documents.search": {"query", "limit", "path"},
    "documents.get": {"document_id", "path", "source_url"},
    "calendar.search": {"query", "start", "end", "limit"},
    "calendar.get_event": {"event_id"},
    "goals.list": {"limit"},
    "plans.get": {"plan_id"},
}

_URL_RE = re.compile(r"https?://([^\s/\"'<>?#]+)")
_HOST_KEYS = frozenset(
    {
        "url",
        "uri",
        "host",
        "hostname",
        "endpoint",
        "base_url",
        "source_url",
        "source_uri",
        "webhook",
        "remote_url",
    }
)
_PATH_KEYS = frozenset(
    {"path", "file_path", "doc_path", "document_path", "source_path", "path_prefix"}
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ms() -> int:
    return int(time.time() * 1000)


# ── Allowlist / denylist classification ────────────────────────────────────


def classify_tool_allowed(tool_name: str) -> tuple[bool, str]:
    """Return (allowed, capability_class_or_reason).

    Deny-substring check runs first (deny always wins), then the exact-tool
    allowlist, then unknown-tool denial.
    """
    name = str(tool_name or "").lower()
    for sub in DENIED_SUBSTRINGS:
        if sub in name:
            return False, f"denied substring {sub!r}"
    if name in ALLOWED_TOOLS:
        return True, ALLOWED_TOOLS[name]
    return False, "unknown tool"


# ── SSRF guard ─────────────────────────────────────────────────────────────


def _normalize_host(raw: str) -> str:
    """Reduce a host/URL value to a bare lowercase host (no scheme/port/path)."""
    h = str(raw or "").strip().lower()
    if "://" in h:
        h = h.split("://", 1)[1]
    h = h.split("/", 1)[0]
    h = h.split("?", 1)[0]
    h = h.split("#", 1)[0]
    if "@" in h:
        h = h.rsplit("@", 1)[1]
    if h.startswith("[") and "]" in h:
        h = h[1 : h.index("]")]
    elif h.count(":") == 1:
        left, right = h.rsplit(":", 1)
        if right.isdigit():
            h = left
    return h


def _is_private_or_metadata(host: str) -> bool:
    """True for localhost, link-local, RFC1918, unspecified, and metadata hosts."""
    h = host or ""
    if h in ("localhost", "localhost.localdomain", "metadata", "metadata.google.internal"):
        return True
    if h.endswith(".localhost") or h.endswith(".local") or h.endswith(".internal") or h.endswith(".metadata"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_reserved
    )


def _is_safe_host(host: str, safe_hosts: Optional[Iterable[str]] = None) -> bool:
    """SSRF guard. Blocks localhost/127.x/0.0.0.0/169.254.x/10.x/172.16-31.x/
    192.168.x/::1 and any private/metadata host. Otherwise requires an explicit
    safe-host allowlist (fail closed when none is supplied)."""
    h = _normalize_host(host)
    if not h:
        return False
    if _is_private_or_metadata(h):
        return False
    allowed = {_normalize_host(x) for x in (safe_hosts or ()) if x}
    if not allowed:
        return False
    return h in allowed


def _iter_strings(value: Any):
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                yield from _iter_strings(v)
            elif isinstance(v, str):
                yield str(k), v
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)
    elif isinstance(value, str):
        yield None, value


def _extract_hosts(value: Any) -> set[str]:
    hosts: set[str] = set()
    for key, s in _iter_strings(value):
        if key is not None and str(key).lower() in _HOST_KEYS:
            hosts.add(_normalize_host(s))
        for m in _URL_RE.finditer(s):
            hosts.add(_normalize_host(m.group(1)))
    return {h for h in hosts if h}


def _extract_doc_paths(value: Any) -> set[str]:
    paths: set[str] = set()
    for key, s in _iter_strings(value):
        if key is not None and str(key).lower() in _PATH_KEYS:
            paths.add(s)
    return paths


# ── Path-traversal guard ───────────────────────────────────────────────────


def _is_safe_doc_path(path: str, allowed_root: Optional[str] = None) -> bool:
    """Path-traversal guard. Rejects "..", absolute paths, and any path that
    escapes the allowed root."""
    p = str(path or "")
    if p == "":
        return False
    if p.startswith("/") or p.startswith("\\") or re.match(r"^[A-Za-z]:", p):
        return False
    parts = [seg for seg in re.split(r"[\\/]+", p) if seg != ""]
    if not parts:
        return False
    if any(seg == ".." for seg in parts):
        return False
    root = Path(allowed_root) if allowed_root else Path(".")
    try:
        resolved = (root / Path(p)).resolve()
        resolved.relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


# ── Schema validation ──────────────────────────────────────────────────────


def _validate_request(tool: str, request: Any) -> tuple[bool, str]:
    if request is None:
        return True, ""
    if not isinstance(request, dict):
        return False, "invalid schema: request must be a dict"
    fields = _TOOL_REQUEST_FIELDS.get(tool)
    if fields is None:
        return True, ""
    unknown = [k for k in request.keys() if k not in fields]
    if unknown:
        return False, f"invalid schema: unknown field(s) {sorted(unknown)}"
    return True, ""


def _is_search_tool(tool: str) -> bool:
    t = str(tool or "").lower()
    return t.endswith(".search") or t.endswith(".search_history") or t.endswith(".list")


# ── The single chokepoint ──────────────────────────────────────────────────


def call_mcp_tool(
    *,
    wake_id: Any,
    trace_id: Any,
    agent: Any,
    tool: Any,
    provider: Any = None,
    request: Any = None,
    provider_registry: Optional[dict[str, Any]] = None,
    safe_hosts: Optional[Iterable[str]] = None,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    trace_path: Any = None,
    doc_root: Optional[str] = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    governor: Optional["MCPRateGovernor"] = None,
) -> dict[str, Any]:
    """Single chokepoint for every agent MCP tool call.

    Denies early (never raises) for missing ids, non-allowlisted tools, bad
    schema, SSRF-unsafe hosts, and path traversal. Resolves the provider from
    ``provider_registry`` and fails soft on missing/error/NOT_CONFIGURED.
    Redacts secrets and enforces the response size bound before returning.
    """
    started_iso = _now_iso()
    started_ms = _now_ms()

    wake_id = "" if wake_id is None else str(wake_id)
    trace_id = "" if trace_id is None else str(trace_id)
    agent = "" if agent is None else str(agent)
    tool = "" if tool is None else str(tool)
    provider = None if provider is None else str(provider)

    def _finish(
        *,
        ok: bool,
        status: str,
        response: Any = None,
        reason: Optional[str] = None,
        bounded: bool = False,
        source_asof: Optional[str] = None,
        provider_name: Optional[str] = None,
        latency_ms: Optional[int] = None,
    ) -> dict[str, Any]:
        ended_iso = _now_iso()
        lat = latency_ms if latency_ms is not None else (_now_ms() - started_ms)
        redacted_response = redact_secrets(response) if response is not None else None
        source_asof = source_asof or _now_iso()
        pname = provider_name or provider or (tool.split(".")[0] if tool else "")
        receipt = build_tool_call(
            tool_name=tool,
            trace_id=trace_id,
            wake_id=wake_id,
            agent=agent,
            request=request,
            response=redacted_response,
            provider=pname,
            source_asof=source_asof,
            started_at=started_iso,
            ended_at=ended_iso,
            success=ok,
        )
        receipt["status"] = status
        receipt["authority"] = MCP_READ_ONLY_AUTHORITY
        receipt["latency_ms"] = lat
        receipt["bounded"] = bool(bounded)
        if reason is not None:
            receipt["reason"] = reason
        append_tool_call(receipt, path=trace_path)
        return {
            "ok": ok,
            "status": status,
            "authority": MCP_READ_ONLY_AUTHORITY,
            "tool": tool,
            "provider": pname,
            "reason": reason,
            "response": redacted_response,
            "bounded": bool(bounded),
            "trace_id": trace_id,
            "wake_id": wake_id,
            "agent": agent,
            "request_digest": receipt.get("request_digest"),
            "response_digest": receipt.get("response_digest"),
            "latency_ms": lat,
            "source_asof": source_asof,
            "timestamp": ended_iso,
        }

    # 1. wake_id / trace_id presence
    if not wake_id.strip():
        return _finish(ok=False, status=MCP_READ_ONLY_STATUS_DENIED, reason="missing wake_id")
    if not trace_id.strip():
        return _finish(ok=False, status=MCP_READ_ONLY_STATUS_DENIED, reason="missing trace_id")

    # 2. allowlist + deny substring
    allowed, detail = classify_tool_allowed(tool)
    if not allowed:
        return _finish(ok=False, status=MCP_READ_ONLY_STATUS_DENIED, reason=detail)

    # 3. request schema
    schema_ok, schema_err = _validate_request(tool, request)
    if not schema_ok:
        return _finish(ok=False, status=MCP_READ_ONLY_STATUS_DENIED, reason=schema_err)

    request = request if isinstance(request, dict) else {}

    # 4. SSRF check
    for host in sorted(_extract_hosts(request)):
        if not _is_safe_host(host, safe_hosts):
            return _finish(
                ok=False,
                status=MCP_READ_ONLY_STATUS_DENIED,
                reason=f"unsafe host: {host}",
            )

    # 5. path-traversal check
    for p in sorted(_extract_doc_paths(request)):
        if not _is_safe_doc_path(p, doc_root):
            return _finish(
                ok=False,
                status=MCP_READ_ONLY_STATUS_DENIED,
                reason=f"unsafe path: {p}",
            )

    # 5a. rate / budget governance (bounded, deterministic, fail-closed).
    # Structural: governance ALWAYS applies. Omitting the governor uses the
    # shared default; a caller cannot disable governance with governor=None.
    active_governor = governor if governor is not None else _DEFAULT_GOVERNOR
    budget_ok, budget_reason = active_governor.allow(wake_id, tool)
    if not budget_ok:
        return _finish(
            ok=False,
            status=MCP_READ_ONLY_STATUS_LIMITED,
            reason=budget_reason,
        )

    # 6. provider lookup (fail-soft)
    provider_obj = None
    if isinstance(provider_registry, dict):
        provider_obj = provider_registry.get(tool)
        if provider_obj is None and provider:
            provider_obj = provider_registry.get(provider)
    if provider_obj is None:
        return _finish(
            ok=False,
            status=MCP_READ_ONLY_STATUS_ERROR,
            reason=f"provider not found: {tool}",
        )

    pname = (
        provider
        or getattr(provider_obj, "name", None)
        or getattr(provider_obj, "domain", None)
        or tool.split(".")[0]
    )

    # NOT_CONFIGURED surfaced via provider health
    health = getattr(provider_obj, "health", None)
    if callable(health):
        try:
            healthy = bool(health())
        except Exception:  # noqa: BLE001 — fail-soft boundary
            healthy = False
        if not healthy:
            return _finish(
                ok=False,
                status=MCP_READ_ONLY_STATUS_NOT_CONFIGURED,
                reason=f"provider NOT_CONFIGURED: {tool}",
                provider_name=pname,
            )

    method = "search" if _is_search_tool(tool) else "get"
    fn = getattr(provider_obj, method, None)
    if not callable(fn):
        return _finish(
            ok=False,
            status=MCP_READ_ONLY_STATUS_ERROR,
            reason=f"provider method missing: {method}",
            provider_name=pname,
        )

    try:
        response = _call_with_timeout(fn, timeout_ms, tool=tool, **request)
    except Exception as exc:  # noqa: BLE001 — fail-soft boundary
        return _finish(
            ok=False,
            status=MCP_READ_ONLY_STATUS_ERROR,
            reason=f"{type(exc).__name__}: {exc}",
            provider_name=pname,
        )

    if response is _TIMEOUT:
        return _finish(
            ok=False,
            status=MCP_READ_ONLY_STATUS_TIMEOUT,
            reason=f"timeout after {timeout_ms}ms",
            provider_name=pname,
        )

    if not isinstance(response, dict):
        response = {"value": response}

    if str(response.get("status") or "") == MCP_READ_ONLY_STATUS_NOT_CONFIGURED:
        return _finish(
            ok=False,
            status=MCP_READ_ONLY_STATUS_NOT_CONFIGURED,
            reason=f"provider NOT_CONFIGURED: {tool}",
            response=response,
            provider_name=pname,
        )

    source_asof = response.get("source_asof") or request.get("asof") or _now_iso()

    # 7. response size bound
    serialized = json.dumps(response, sort_keys=True, separators=(",", ":"), default=str)
    size = len(serialized.encode("utf-8"))
    if size > max_response_bytes:
        truncated = serialized.encode("utf-8")[:max_response_bytes].decode("utf-8", "ignore")
        bounded_response = {
            "bounded": True,
            "truncated": True,
            "original_bytes": size,
            "max_response_bytes": max_response_bytes,
            "content": truncated,
        }
        return _finish(
            ok=True,
            status=MCP_READ_ONLY_STATUS_BOUNDED,
            response=bounded_response,
            bounded=True,
            source_asof=source_asof,
            provider_name=pname,
        )

    # 8. redaction + receipt happen inside _finish
    return _finish(
        ok=True,
        status=MCP_READ_ONLY_STATUS_OK,
        response=response,
        source_asof=source_asof,
        provider_name=pname,
    )
