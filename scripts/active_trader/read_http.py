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
    _ = query
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
            ],
        }

    suffix = path[len(ACTIVE_TRADER_PREFIX):].lstrip("/")
    if suffix in ("health",):
        return 200, api.health()
    if suffix in ("status",):
        return 200, api.status()
    if suffix in ("sessions",):
        return 200, api.list_sessions()

    return 404, _envelope("not_found", f"unknown Stage 0 endpoint: {suffix}")
