"""Read-only fire-performance payload for ActiveTrader (/fire-performance).

Joins today's FIRED setups (immutable fire facts) with live current marks + the server-side
performance reducer, and splits them into the ACTIVE queue vs TODAY'S FIRE HISTORY. Finalized
T+1 outcomes pass through untouched (record of record). Read plane only — no order path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]

FIRE_PERF_CONTRACT = "active-trader-fire-performance-v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zero_authority() -> dict[str, Any]:
    return {"mutation": False, "order": False, "session_authorize": False,
            "canary": False, "financial_action": False}


def build_fire_performance(
    fires: list[dict[str, Any]],
    *,
    resolver,
    tracker,
    now_iso: str,
    l2_state_lookup: Optional[Callable[[str], str]] = None,
    finalized_lookup: Optional[Callable[[dict], Optional[str]]] = None,
) -> dict[str, Any]:
    """Pure builder: fire facts + injected mark resolver/tracker → active + history split.

    Deterministic in tests — inject a fake resolver (fixed marks) and a FirePerfTracker."""
    active: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    for fire in fires:
        sym = str(fire.get("symbol") or "")
        mark = resolver.resolve(sym) if resolver is not None else None
        l2_now = l2_state_lookup(sym) if l2_state_lookup else None
        finalized = finalized_lookup(fire) if finalized_lookup else fire.get("finalized_outcome")
        perf = tracker.update(
            fire,
            current_bid=(mark.bid if mark else None),
            current_ask=(mark.ask if mark else None),
            current_last=(mark.last if mark else None),
            mark_source=(mark.source if mark else None),
            mark_at_iso=(mark.at if mark else None),
            now_iso=now_iso,
            l2_state_now=l2_now,
            finalized_outcome=finalized,
        )
        (active if perf["in_active_queue"] else history).append(perf)
    # newest fire first within each section
    active.sort(key=lambda p: (p.get("fired_at") or ""), reverse=True)
    history.sort(key=lambda p: (p.get("fired_at") or ""), reverse=True)
    return {
        "contract": FIRE_PERF_CONTRACT,
        "read_only": True, "write": False, "order_path": False,
        "generated_at": now_iso,
        "active_fires": active,
        "fire_history": history,
        "active_count": len(active),
        "history_count": len(history),
        "authority": _zero_authority(),
        "note": ("Fire price / fired_at are immutable; current mark, change, MFE/MAE and "
                 "current-R are computed server-side from live marks. Finalized outcomes are "
                 "the record of record and are never overwritten."),
    }


# ── DB-backed today's fires ──────────────────────────────────────────────────
def _et_today() -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def _todays_fires(limit: int = 100) -> list[dict[str, Any]]:
    """TODAY's FIRED setups from scalp_ignition_events as immutable fire facts. Fail-closed []."""
    try:
        import sys
        sp = str(_REPO_ROOT / "scripts")
        if sp not in sys.path:
            sys.path.insert(0, sp)
        from db_adapter import get_connection
    except Exception:
        return []
    lim = max(1, min(int(limit or 100), 200))
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT ON (symbol) id, symbol, fired_at, lane, primary_setup_id,
                          primary_setup_label, setup_state, gate_result, entry_ref, stop_ref,
                          data_tier
                   FROM scalp_ignition_events
                   WHERE session_date = %s AND (setup_state = 'FIRED' OR lane = 'TRIGGER')
                   ORDER BY symbol, fired_at DESC, id DESC
                   LIMIT %s""",
                (_et_today(), lim))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        return []
    fires = []
    for r in rows:
        fa = r.get("fired_at")
        fires.append({
            "fire_id": f"fire-{r.get('id')}",
            "id": r.get("id"),
            "symbol": r.get("symbol"),
            "fired_at": fa.isoformat() if hasattr(fa, "isoformat") else fa,
            "lane": r.get("lane"),
            "primary_setup_id": r.get("primary_setup_id"),
            "primary_setup_label": r.get("primary_setup_label"),
            "setup_state": r.get("setup_state"),
            "gate_decision": (r.get("gate_result") or "DEFER"),
            "fire_price": r.get("entry_ref"),        # immutable fire reference
            "stop_ref": r.get("stop_ref"),
            "l2_state_at_fire": ("T2" if r.get("data_tier") == "T2" else "L2_NOT_CONFIRMED"),
        })
    return fires


def _approved_provider_factory():
    """Best-effort approved current-quote provider for non-Moomoo symbols. None-safe."""
    try:
        import sys
        sp = str(_REPO_ROOT / "scripts")
        if sp not in sys.path:
            sys.path.insert(0, sp)
        from db_adapter import get_connection
    except Exception:
        return None

    def _provider(symbol: str) -> Optional[dict]:
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT bid, ask, price, updated_at FROM ticker_prices WHERE symbol=%s "
                    "ORDER BY updated_at DESC LIMIT 1", (symbol.upper(),))
                row = cur.fetchone()
            if not row:
                return None
            bid, ask, price, at = row
            return {"bid": float(bid) if bid is not None else None,
                    "ask": float(ask) if ask is not None else None,
                    "last": float(price) if price is not None else None,
                    "at": at.isoformat() if hasattr(at, "isoformat") else at,
                    "source": "ticker_prices"}
        except Exception:
            return None
    return _provider


def fire_performance_payload(limit: int = 100) -> dict[str, Any]:
    """Live payload: today's fires + current marks + performance, active/history split."""
    try:
        from .live_mark import LiveMarkResolver
        from .l2_runtime import get_runtime
        from .fire_performance import FirePerfTracker, FirePerfConfig
    except ImportError:  # pragma: no cover
        from live_mark import LiveMarkResolver  # type: ignore
        from l2_runtime import get_runtime  # type: ignore
        from fire_performance import FirePerfTracker, FirePerfConfig  # type: ignore

    rt = get_runtime()
    fires = _todays_fires(limit)
    gateway = rt.gateway if rt else None
    manager = rt.manager if rt else None

    def _is_moomoo_marked(sym: str) -> bool:
        if manager is None:
            return False
        try:
            return sym.upper() in manager.confirmed_subscriptions()
        except Exception:
            return False

    def _l2_now(sym: str) -> str:
        if manager is None:
            return "L2_DISCONNECTED"
        life = manager.symbols.get(sym.upper())
        return life.state.value if life else "NOT_REQUESTED"

    resolver = LiveMarkResolver(gateway=gateway, is_moomoo_marked=_is_moomoo_marked,
                                approved_provider=_approved_provider_factory())
    if rt is not None:
        tracker = rt.fire_tracker
    else:
        tracker = FirePerfTracker(FirePerfConfig())
    return build_fire_performance(fires, resolver=resolver, tracker=tracker,
                                  now_iso=_now_iso(), l2_state_lookup=_l2_now)
