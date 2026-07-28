"""HTTP dispatcher for the Active Trader read surface (GET only)."""
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
    normalized = path.rstrip("/") or "/"
    return normalized == ACTIVE_TRADER_PREFIX or normalized.startswith(ACTIVE_TRADER_PREFIX + "/")


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
    query = query or {}
    path = (path or "").rstrip("/") or "/"
    method = (method or "GET").upper()
    if not is_active_trader_path(path):
        return 404, _envelope("not_found", f"not an active-trader path: {path}")
    if method != "GET":
        return 405, _envelope(
            "method_not_allowed",
            "Active Trader is GET-only (write:false)",
            status_hint=405,
        )
    api = api or ReadOnlyActiveTraderAPI()
    if path == ACTIVE_TRADER_PREFIX:
        return 200, {
            **api.health(),
            "endpoints": [
                f"{ACTIVE_TRADER_PREFIX}/health",
                f"{ACTIVE_TRADER_PREFIX}/status",
                f"{ACTIVE_TRADER_PREFIX}/sessions",
                f"{ACTIVE_TRADER_PREFIX}/venue-eligibility?symbol=...",
                f"{ACTIVE_TRADER_PREFIX}/near-ready",
                f"{ACTIVE_TRADER_PREFIX}/permission-queue",
                f"{ACTIVE_TRADER_PREFIX}/l2-status",
                f"{ACTIVE_TRADER_PREFIX}/l2-status/{{symbol}}",
                f"{ACTIVE_TRADER_PREFIX}/current-marks?symbols=AAPL,TSLA",
                f"{ACTIVE_TRADER_PREFIX}/fire-performance",
                f"{ACTIVE_TRADER_PREFIX}/scalp/setups",
                f"{ACTIVE_TRADER_PREFIX}/scalp/setup-events?limit=...",
                f"{ACTIVE_TRADER_PREFIX}/config",
            ],
        }
    suffix = path[len(ACTIVE_TRADER_PREFIX) :].lstrip("/")
    if suffix == "health":
        return 200, api.health()
    if suffix == "status":
        return 200, api.status()
    if suffix == "sessions":
        return 200, api.list_sessions()
    if suffix in ("venue-eligibility", "venue_eligibility"):
        symbol = _q1(query, "symbol")
        venue = _q1(query, "venue")
        if not symbol:
            return 400, _envelope("bad_request", "symbol query parameter is required", status_hint=400)
        return 200, api.venue_eligibility(symbol, venue or None)
    if suffix in ("near-ready", "near_ready"):
        include_watch = _q1(query, "include_watch").lower() in ("1", "true", "yes")
        return 200, api.near_ready(include_watch=include_watch)
    if suffix in ("permission-queue", "permission_queue"):
        return 200, api.permission_queue()
    if suffix in ("l2-status", "l2_status"):
        return 200, api.l2_status()
    if suffix.startswith("l2-status/") or suffix.startswith("l2_status/"):
        symbol = suffix.split("/", 1)[1].strip()
        if not symbol:
            return 400, _envelope("bad_request", "symbol path segment required", status_hint=400)
        return 200, api.l2_status_symbol(symbol)
    if suffix in ("current-marks", "current_marks"):
        raw = _q1(query, "symbols") or _q1(query, "symbol")
        symbols = [part.strip() for part in raw.split(",") if part.strip()]
        if not symbols:
            return 400, _envelope("bad_request", "symbols query parameter is required", status_hint=400)
        try:
            from .current_marks_api import current_marks_payload

            return 200, current_marks_payload(symbols)
        except Exception as exc:
            return 503, _envelope(
                "unavailable",
                f"current marks unavailable: {type(exc).__name__}",
                status_hint=503,
            )
    if suffix in ("fire-performance", "fire_performance"):
        return 200, api.fire_performance()
    if suffix in ("config", "config-overview", "config_overview"):
        try:
            from .config_read import config_overview

            return 200, config_overview()
        except Exception as exc:
            return 503, _envelope("unavailable", f"config overview unavailable: {exc}", status_hint=503)
    if suffix in ("scalp/setups", "scalp_setups"):
        return 200, api.scalp_setups()
    if suffix in ("scalp/setup-events", "scalp/setup_events", "scalp_setup_events"):
        limit = _q1(query, "limit")
        return 200, api.scalp_setup_events(
            limit=int(limit) if limit.isdigit() else 50,
            session_date=_q1(query, "session_date") or None,
            setup=_q1(query, "setup") or None,
        )
    return 404, _envelope("not_found", f"unknown endpoint: {suffix}")


def _q1(query: Mapping[str, Any] | None, key: str) -> str:
    if not query:
        return ""
    value = query.get(key)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value or "").strip()
