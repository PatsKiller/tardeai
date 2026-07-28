"""Boot helper for the ActiveTrader SESSION CONTROL + SIMULATION plane (host-mounted).

Holds a process-singleton SessionStore (JSON-backed) + SimExecutionEngine, exposed via handle().
Simulation-only: live activation is FEATURE_DISABLED, no live adapter/2FA/credential/order path.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"built": False, "store": None, "engine": None, "flags": None}


def _build():
    import active_trader.session_control as sc
    import active_trader.sim_execution as se
    try:
        from active_trader.feature_flags import load_flags
        flags = load_flags()
    except Exception:
        flags = None
    store_path = os.environ.get("ACTIVE_TRADER_SESSION_STORE") or str(
        Path(__file__).resolve().parent.parent / "data" / "active_trader" / "sessions.json")
    os.makedirs(os.path.dirname(store_path), exist_ok=True)
    return sc.SessionStore(store_path), se.SimExecutionEngine(), flags


def _ensure() -> dict[str, Any]:
    if not _STATE["built"]:
        with _LOCK:
            if not _STATE["built"]:
                try:
                    _STATE["store"], _STATE["engine"], _STATE["flags"] = _build()
                except Exception:
                    _STATE["store"] = _STATE["engine"] = _STATE["flags"] = None
                _STATE["built"] = True
    return _STATE


def handle(method: str, path: str, query: Optional[Mapping[str, Any]],
           body: Optional[Mapping[str, Any]]) -> Tuple[int, dict]:
    st = _ensure()
    if st["store"] is None:
        return 503, {"contract": "active-trader-p3-session-control-v1", "kind": "unavailable",
                     "read_only": False, "write": False, "live": False,
                     "detail": "session control plane unavailable"}
    import active_trader.session_http as sh
    return sh.dispatch(st["store"], st["engine"], method, path, query, body, st["flags"])
