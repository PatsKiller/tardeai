"""Boot helper for Active Trader Stage 0 read API (host-mounted).

Unlike agent-runtime read, Stage 0 does not require a DSN — health/status are
pure scaffolds. Never enables live_canary or order routes.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Mapping, Optional, Tuple

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"built": False, "api": None}


def build_api(env: Optional[Mapping[str, str]] = None, *, config_path: str | None = None):
    env = os.environ if env is None else env
    _ = env  # reserved for future gate; Stage 0 always builds read API
    try:
        from active_trader.flags import load_flags
        from active_trader.read_api import ReadOnlyActiveTraderAPI

        path = config_path or env.get("ACTIVE_TRADER_STAGE0_CONFIG") or None
        flags = load_flags(path)
        return ReadOnlyActiveTraderAPI(flags)
    except Exception:
        # Fail open to empty API with hard write:false via default constructor
        try:
            from active_trader.read_api import ReadOnlyActiveTraderAPI
            return ReadOnlyActiveTraderAPI()
        except Exception:
            return None


def get_api():
    if _STATE["built"]:
        return _STATE["api"]
    with _LOCK:
        if not _STATE["built"]:
            _STATE["api"] = build_api()
            _STATE["built"] = True
    return _STATE["api"]


def reset_for_test() -> None:
    with _LOCK:
        _STATE["built"] = False
        _STATE["api"] = None


def handle(
    method: str,
    path: str,
    query: Mapping[str, Any] | None = None,
) -> Optional[Tuple[int, dict]]:
    from active_trader.read_http import dispatch, is_active_trader_path

    if not is_active_trader_path(path):
        return None
    return dispatch(get_api(), method, path, query or {})
