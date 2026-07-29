"""Read-only L2 status payloads for ActiveTrader.

Production remains disconnected until a dedicated single-owner gateway publishes an IPC
snapshot.  Tests may inject a deterministic runtime.  No state file, arm intent, port
probe, or frontend build marker is allowed to imply entitlement, subscription, freshness,
or T2.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

L2_STATUS_CONTRACT = "active-trader-l2-status-v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zero_authority() -> dict[str, Any]:
    return {
        "mutation": False,
        "order": False,
        "session_authorize": False,
        "canary": False,
        "financial_action": False,
    }


def _runtime_metadata() -> dict[str, Any]:
    try:
        from .l2_runtime import (
            backend_source_commit,
            served_ui_source_commit,
            runtime_posture,
        )
    except ImportError:  # pragma: no cover
        from l2_runtime import backend_source_commit, served_ui_source_commit, runtime_posture  # type: ignore
    return {
        "source_commit": backend_source_commit(),
        "backend_source_commit": backend_source_commit(),
        "served_ui_source_commit": served_ui_source_commit(),
        "runtime_posture": runtime_posture(),
    }


def _envelope_base(_runtime) -> dict[str, Any]:
    return {
        "contract": L2_STATUS_CONTRACT,
        "read_only": True,
        "write": False,
        "order_path": False,
        "generated_at": _now_iso(),
        "authority": _zero_authority(),
        **_runtime_metadata(),
    }


def _disconnected_payload(runtime, detail: str | None = None) -> dict[str, Any]:
    body = _envelope_base(runtime)
    posture = body.get("runtime_posture") or {}
    body.update(
        {
            "provider_state": "PROVIDER_DISCONNECTED",
            "entitlement_state": "UNKNOWN",
            "quota": None,
            "symbols": {},
            "confirmed_subscriptions": {},
            "detail": detail or posture.get("detail") or "L2 runtime unavailable",
            "connected": False,
            "subscribed_any": False,
            "t2_any": False,
        }
    )
    return body


def _manager_snapshot(runtime, now: Optional[float] = None) -> dict[str, Any]:
    manager = runtime.manager
    if now is not None:
        try:
            manager.tick(now)
        except Exception:
            pass
    return manager.snapshot(_now_iso())


def build_l2_status(runtime) -> dict[str, Any]:
    if runtime is None:
        return _disconnected_payload(runtime)
    manager = runtime.manager
    try:
        connected = bool(manager._connected())
        entitled = bool(manager._entitled())
    except Exception:
        connected = entitled = False
    snapshot = _manager_snapshot(runtime)
    symbols: dict[str, Any] = {}
    for symbol, lifecycle in snapshot.get("symbols", {}).items():
        entry = dict(lifecycle)
        try:
            import time

            decision = runtime.features.evaluate_t2(symbol, time.monotonic(), _now_iso())
            entry["t2"] = decision.to_dict()
        except Exception:
            entry["t2"] = {"is_t2": False, "reason": "EVAL_ERROR"}
        symbols[symbol] = entry

    body = _envelope_base(runtime)
    body.update(
        {
            "provider_state": "CONNECTED" if connected else "PROVIDER_DISCONNECTED",
            "entitlement_state": "AVAILABLE_REALTIME" if connected and entitled else "UNAVAILABLE",
            "connected": connected,
            "quota": snapshot.get("quota"),
            "concurrent_symbols": snapshot.get("concurrent_symbols"),
            "max_concurrent_l2_symbols": snapshot.get("max_concurrent_l2_symbols"),
            "min_dwell_seconds": snapshot.get("min_dwell_seconds"),
            "reconnect_epoch": snapshot.get("reconnect_epoch"),
            "confirmed_subscriptions": snapshot.get("confirmed_subscriptions"),
            "symbols": symbols,
            "subscribed_any": bool(snapshot.get("confirmed_subscriptions")),
            "t2_any": any(entry.get("t2", {}).get("is_t2") for entry in symbols.values()),
            "note": (
                "Injected-runtime truth only. Production remains disconnected until a dedicated "
                "single-owner gateway publishes normalized snapshots."
            ),
        }
    )
    return body


def build_l2_status_symbol(runtime, symbol: str) -> dict[str, Any]:
    normalized = (symbol or "").upper()
    if runtime is None:
        body = _disconnected_payload(runtime)
        body["symbol"] = normalized
        body["lifecycle"] = {"symbol": normalized, "state": "NOT_REQUESTED"}
        body["t2"] = {"is_t2": False, "reason": "PROVIDER_DISCONNECTED"}
        return body

    manager = runtime.manager
    snapshot = _manager_snapshot(runtime)
    lifecycle = snapshot.get("symbols", {}).get(normalized)
    try:
        connected = bool(manager._connected())
        entitled = bool(manager._entitled())
    except Exception:
        connected = entitled = False
    t2 = {"is_t2": False, "reason": "NOT_REQUESTED"}
    try:
        import time

        t2 = runtime.features.evaluate_t2(normalized, time.monotonic(), _now_iso()).to_dict()
    except Exception:
        pass

    body = _envelope_base(runtime)
    body.update(
        {
            "symbol": normalized,
            "provider_state": "CONNECTED" if connected else "PROVIDER_DISCONNECTED",
            "entitlement_state": "AVAILABLE_REALTIME" if connected and entitled else "UNAVAILABLE",
            "connected": connected,
            "quota": snapshot.get("quota"),
            "lifecycle": lifecycle or {"symbol": normalized, "state": "NOT_REQUESTED"},
            "t2": t2,
            "confirmed_subtypes": (lifecycle or {}).get("confirmed_subtypes", []),
            "book_provider_at": (lifecycle or {}).get("provider_at"),
            "book_received_at": (lifecycle or {}).get("received_at"),
            "book_age_ms": (lifecycle or {}).get("book_age_ms"),
            "tape_age_ms": (lifecycle or {}).get("tape_age_ms"),
            "sequence_id": (lifecycle or {}).get("sequence_id"),
            "reconnect_epoch": (lifecycle or {}).get("reconnect_epoch"),
            "feature_snapshot": t2.get("feature") or None,
        }
    )
    return body
