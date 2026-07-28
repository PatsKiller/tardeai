"""Read-only L2 status payloads for ActiveTrader (/l2-status and /l2-status/{symbol}).

Truth surface for the Moomoo L2 data plane: provider connection, entitlement, SIMULTANEOUS
subscription quota, per-symbol lifecycle, confirmed subscriptions, book/tape timestamps,
freshness, sequence state, and the compact feature snapshot. Every field derives from the
live gateway/subscription-manager — NEVER from a state file's existence.

Zero authority: read_only=true, write=false, order_path=false. No LLM in this path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

L2_STATUS_CONTRACT = "active-trader-l2-status-v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zero_authority() -> dict[str, Any]:
    return {"mutation": False, "order": False, "session_authorize": False,
            "canary": False, "financial_action": False}


def _envelope_base(runtime) -> dict[str, Any]:
    try:
        from .l2_runtime import source_commit
    except ImportError:  # pragma: no cover
        from l2_runtime import source_commit  # type: ignore
    return {
        "contract": L2_STATUS_CONTRACT,
        "read_only": True, "write": False, "order_path": False,
        "source_commit": source_commit(),
        "generated_at": _now_iso(),
        "authority": _zero_authority(),
    }


def _disconnected_payload(runtime, detail: str = "L2 runtime unavailable") -> dict[str, Any]:
    body = _envelope_base(runtime)
    body.update({
        "provider_state": "PROVIDER_DISCONNECTED",
        "entitlement_state": "UNKNOWN",
        "quota": None,
        "symbols": {},
        "confirmed_subscriptions": {},
        "detail": detail,
        # explicit: nothing here implies a live/connected/subscribed L2
        "connected": False, "subscribed_any": False, "t2_any": False,
    })
    return body


def _mgr_snapshot(runtime, now: Optional[float] = None) -> dict[str, Any]:
    """Read the manager's current (already tick-driven) state.

    We do NOT force a tick here: freshness/expiry are advanced by the ingestion loop on
    the SAME monotonic clock that timestamps book/tape. Ticking with an unrelated clock
    from the read path would flip a just-ingested FRESH book to STALE. When a caller has a
    consistent clock it may pass `now`."""
    mgr = runtime.manager
    if now is not None:
        try:
            mgr.tick(now)
        except Exception:
            pass
    return mgr.snapshot(_now_iso())


def build_l2_status(runtime) -> dict[str, Any]:
    """Full L2 status across all tracked symbols."""
    if runtime is None:
        return _disconnected_payload(runtime)
    mgr = runtime.manager
    connected = False
    entitled = False
    try:
        connected = bool(mgr._connected())
        entitled = bool(mgr._entitled())
    except Exception:
        pass
    snap = _mgr_snapshot(runtime)
    # per-symbol enrichment: T2 gate + feature snapshot for confirmed-fresh symbols
    symbols_out: dict[str, Any] = {}
    for sym, life in snap.get("symbols", {}).items():
        entry = dict(life)
        try:
            import time as _time
            dec = runtime.features.evaluate_t2(sym, _time.monotonic(), _now_iso())
            entry["t2"] = dec.to_dict()
        except Exception:
            entry["t2"] = {"is_t2": False, "reason": "EVAL_ERROR"}
        symbols_out[sym] = entry

    body = _envelope_base(runtime)
    body.update({
        "provider_state": "CONNECTED" if connected else "PROVIDER_DISCONNECTED",
        "entitlement_state": "AVAILABLE_REALTIME" if (connected and entitled) else "UNAVAILABLE",
        "connected": connected,
        "quota": snap.get("quota"),
        "concurrent_symbols": snap.get("concurrent_symbols"),
        "max_concurrent_l2_symbols": snap.get("max_concurrent_l2_symbols"),
        "min_dwell_seconds": snap.get("min_dwell_seconds"),
        "reconnect_epoch": snap.get("reconnect_epoch"),
        "confirmed_subscriptions": snap.get("confirmed_subscriptions"),
        "symbols": symbols_out,
        "subscribed_any": bool(snap.get("confirmed_subscriptions")),
        "t2_any": any(s.get("t2", {}).get("is_t2") for s in symbols_out.values()),
        "note": ("L2 status is derived from the live gateway/subscription-manager. A state "
                 "file or arm intent NEVER implies connected/subscribed/fresh/T2."),
    })
    return body


def build_l2_status_symbol(runtime, symbol: str) -> dict[str, Any]:
    """Detailed L2 lifecycle for one symbol."""
    sym = (symbol or "").upper()
    if runtime is None:
        body = _disconnected_payload(runtime)
        body["symbol"] = sym
        return body
    mgr = runtime.manager
    snap = _mgr_snapshot(runtime)
    life = snap.get("symbols", {}).get(sym)
    connected = False
    entitled = False
    try:
        connected = bool(mgr._connected())
        entitled = bool(mgr._entitled())
    except Exception:
        pass
    t2 = {"is_t2": False, "reason": "NOT_REQUESTED"}
    try:
        import time as _time
        t2 = runtime.features.evaluate_t2(sym, _time.monotonic(), _now_iso()).to_dict()
    except Exception:
        pass
    body = _envelope_base(runtime)
    body.update({
        "symbol": sym,
        "provider_state": "CONNECTED" if connected else "PROVIDER_DISCONNECTED",
        "entitlement_state": "AVAILABLE_REALTIME" if (connected and entitled) else "UNAVAILABLE",
        "connected": connected,
        "quota": snap.get("quota"),
        "lifecycle": life or {"symbol": sym, "state": "NOT_REQUESTED"},
        "t2": t2,
        "confirmed_subtypes": (life or {}).get("confirmed_subtypes", []),
        "book_provider_at": (life or {}).get("provider_at"),
        "book_received_at": (life or {}).get("received_at"),
        "book_age_ms": (life or {}).get("book_age_ms"),
        "tape_age_ms": (life or {}).get("tape_age_ms"),
        "sequence_id": (life or {}).get("sequence_id"),
        "reconnect_epoch": (life or {}).get("reconnect_epoch"),
        "feature_snapshot": t2.get("feature") or None,
    })
    return body
