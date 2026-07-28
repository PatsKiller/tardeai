"""HTTP dispatcher for Active Trader read surfaces (GET only)."""
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


def _account_agnostic_permission_queue(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Remove legacy static account/environment assumptions from the review read model.

    Market-state evidence may be reviewed without binding an account. Until a runtime
    account registry supplies verified capabilities, the API returns an empty account
    set and an explicit UNBOUND state. This adapter is read-only and cannot authorize.
    """
    body = dict(raw)
    signals: list[dict[str, Any]] = []
    for item in body.get("signals") if isinstance(body.get("signals"), list) else []:
        if not isinstance(item, Mapping):
            continue
        signal = dict(item)
        # Preserve the compatibility key while removing environment semantics.
        signal["mode"] = "REVIEW_ONLY"
        signals.append(signal)
    body["signals"] = signals
    body["mode"] = "REVIEW_ONLY"
    body["accounts"] = []
    body["account_binding_state"] = "UNBOUND"
    body["account_capability_source"] = "NOT_CONFIGURED"
    body["posture"] = {
        "account_binding": "UNBOUND",
        "account_capability_source": "NOT_CONFIGURED",
        "execution_routes": False,
        "order_path": False,
        "final_submit_present": False,
        "automation": "none_wired",
    }
    body["note"] = (
        "Read-only review evidence. Account, venue, environment, and execution "
        "authority are not bound by this endpoint."
    )
    body["authority"] = dict(_ZERO_AUTHORITY)
    return body


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
            "Active Trader read surfaces are GET-only (write:false)",
            status_hint=405,
        )

    if api is None:
        api = ReadOnlyActiveTraderAPI()

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
                f"{ACTIVE_TRADER_PREFIX}/motion",
                f"{ACTIVE_TRADER_PREFIX}/scalp/setups",
                f"{ACTIVE_TRADER_PREFIX}/scalp/setup-events?limit=...",
                f"{ACTIVE_TRADER_PREFIX}/config",
            ],
        }

    suffix = path[len(ACTIVE_TRADER_PREFIX):].lstrip("/")
    if suffix in ("health",):
        return 200, api.health()
    if suffix in ("status",):
        return 200, api.status()
    if suffix in ("sessions",):
        return 200, api.list_sessions()
    if suffix in ("motion", "live-motion", "live_motion"):
        try:
            from .motion_snapshot_api import read_motion_snapshot
            return 200, read_motion_snapshot()
        except Exception:
            return 503, _envelope(
                "unavailable",
                "motion snapshot unavailable",
                status_hint=503,
            )
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
    if suffix in ("permission-queue", "permission_queue"):
        return 200, _account_agnostic_permission_queue(api.permission_queue())
    if suffix in ("config", "config-overview", "config_overview"):
        try:
            from .config_read import config_overview
            return 200, config_overview()
        except Exception as exc:
            return 503, _envelope("unavailable", f"config overview unavailable: {exc}", status_hint=503)
    if suffix in ("scalp/setups", "scalp_setups"):
        return 200, api.scalp_setups()
    if suffix in ("scalp/setup-events", "scalp_setup_events", "scalp_setup_events"):
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
    value = query.get(key)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value or "").strip()
