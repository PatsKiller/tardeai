"""Strategy Desk — Data Broker read model for strategy registry + signals view.

Queries strategy_registry, strategy_signals, agent_recommendation_outcomes (30d),
strategy_state_transitions, and pattern_library to produce the full strategy desk
view that /api/v2/strategy-desk needs. Consolidates the 5+ DB round-trips in the
endpoint into one broker call.

Status: ADDITIVE. Covers ~90% of the endpoint (all DB queries). The endpoint
handler still handles JSON cleaning of types the broker can't reach (postgreSQL
Decimal etc.), but this module does that inline.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "state" / "data_broker"
SNAPSHOT_PATH = SNAPSHOT_DIR / "strategy_desk.json"
DEFAULT_MAX_AGE_S = 60  # 1 min — signals update in real time


def _clean(val: Any) -> Any:
    """JSON-safe value for Decimal/date types."""
    if val is None:
        return None
    from decimal import Decimal
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, datetime):
        return val.isoformat()
    return val


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: _clean(v) for k, v in (row or {}).items()}


def _build(db_query) -> dict[str, Any]:
    """Recompute strategy desk from DB."""
    # 1. Strategy registry with today's signal counts
    strategies = db_query("""
        SELECT sr.strategy_id, sr.strategy_type, sr.display_name,
               sr.status, sr.min_win_rate, sr.target_win_rate,
               sr.total_signals, sr.trades_taken, sr.active,
               sr.objective, sr.description, sr.timeframe,
               sr.account_fit, sr.min_price, sr.max_price,
               sr.max_float_m, sr.min_rvol, sr.risk_per_trade,
               sr.scoring_profile,
               COUNT(DISTINCT ss.id) as signals_today,
               COUNT(DISTINCT CASE WHEN ss.signal_grade = 'A+' THEN ss.id END) as aplus_today,
               COUNT(DISTINCT CASE WHEN ss.signal_grade IN ('A+','A') THEN ss.id END) as high_grade_today
        FROM strategy_registry sr
        LEFT JOIN strategy_signals ss ON ss.strategy_id = sr.strategy_id
            AND ss.fired_at > NOW() - INTERVAL '24 hours'
            AND ss.status = 'active'
        WHERE sr.strategy_id IS NOT NULL AND sr.active = true
        GROUP BY sr.strategy_id, sr.strategy_type, sr.display_name,
                 sr.status, sr.min_win_rate, sr.target_win_rate,
                 sr.total_signals, sr.trades_taken, sr.active,
                 sr.objective, sr.description, sr.timeframe,
                 sr.account_fit, sr.min_price, sr.max_price,
                 sr.max_float_m, sr.min_rvol, sr.risk_per_trade,
                 sr.scoring_profile
        ORDER BY
            CASE sr.status
                WHEN 'SCALING' THEN 0 WHEN 'VALIDATED' THEN 1
                WHEN 'TESTING' THEN 2 WHEN 'UNVALIDATED' THEN 3
                WHEN 'WATCHLIST' THEN 4 WHEN 'KILLING_REVIEW' THEN 5
                WHEN 'KILLED' THEN 6 ELSE 7
            END
    """) or []

    # 2. Performance summary (30d)
    perf_rows = db_query("""
        SELECT strategy_type,
               COUNT(*) as trade_count,
               COUNT(CASE WHEN verdict='CORRECT' THEN 1 END) as wins,
               ROUND(AVG(realized_pnl)::numeric, 2) as avg_pnl,
               ROUND(SUM(realized_pnl)::numeric, 2) as total_pnl
        FROM agent_recommendation_outcomes
        WHERE scored_at > NOW() - INTERVAL '30 days'
        AND verdict IN ('CORRECT', 'WRONG')
        GROUP BY strategy_type
    """) or []
    perf_by_strategy = {}
    for r in perf_rows:
        sid = r.get("strategy_type")
        tc = r.get("trade_count", 0) or 0
        w = r.get("wins", 0) or 0
        perf_by_strategy[sid] = {
            "trade_count": tc, "wins": w,
            "win_rate": round(w / tc, 3) if tc > 0 else None,
            "avg_pnl": _clean(r.get("avg_pnl")),
            "total_pnl": _clean(r.get("total_pnl")),
        }

    # 3. Recent lifecycle transitions
    transitions = db_query("""
        SELECT strategy_id, from_status, to_status, reason,
               triggered_by, created_at
        FROM strategy_state_transitions
        WHERE created_at > NOW() - INTERVAL '30 days'
        ORDER BY created_at DESC LIMIT 10
    """) or []

    # 4. Pattern library
    pattern_rows = db_query("""
        SELECT strategy_id, pattern_name, pattern_type,
               win_rate, trade_count, expectancy
        FROM pattern_library
        ORDER BY strategy_id, trade_count DESC
    """) or []
    patterns_by_strategy: dict[str, list[dict]] = {}
    for r in pattern_rows:
        sid = r.get("strategy_id")
        patterns_by_strategy.setdefault(sid, []).append(
            {k: _clean(v) for k, v in r.items() if k != "strategy_id"}
        )
    pattern_summary = {
        "proven": sum(1 for pp in patterns_by_strategy.values()
                      for p in pp if p.get("pattern_type") == "PROVEN"),
        "killed": sum(1 for pp in patterns_by_strategy.values()
                      for p in pp if p.get("pattern_type") == "KILLED"),
    }

    # 5. Today's signals (active/watch)
    all_signals = db_query("""
        SELECT ss.id, ss.strategy_id, ss.symbol,
               ss.signal_type, ss.signal_grade, ss.signal_score,
               ss.price, ss.rvol, ss.float_m, ss.gap_pct,
               ss.catalyst, ss.catalyst_verified,
               ss.entry_low, ss.entry_high,
               ss.stop_loss, ss.target_1, ss.target_2,
               ss.risk_reward, ss.shares, ss.dollar_risk,
               ss.vix_at_signal, ss.market_regime, ss.sector,
               ss.intel_readiness, ss.setup_description,
               ss.status, ss.fired_at
        FROM strategy_signals ss
        WHERE ss.fired_at > NOW() - INTERVAL '24 hours'
        AND ss.status IN ('active', 'watch')
        ORDER BY ss.strategy_id,
                 CASE ss.signal_grade WHEN 'A+' THEN 0 WHEN 'A' THEN 1
                     WHEN 'B' THEN 2 ELSE 3 END,
                 ss.signal_score DESC NULLS LAST
    """) or []

    signals_by_strategy: dict[str, list[dict]] = {}
    top_signals: list[dict] = []
    for r in all_signals:
        row = _clean_row(r)
        sid = row.get("strategy_id")
        signals_by_strategy.setdefault(sid, []).append(row)
        top_signals.append(row)

    now = datetime.now(timezone.utc)

    return {
        "computed_at": now.isoformat(),
        "strategies": [_clean_row(r) for r in strategies],
        "signals_by_strategy": signals_by_strategy,
        "top_signals": top_signals[:20],
        "performance_30d": {k: {kk: _clean(vv) for kk, vv in v.items()}
                            for k, v in perf_by_strategy.items()},
        "recent_transitions": [_clean_row(r) for r in transitions],
        "pattern_summary": pattern_summary,
        "patterns_by_strategy": patterns_by_strategy,
        "source": "DB: strategy_registry + strategy_signals + agent_recommendation_outcomes + "
                 "strategy_state_transitions + pattern_library",
    }


def get_strategy_desk(db_query, max_age_s: float = DEFAULT_MAX_AGE_S) -> dict[str, Any]:
    """Return cached strategy desk if fresh, else recompute from DB.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") — required.
        max_age_s: max age before recompute (default 60s).
    """
    cached = None
    if SNAPSHOT_PATH.exists() and max_age_s > 0:
        try:
            cached = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            age = time.time() - datetime.fromisoformat(cached["computed_at"]).timestamp()
            if age <= max_age_s:
                cached["_cache"] = {"hit": True, "age_seconds": round(age, 1)}
                return cached
        except Exception:
            cached = None

    if db_query is None:
        if cached:
            cached["_cache"] = {"hit": True, "age_seconds": 0, "stale": True}
            return cached
        return {"computed_at": "", "strategies": [], "signals_by_strategy": {},
                "top_signals": [], "performance_30d": {}, "recent_transitions": [],
                "pattern_summary": {}, "patterns_by_strategy": {}, "source": "unavailable"}

    fresh = _build(db_query)
    try:
        from lib.data_broker.atomic_json import atomic_write_json_soft
        atomic_write_json_soft(SNAPSHOT_PATH, fresh)
    except Exception:
        try:
            SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            SNAPSHOT_PATH.write_text(json.dumps(fresh, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass
    fresh["_cache"] = {"hit": False, "age_seconds": 0}
    return fresh


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from db_adapter import _execute as _db_q

    def db_query(sql, params=None, fetch="all"):
        from db_adapter import USE_DB
        if not USE_DB:
            return None
        return _db_q(sql, params, fetch=fetch)

    print(json.dumps(get_strategy_desk(db_query=db_query, max_age_s=0), indent=2, default=str))
