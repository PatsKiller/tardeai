"""Read-only ActiveTrader fire-performance payload.

Today's latest fire per symbol is selected first, then globally ordered by recency before
LIMIT.  Current fallback marks are batch-read from ``ticker_prices`` once per request,
not once per symbol.  Fire facts stay immutable; observed performance is explicitly
partial until replay or finalized outcomes provide complete coverage.
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
    return {
        "mutation": False,
        "order": False,
        "session_authorize": False,
        "canary": False,
        "financial_action": False,
    }


def build_fire_performance(
    fires: list[dict[str, Any]],
    *,
    resolver,
    tracker,
    now_iso: str,
    l2_state_lookup: Optional[Callable[[str], str]] = None,
    finalized_lookup: Optional[Callable[[dict], Optional[str]]] = None,
) -> dict[str, Any]:
    active: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    for fire in fires:
        symbol = str(fire.get("symbol") or "")
        mark = resolver.resolve(symbol) if resolver is not None else None
        l2_now = l2_state_lookup(symbol) if l2_state_lookup else None
        finalized = finalized_lookup(fire) if finalized_lookup else fire.get("finalized_outcome")
        performance = tracker.update(
            fire,
            current_bid=mark.bid if mark else None,
            current_ask=mark.ask if mark else None,
            current_last=mark.last if mark else None,
            mark_source=mark.source if mark else None,
            mark_at_iso=mark.at if mark else None,
            now_iso=now_iso,
            l2_state_now=l2_now,
            finalized_outcome=finalized,
        )
        (active if performance["in_active_queue"] else history).append(performance)
    active.sort(key=lambda item: item.get("fired_at") or "", reverse=True)
    history.sort(key=lambda item: item.get("fired_at") or "", reverse=True)
    return {
        "contract": FIRE_PERF_CONTRACT,
        "read_only": True,
        "write": False,
        "order_path": False,
        "generated_at": now_iso,
        "active_fires": active,
        "fire_history": history,
        "active_count": len(active),
        "history_count": len(history),
        "authority": _zero_authority(),
        "performance_coverage": "OBSERVED_MARKS_ONLY_UNTIL_FINALIZED_REPLAY",
        "note": (
            "Fire price/fired_at are immutable. Current marks and deltas are server-side. "
            "Intraprocess MFE/MAE covers observed polls only; finalized replay outcomes remain "
            "the record of record."
        ),
    }


def _et_today() -> str:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def _todays_fires(limit: int = 100) -> list[dict[str, Any]]:
    """Latest fire per symbol, globally ordered by recency after deduplication."""
    try:
        import sys

        scripts_path = str(_REPO_ROOT / "scripts")
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        from db_adapter import get_connection
    except Exception:
        return []

    bounded_limit = max(1, min(int(limit or 100), 200))
    try:
        connection = get_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """WITH latest_per_symbol AS (
                       SELECT DISTINCT ON (symbol)
                              id, symbol, fired_at, lane, primary_setup_id,
                              primary_setup_label, setup_state, gate_result,
                              entry_ref, stop_ref, data_tier
                       FROM scalp_ignition_events
                       WHERE session_date = %s
                         AND (setup_state = 'FIRED' OR lane = 'TRIGGER')
                       ORDER BY symbol, fired_at DESC, id DESC
                   )
                   SELECT id, symbol, fired_at, lane, primary_setup_id,
                          primary_setup_label, setup_state, gate_result,
                          entry_ref, stop_ref, data_tier
                   FROM latest_per_symbol
                   ORDER BY fired_at DESC, id DESC
                   LIMIT %s""",
                (_et_today(), bounded_limit),
            )
            columns = [description[0] for description in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception:
        return []

    fires: list[dict[str, Any]] = []
    for row in rows:
        fired_at = row.get("fired_at")
        fires.append(
            {
                "fire_id": f"fire-{row.get('id')}",
                "id": row.get("id"),
                "symbol": row.get("symbol"),
                "fired_at": fired_at.isoformat() if hasattr(fired_at, "isoformat") else fired_at,
                "lane": row.get("lane"),
                "primary_setup_id": row.get("primary_setup_id"),
                "primary_setup_label": row.get("primary_setup_label"),
                "setup_state": row.get("setup_state"),
                "gate_decision": row.get("gate_result") or "DEFER",
                "fire_price": row.get("entry_ref"),
                "stop_ref": row.get("stop_ref"),
                "l2_state_at_fire": "T2" if row.get("data_tier") == "T2" else "L2_NOT_CONFIRMED",
            }
        )
    return fires


def _approved_provider_factory(symbols: list[str]):
    """Batch-read the approved fallback marks once for the request."""
    wanted = sorted({str(symbol).upper() for symbol in symbols if symbol})
    if not wanted:
        return lambda _symbol: None
    try:
        import sys

        scripts_path = str(_REPO_ROOT / "scripts")
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        from db_adapter import get_connection
    except Exception:
        return None

    marks: dict[str, dict[str, Any]] = {}
    try:
        connection = get_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT DISTINCT ON (symbol)
                          symbol, bid, ask, price, updated_at
                   FROM ticker_prices
                   WHERE symbol = ANY(%s)
                   ORDER BY symbol, updated_at DESC""",
                (wanted,),
            )
            for symbol, bid, ask, price, updated_at in cursor.fetchall():
                marks[str(symbol).upper()] = {
                    "bid": float(bid) if bid is not None else None,
                    "ask": float(ask) if ask is not None else None,
                    "last": float(price) if price is not None else None,
                    "at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
                    "source": "ticker_prices",
                }
    except Exception:
        return None

    return lambda symbol: marks.get(str(symbol).upper())


def fire_performance_payload(limit: int = 100) -> dict[str, Any]:
    try:
        from .live_mark import LiveMarkResolver
        from .l2_runtime import get_runtime
        from .fire_performance import FirePerfTracker, FirePerfConfig
    except ImportError:  # pragma: no cover
        from live_mark import LiveMarkResolver  # type: ignore
        from l2_runtime import get_runtime  # type: ignore
        from fire_performance import FirePerfTracker, FirePerfConfig  # type: ignore

    runtime = get_runtime()
    fires = _todays_fires(limit)
    gateway = runtime.gateway if runtime else None
    manager = runtime.manager if runtime else None

    def is_moomoo_marked(symbol: str) -> bool:
        if manager is None:
            return False
        try:
            return symbol.upper() in manager.confirmed_subscriptions()
        except Exception:
            return False

    def l2_now(symbol: str) -> str:
        if manager is None:
            return "L2_DISCONNECTED"
        lifecycle = manager.symbols.get(symbol.upper())
        return lifecycle.state.value if lifecycle else "NOT_REQUESTED"

    approved_provider = _approved_provider_factory([fire.get("symbol") for fire in fires])
    resolver = LiveMarkResolver(
        gateway=gateway,
        is_moomoo_marked=is_moomoo_marked,
        approved_provider=approved_provider,
    )
    tracker = runtime.fire_tracker if runtime is not None else FirePerfTracker(FirePerfConfig())
    return build_fire_performance(
        fires,
        resolver=resolver,
        tracker=tracker,
        now_iso=_now_iso(),
        l2_state_lookup=l2_now,
    )
