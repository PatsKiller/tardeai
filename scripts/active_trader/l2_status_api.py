"""Read-only L2 status payloads from either injected tests or dedicated-gateway IPC."""
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
        "trade_unlock": False,
    }


def _runtime_metadata() -> dict[str, Any]:
    try:
        from .l2_runtime import backend_source_commit, served_ui_source_commit, runtime_posture
    except ImportError:  # pragma: no cover
        from l2_runtime import backend_source_commit, served_ui_source_commit, runtime_posture  # type: ignore
    return {
        "source_commit": backend_source_commit(),
        "backend_source_commit": backend_source_commit(),
        "served_ui_source_commit": served_ui_source_commit(),
        "runtime_posture": runtime_posture(),
    }


def _envelope_base() -> dict[str, Any]:
    return {
        "contract": L2_STATUS_CONTRACT,
        "contract_revision": 2,
        "read_only": True,
        "write": False,
        "order_path": False,
        "generated_at": _now_iso(),
        "authority": _zero_authority(),
        **_runtime_metadata(),
    }


def _disconnected_payload(runtime, detail: str | None = None, *, provider_state: str = "PROVIDER_DISCONNECTED") -> dict[str, Any]:
    body = _envelope_base()
    posture = body.get("runtime_posture") or {}
    body.update(
        {
            "provider_state": provider_state,
            "entitlement_state": "UNKNOWN",
            "quota": None,
            "symbols": {},
            "confirmed_subscriptions": {},
            "detail": detail or posture.get("detail") or "L2 runtime unavailable",
            "connected": False,
            "subscribed_any": False,
            "t2_any": False,
            "ipc_snapshot_fresh": False,
        }
    )
    return body


def _build_ipc_status(runtime) -> dict[str, Any]:
    read = runtime.snapshot_read()
    payload = read.payload or {}
    if not read.fresh:
        body = _disconnected_payload(
            runtime,
            f"gateway IPC unavailable: {read.reason}",
            provider_state="SNAPSHOT_STALE" if payload else "PROVIDER_DISCONNECTED",
        )
        body.update(
            {
                "ipc_snapshot_reason": read.reason,
                "ipc_snapshot_age_seconds": read.age_seconds,
                "gateway_source_commit": payload.get("source_commit"),
                "gateway_owner": payload.get("owner"),
                "last_snapshot_at": payload.get("heartbeat_at"),
            }
        )
        return body
    provider = payload.get("provider") or {}
    symbols = payload.get("symbols") or {}
    connected = bool(provider.get("connected"))
    entitled = bool(provider.get("entitled_realtime"))
    confirmed = {
        symbol: list((detail or {}).get("confirmed_subtypes") or [])
        for symbol, detail in symbols.items()
        if (detail or {}).get("confirmed_subtypes")
    }
    body = _envelope_base()
    body.update(
        {
            "provider_state": "CONNECTED" if connected else "PROVIDER_DISCONNECTED",
            "entitlement_state": "AVAILABLE_REALTIME" if connected and entitled else "UNAVAILABLE",
            "connected": connected,
            "quota": payload.get("quota"),
            "concurrent_symbols": payload.get("concurrent_symbols"),
            "max_concurrent_l2_symbols": payload.get("max_concurrent_l2_symbols"),
            "min_dwell_seconds": payload.get("min_dwell_seconds"),
            "reconnect_epoch": provider.get("reconnect_epoch"),
            "provider_subscriptions": provider.get("subscriptions_by_symbol") or {},
            "confirmed_subscriptions": confirmed,
            "symbols": symbols,
            "current_marks": payload.get("current_marks") or {},
            "subscribed_any": bool(provider.get("subscriptions_by_symbol")),
            "t2_any": any(bool((detail or {}).get("t2", {}).get("is_t2")) for detail in symbols.values()),
            "ipc_snapshot_fresh": True,
            "ipc_snapshot_reason": read.reason,
            "ipc_snapshot_age_seconds": read.age_seconds,
            "gateway_source_commit": payload.get("source_commit"),
            "gateway_owner": payload.get("owner"),
            "journal": payload.get("journal"),
            "note": "Dedicated single-owner gateway snapshot. Provider acceptance and observed subtype confirmation remain separate facts.",
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
    if getattr(runtime, "kind", None) == "ipc_snapshot":
        return _build_ipc_status(runtime)
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

            entry["t2"] = runtime.features.evaluate_t2(symbol, time.monotonic(), _now_iso()).to_dict()
        except Exception:
            entry["t2"] = {"is_t2": False, "reason": "EVAL_ERROR"}
        symbols[symbol] = entry
    body = _envelope_base()
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
            "ipc_snapshot_fresh": False,
            "note": "Injected deterministic runtime.",
        }
    )
    return body


def build_l2_status_symbol(runtime, symbol: str) -> dict[str, Any]:
    normalized = (symbol or "").upper()
    full = build_l2_status(runtime)
    lifecycle = (full.get("symbols") or {}).get(normalized)
    if lifecycle is None:
        lifecycle = {"symbol": normalized, "state": "NOT_REQUESTED"}
    t2 = lifecycle.get("t2") or {"is_t2": False, "reason": "NOT_REQUESTED"}
    body = {
        **full,
        "symbol": normalized,
        "lifecycle": lifecycle,
        "t2": t2,
        "confirmed_subtypes": lifecycle.get("confirmed_subtypes", []),
        "provider_subtypes": lifecycle.get("provider_subtypes", []),
        "book_provider_at": (lifecycle.get("book") or {}).get("provider_at", lifecycle.get("provider_at")),
        "book_bid_provider_at": (lifecycle.get("book") or {}).get("bid_provider_at"),
        "book_ask_provider_at": (lifecycle.get("book") or {}).get("ask_provider_at"),
        "book_received_at": (lifecycle.get("book") or {}).get("received_at", lifecycle.get("received_at")),
        "tape_provider_at": (lifecycle.get("tape") or {}).get("provider_at"),
        "tape_received_at": (lifecycle.get("tape") or {}).get("received_at"),
        "quote_provider_at": (lifecycle.get("quote") or {}).get("provider_at"),
        "quote_received_at": (lifecycle.get("quote") or {}).get("received_at"),
        "book_age_ms": lifecycle.get("book_age_ms"),
        "tape_age_ms": lifecycle.get("tape_age_ms"),
        "sequence_id": (lifecycle.get("book") or {}).get("sequence_id", lifecycle.get("sequence_id")),
        "sequence_source": (lifecycle.get("book") or {}).get("sequence_source"),
        "reconnect_epoch": lifecycle.get("reconnect_epoch"),
        "feature_snapshot": t2.get("feature") or None,
        "current_mark": (full.get("current_marks") or {}).get(normalized),
    }
    return body
