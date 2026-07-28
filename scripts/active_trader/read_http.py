"""HTTP dispatcher for Active Trader Stage 0 read surface (GET only)."""
from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from .read_api import READ_API_CONTRACT, ReadOnlyActiveTraderAPI

ACTIVE_TRADER_PREFIX = "/api/v3/active-trader"

_ZERO_AUTHORITY = {
    "mutation": False,
    "order": False,
    "session_authorize": False,
    "canary": False,
    "financial_action": False,
}


def is_active_trader_path(path: str) -> bool:
    p = path.rstrip("/") or "/"
    return p == ACTIVE_TRADER_PREFIX or p.startswith(ACTIVE_TRADER_PREFIX + "/")


def _envelope(kind: str, detail: str, *, status_hint: int = 404) -> dict[str, Any]:
    return {
        "contract": READ_API_CONTRACT,
        "stage": 0,
        "write": False,
        "canary": False,
        "read_only": True,
        "kind": kind,
        "data": None,
        "authority": dict(_ZERO_AUTHORITY),
        "detail": detail,
        "status_hint": status_hint,
    }


def dispatch(
    api: Optional[ReadOnlyActiveTraderAPI],
    method: str,
    path: str,
    query: Mapping[str, Any] | None = None,
) -> Tuple[int, dict[str, Any]]:
    """Dispatch one request. Always returns (status, body). Never mutates."""
    query = query or {}
    path = (path or "").rstrip("/") or "/"
    method = (method or "GET").upper()

    if not is_active_trader_path(path):
        return 404, _envelope("not_found", f"not an active-trader path: {path}")

    if method != "GET":
        return 405, _envelope(
            "method_not_allowed",
            "Active Trader Stage 0 is GET-only (write:false)",
            status_hint=405,
        )

    if api is None:
        # Still honest Stage 0 posture without config
        api = ReadOnlyActiveTraderAPI()

    # Normalize prefix strip
    if path == ACTIVE_TRADER_PREFIX:
        return 200, {
            **api.health(),
            "endpoints": [
                f"{ACTIVE_TRADER_PREFIX}/health",
                f"{ACTIVE_TRADER_PREFIX}/status",
                f"{ACTIVE_TRADER_PREFIX}/sessions",
                f"{ACTIVE_TRADER_PREFIX}/venue-eligibility?symbol=...",
                f"{ACTIVE_TRADER_PREFIX}/near-ready",
                f"{ACTIVE_TRADER_PREFIX}/scalp/setups",
                f"{ACTIVE_TRADER_PREFIX}/scalp/setup-events?limit=...",
            ],
        }

    suffix = path[len(ACTIVE_TRADER_PREFIX):].lstrip("/")
    if suffix in ("health",):
        return 200, api.health()
    if suffix in ("status",):
        return 200, api.status()
    if suffix in ("sessions",):
        return 200, api.list_sessions()
    if suffix in ("venue-eligibility", "venue_eligibility"):
        symbol = _q1(query, "symbol")
        venue = _q1(query, "venue")
        if not symbol:
            body = _envelope("bad_request", "symbol query parameter is required", status_hint=400)
            return 400, body
        return 200, api.venue_eligibility(symbol, venue or None)
    if suffix in ("near-ready", "near_ready"):
        include_watch = _q1(query, "include_watch").lower() in ("1", "true", "yes")
        return 200, api.near_ready(include_watch=include_watch)
    if suffix in ("scalp/setups", "scalp_setups"):
        return 200, api.scalp_setups()
    if suffix in ("scalp/setup-events", "scalp/setup_events", "scalp_setup_events"):
        lim = _q1(query, "limit")
        return 200, api.scalp_setup_events(
            limit=int(lim) if lim.isdigit() else 50,
            session_date=_q1(query, "session_date") or None,
            setup=_q1(query, "setup") or None,
        )

    return 404, _envelope("not_found", f"unknown endpoint: {suffix}")


def _q1(query: Mapping[str, Any] | None, key: str) -> str:
    """Extract a single string query value (list-safe). Empty string when absent."""
    if not query:
        return ""
    v = query.get(key)
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    return str(v or "").strip()
