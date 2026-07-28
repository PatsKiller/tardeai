"""ActiveTrader L2 runtime boundary.

Production requests must never create or own an OpenD quote context. The canonical
architecture requires one long-lived gateway service to own subscriptions and publish
normalized read snapshots. PR #247 did not implement that service boundary: its lazy
request-path singleton could open one context in ``portfolio_server`` while the scalp
cron opened another. Until an external gateway/IPC contract exists, production is
therefore deliberately fail-closed.

Tests may inject an in-memory ``L2Runtime`` with ``set_runtime_for_test``. A state file
is desired intent only and never creates a connection, subscription, entitlement, or T2.
Read plane only; no order or trade-unlock path.
"""
from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARM_STATE = _REPO_ROOT / "data" / "scalp" / "moomoo_armed_state.json"

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"built": False, "runtime": None}


@lru_cache(maxsize=1)
def backend_source_commit() -> str:
    """Best-effort backend checkout provenance, cached for the process lifetime."""
    try:
        import subprocess

        result = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


@lru_cache(maxsize=1)
def served_ui_source_commit() -> str:
    """Best-effort served-bundle provenance, cached for the process lifetime."""
    meta = _REPO_ROOT / "apps" / "command-center-v3" / "dist" / "build-meta.json"
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        for key in ("source_commit", "source_commit_sha", "commit"):
            if data.get(key):
                return str(data[key])
    except Exception:
        pass
    return "unknown"


def source_commit() -> str:
    """Backward-compatible alias for the backend source commit."""
    return backend_source_commit()


def runtime_posture() -> dict[str, Any]:
    """Return the production owner posture without touching OpenD."""
    return {
        "mode": "DISABLED_PENDING_DEDICATED_GATEWAY",
        "owner_ready": False,
        "connected": False,
        "detail": (
            "No dedicated single-owner gateway/IPC ingestion loop is implemented. "
            "Request handlers and scalp cron jobs are prohibited from opening OpenD contexts."
        ),
        "backend_source_commit": backend_source_commit(),
        "served_ui_source_commit": served_ui_source_commit(),
    }


class L2Runtime:
    """Injected read runtime used by deterministic tests and a future gateway client."""

    def __init__(self, gateway, manager, features, fire_tracker, config):
        self.gateway = gateway
        self.manager = manager
        self.features = features
        self.fire_tracker = fire_tracker
        self.config = config

    def desired_from_state_file(self) -> list[str]:
        """Read desired symbols from the arm-state file (intent only)."""
        try:
            if not _ARM_STATE.is_file():
                return []
            data = json.loads(_ARM_STATE.read_text(encoding="utf-8"))
            armed = data.get("armed") if isinstance(data, dict) else data
            if isinstance(armed, dict):
                return [str(symbol).upper() for symbol in armed]
            if isinstance(armed, list):
                return [
                    str(item.get("symbol") if isinstance(item, dict) else item).upper()
                    for item in armed
                ]
        except Exception:
            return []
        return []


def _build() -> Optional[L2Runtime]:
    """Production construction is intentionally disabled.

    A process-local singleton is not a system-wide single owner and there is no worker
    in PR #247 that drives subscriptions, quote/tape ingestion, freshness ticks, or
    reconnect recovery. Returning ``None`` keeps every production status surface
    explicitly disconnected until a dedicated gateway service and IPC snapshot contract
    are implemented and independently integration-tested.
    """
    return None


def get_runtime() -> Optional[L2Runtime]:
    if _STATE["built"]:
        return _STATE["runtime"]
    with _LOCK:
        if not _STATE["built"]:
            _STATE["runtime"] = _build()
            _STATE["built"] = True
    return _STATE["runtime"]


def reset_for_test() -> None:
    with _LOCK:
        _STATE["built"] = False
        _STATE["runtime"] = None


def set_runtime_for_test(runtime: Optional[L2Runtime]) -> None:
    """Inject a deterministic in-memory runtime; never use in production startup."""
    with _LOCK:
        _STATE["runtime"] = runtime
        _STATE["built"] = True
