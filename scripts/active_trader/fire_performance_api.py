"""Read-only ActiveTrader fire performance with durable gateway-journal replay.

Fire facts are immutable. Current marks come from a fresh dedicated-gateway snapshot, then
one approved batch fallback. MFE/MAE is replay-backed when the gateway journal is available;
coverage is explicitly incomplete across any recorded gap.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
FIRE_PERF_CONTRACT = "active-trader-fire-performance-v1"
_TRACKERS: dict[str, Any] = {}


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
    replay_complete = sum(1 for item in active + history if item.get("coverage_complete_since_fire"))
    return {
        "contract": FIRE_PERF_CONTRACT,
        "contract_revision": 2,
        "read_only": True,
        "write": False,
        "order_path": False,
        "generated_at": now_iso,
        "active_fires": active,
        "fire_history": history,
        "active_count": len(active),
        "history_count": len(history),
        "replay_complete_count": replay_complete,
        "authority": _zero_authority(),
        "performance_coverage": "DURABLE_JOURNAL_REPLAY_WHEN_CONTINUOUS",
        "note": (
            "Fire price/fired_at are immutable. Current marks are timestamped server facts. "
            "MFE/MAE is complete only when the durable journal proves coverage before fire with no gap."
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
                    "source": "approved_ticker_prices",
                }
    except Exception:
        return None
    return lambda symbol: marks.get(str(symbol).upper())


class _SnapshotFirstResolver:
    def __init__(self, snapshot_marks: dict[str, Any], approved_provider):
        try:
            from .live_mark import Mark
        except ImportError:  # pragma: no cover
            from live_mark import Mark  # type: ignore
        self.Mark = Mark
        self.snapshot_marks = snapshot_marks
        self.approved_provider = approved_provider

    def resolve(self, symbol: str):
        normalized = str(symbol).upper()
        raw = self.snapshot_marks.get(normalized)
        if isinstance(raw, dict) and raw.get("available") and not raw.get("stale"):
            # received_at is UTC and is the freshness clock; provider_at is preserved elsewhere.
            return self.Mark(
                normalized,
                raw.get("bid"),
                raw.get("ask"),
                raw.get("last"),
                raw.get("source") or "moomoo_gateway",
                raw.get("received_at"),
                True,
            )
        fallback = self.approved_provider(normalized) if self.approved_provider else None
        if fallback:
            return self.Mark(
                normalized,
                fallback.get("bid"),
                fallback.get("ask"),
                fallback.get("last"),
                fallback.get("source") or "approved_ticker_prices",
                fallback.get("at"),
                True,
            )
        return self.Mark(normalized, None, None, None, None, None, False)


def _snapshot_payload(runtime) -> tuple[dict[str, Any], bool, str]:
    if runtime is None or getattr(runtime, "kind", None) != "ipc_snapshot":
        return {}, False, "NO_IPC_RUNTIME"
    read = runtime.snapshot_read()
    return (read.payload or {}, read.fresh, read.reason)


def _tracker(snapshot: dict[str, Any], runtime, config):
    journal = snapshot.get("journal") or {}
    directory = str(journal.get("directory") or "")
    if directory:
        existing = _TRACKERS.get(directory)
        if existing is not None:
            return existing
        try:
            from .fire_replay import tracker_from_gateway_snapshot

            replay = tracker_from_gateway_snapshot(snapshot, config)
        except Exception:
            replay = None
        if replay is not None:
            _TRACKERS[directory] = replay
            return replay
    if runtime is not None and getattr(runtime, "fire_tracker", None) is not None:
        return runtime.fire_tracker
    try:
        from .fire_performance import FirePerfTracker
    except ImportError:  # pragma: no cover
        from fire_performance import FirePerfTracker  # type: ignore
    fallback = _TRACKERS.get("in_memory_fallback")
    if fallback is None:
        fallback = FirePerfTracker(config)
        _TRACKERS["in_memory_fallback"] = fallback
    return fallback


def fire_performance_payload(limit: int = 100) -> dict[str, Any]:
    try:
        from .fire_performance import FirePerfConfig
        from .l2_runtime import get_runtime
    except ImportError:  # pragma: no cover
        from fire_performance import FirePerfConfig  # type: ignore
        from l2_runtime import get_runtime  # type: ignore
    runtime = get_runtime()
    snapshot, snapshot_fresh, snapshot_reason = _snapshot_payload(runtime)
    fires = _todays_fires(limit)
    snapshot_marks = (snapshot.get("current_marks") or {}) if snapshot_fresh else {}
    approved_provider = _approved_provider_factory([fire.get("symbol") for fire in fires])
    resolver = _SnapshotFirstResolver(snapshot_marks, approved_provider)
    config = FirePerfConfig()
    tracker = _tracker(snapshot if snapshot_fresh else {}, runtime, config)
    symbols = (snapshot.get("symbols") or {}) if snapshot_fresh else {}

    def l2_now(symbol: str) -> str:
        detail = symbols.get(str(symbol).upper()) or {}
        return str(detail.get("state") or "L2_DISCONNECTED")

    result = build_fire_performance(
        fires,
        resolver=resolver,
        tracker=tracker,
        now_iso=_now_iso(),
        l2_state_lookup=l2_now,
    )
    result["gateway_snapshot_fresh"] = snapshot_fresh
    result["gateway_snapshot_reason"] = snapshot_reason
    result["gateway_source_commit"] = snapshot.get("source_commit")
    result["journal"] = snapshot.get("journal") if snapshot_fresh else None
    return result
