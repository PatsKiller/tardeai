"""Framework-neutral HTTP dispatcher for the read-only agent-runtime surface.

This module is the production boundary between an ordinary HTTP server and the
zero-authority :class:`ReadOnlyAgentRuntimeAPI`. It:

* derives its route matchers directly from the canonical ``READ_ROUTES`` table
  (`read_api.py`), so the HTTP surface can never drift from the API surface;
* answers **GET only** — any other method returns HTTP 405;
* returns an honest read-only, zero-authority envelope with HTTP 503 whenever the
  reader is not connected (gate off / no DSN / connection failure) so the server
  never crashes and never pretends to have data it lacks;
* bounds ``limit``/``offset`` and never leaks driver/connection details on error.

It imports **no** database driver, subprocess, HTTP client, or secret store, and
holds no mutation/provider/service/schedule/financial authority. The concrete
reader (and therefore the driver import) is injected from outside the
``agent_runtime`` package — see ``scripts/agent_runtime_read_boot.py``.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Optional, Pattern, Tuple

from .read_api import READ_API_CONTRACT, READ_ROUTES, ReadOnlyAgentRuntimeAPI

AGENT_RUNTIME_READ_PREFIX = "/api/v3/agent-runtime"
AGENT_MATURITY_READ_PREFIX = "/api/v3/agent-maturity"

# Hard bounds applied to pagination regardless of what the client sends.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

_ZERO_AUTHORITY = {
    "mutation": False,
    "provider_call": False,
    "service_control": False,
    "schedule_change": False,
    "financial_action": False,
}


def zero_authority_envelope(kind: str, detail: str) -> dict:
    """The single honest shape returned for every non-200 path.

    ``read_only`` is always true and every authority flag is always false, so a
    503/405/400 can never be mistaken for a mutation-capable surface.
    """
    return {
        "contract": READ_API_CONTRACT,
        "read_only": True,
        "kind": kind,
        "data": None,
        "authority": dict(_ZERO_AUTHORITY),
        "detail": detail,
        # A2 post-connect acceptance keys (always present; honest when disconnected).
        "connected": False,
        "reader_role": None,
    }


def _template_to_regex(path: str) -> Pattern[str]:
    parts = []
    for segment in path.split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            parts.append(f"(?P<{segment[1:-1]}>[^/]+)")
        else:
            parts.append(re.escape(segment))
    return re.compile("^" + "/".join(parts) + "$")


# Built from READ_ROUTES so a declared route is always dispatchable and an
# undeclared path can never be served — proven by the route-table match test.
ROUTE_MATCHERS: Tuple[Tuple[Any, Pattern[str]], ...] = tuple(
    (route, _template_to_regex(route.path)) for route in READ_ROUTES
)


def is_agent_runtime_path(path: str) -> bool:
    return (
        path == AGENT_RUNTIME_READ_PREFIX
        or path.startswith(AGENT_RUNTIME_READ_PREFIX + "/")
        or path == AGENT_MATURITY_READ_PREFIX
        or path.startswith(AGENT_MATURITY_READ_PREFIX + "/")
    )


def _is_agent_maturity_path(path: str) -> bool:
    return path == AGENT_MATURITY_READ_PREFIX or path.startswith(AGENT_MATURITY_READ_PREFIX + "/")


def _dispatch_maturity(method: str, path: str, api: Optional[ReadOnlyAgentRuntimeAPI] = None) -> Tuple[int, dict]:
    from .maturity_observability import maturity_agent_payload, maturity_payload, maturity_summary_payload

    if method != "GET":
        return 405, zero_authority_envelope(
            "method_not_allowed", f"{method} is not allowed; the agent-maturity surface is read-only (GET only)"
        )
    root = Path(__file__).resolve().parents[2]
    # When a live read-only reader is wired, the maturity board reflects real
    # runtime evidence; without it, it stays honest repository evidence.
    reader = getattr(api, "reader", None) if api is not None else None
    if path == AGENT_MATURITY_READ_PREFIX:
        return 200, maturity_payload(root, reader=reader)
    if path == f"{AGENT_MATURITY_READ_PREFIX}/summary":
        return 200, maturity_summary_payload(root, reader=reader)
    prefix = AGENT_MATURITY_READ_PREFIX + "/"
    if path.startswith(prefix):
        agent_id = path[len(prefix):].strip("/")
        if not agent_id or "/" in agent_id:
            return 404, zero_authority_envelope("not_found", "no such agent-maturity read route")
        payload = maturity_agent_payload(root, agent_id, reader=reader)
        if payload is None:
            return 404, zero_authority_envelope("not_found", "no such agent-maturity observation")
        return 200, payload
    return 404, zero_authority_envelope("not_found", "no such agent-maturity read route")


def _match(path: str):
    for route, matcher in ROUTE_MATCHERS:
        found = matcher.match(path)
        if found:
            return route, found.groupdict()
    return None, None


def _scalar(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _as_int(value: Any, default: int) -> int:
    value = _scalar(value)
    if value is None or value == "":
        return default
    return int(value)  # ValueError -> 400 in dispatch


def _as_str(value: Any) -> Optional[str]:
    value = _scalar(value)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def dispatch(
    api: Optional[ReadOnlyAgentRuntimeAPI],
    method: str,
    path: str,
    query: Mapping[str, Any] | None = None,
) -> Optional[Tuple[int, dict]]:
    """Resolve one request against the read surface.

    Returns ``(status, body)`` for any path under the agent-runtime prefix, or
    ``None`` for paths this surface does not own (so the host can 404 them).
    """
    if not is_agent_runtime_path(path):
        return None

    if _is_agent_maturity_path(path):
        try:
            return _dispatch_maturity(method, path, api)
        except Exception:
            return 503, zero_authority_envelope("not_connected", "agent-maturity read API is unavailable")

    if method != "GET":
        return 405, zero_authority_envelope(
            "method_not_allowed", f"{method} is not allowed; the agent-runtime surface is read-only (GET only)"
        )

    route, params = _match(path)
    if route is None:
        return 404, zero_authority_envelope("not_found", "no such agent-runtime read route")

    # Gate off / no DSN / reader not wired: honest, zero-authority 503.
    if api is None:
        return 503, zero_authority_envelope(
            "not_connected", "agent-runtime read API is not connected (gate disabled or no reader configured)"
        )

    query = query or {}
    try:
        if route.operation == "list_runs":
            limit = _as_int(query.get("limit"), DEFAULT_LIMIT)
            offset = _as_int(query.get("offset"), 0)
            if limit > MAX_LIMIT:
                limit = MAX_LIMIT
            result = api.list_runs(
                limit=limit,
                offset=offset,
                agent_id=_as_str(query.get("agent_id")),
                status=_as_str(query.get("status")),
            )
        elif route.operation in ("list_lessons", "list_cases"):
            limit = _as_int(query.get("limit"), DEFAULT_LIMIT)
            offset = _as_int(query.get("offset"), 0)
            if limit > MAX_LIMIT:
                limit = MAX_LIMIT
            result = getattr(api, route.operation)(limit=limit, offset=offset)
        else:
            result = getattr(api, route.operation)(params["run_id"])
        return 200, result
    except ValueError as exc:
        # Bad pagination input OR a secret-bearing reader row rejected at the
        # response boundary: fail closed with no data, never leak the offending value.
        return 400, zero_authority_envelope("bad_request", "request rejected")
    except Exception:
        # Reader identity/connection/query failure must never crash the host and
        # must never leak driver internals — collapse to the honest 503 envelope.
        return 503, zero_authority_envelope(
            "not_connected", "agent-runtime read API is unavailable"
        )
