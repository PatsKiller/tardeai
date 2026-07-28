"""ActiveTrader boundary for the dedicated Moomoo L2 gateway IPC snapshot.

Production request handlers never own OpenD. They read the atomic snapshot published by the
single service-level owner. Tests may continue to inject the deterministic in-memory runtime.
"""
from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"built": False, "runtime": None}


@lru_cache(maxsize=1)
def backend_source_commit() -> str:
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
    return backend_source_commit()


class L2Runtime:
    """Injected deterministic runtime retained for unit tests."""

    kind = "in_memory"

    def __init__(self, gateway, manager, features, fire_tracker, config):
        self.gateway = gateway
        self.manager = manager
        self.features = features
        self.fire_tracker = fire_tracker
        self.config = config


class IPCSnapshotRuntime:
    """Read-only client for the external owner; contains no transport or OpenD context."""

    kind = "ipc_snapshot"

    def __init__(self, client):
        self.client = client
        self.gateway = None
        self.manager = None
        self.features = None
        self.fire_tracker = None
        self.config = None

    def snapshot_read(self):
        return self.client.read()


def _client():
    try:
        from moomoo.gateway_ipc import SnapshotClient
    except ImportError:  # pragma: no cover
        from scripts.moomoo.gateway_ipc import SnapshotClient  # type: ignore
    return SnapshotClient()


def runtime_posture() -> dict[str, Any]:
    client = _client()
    read = client.read()
    payload = read.payload or {}
    provider = payload.get("provider") or {}
    owner = payload.get("owner") or {}
    return {
        "mode": "DEDICATED_GATEWAY_IPC" if payload else "DISABLED_PENDING_DEDICATED_GATEWAY",
        "owner_ready": bool(read.fresh and owner.get("exclusive_lock_held")),
        "connected": bool(read.fresh and provider.get("connected")),
        "snapshot_fresh": read.fresh,
        "snapshot_reason": read.reason,
        "snapshot_age_seconds": read.age_seconds,
        "snapshot_path": str(client.path),
        "gateway_source_commit": payload.get("source_commit"),
        "detail": (
            "Fresh snapshot from dedicated single-owner gateway."
            if read.fresh
            else "No fresh dedicated-gateway snapshot; request handlers remain disconnected."
        ),
        "backend_source_commit": backend_source_commit(),
        "served_ui_source_commit": served_ui_source_commit(),
    }


def _build() -> Optional[IPCSnapshotRuntime]:
    client = _client()
    # A stale snapshot is still represented so status can report its exact stale reason.
    return IPCSnapshotRuntime(client) if client.path.is_file() else None


def get_runtime() -> Optional[L2Runtime | IPCSnapshotRuntime]:
    if _STATE["built"] and _STATE["runtime"] is not None:
        return _STATE["runtime"]
    with _LOCK:
        if not _STATE["built"]:
            _STATE["runtime"] = _build()
            _STATE["built"] = True
        elif _STATE["runtime"] is None:
            # portfolio-server may start before the independently managed gateway.
            # Discover the snapshot later without a server restart.
            _STATE["runtime"] = _build()
    return _STATE["runtime"]


def reset_for_test() -> None:
    with _LOCK:
        _STATE["built"] = False
        _STATE["runtime"] = None


def set_runtime_for_test(runtime: Optional[L2Runtime | IPCSnapshotRuntime]) -> None:
    with _LOCK:
        _STATE["runtime"] = runtime
        _STATE["built"] = True
