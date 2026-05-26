#!/usr/bin/env python3
"""
atm_classifier_health.py — Per-strategy health scoring for ATM gate decisions.

Returns 0.0 (blocks strategy) if insufficient data exists.
No hardcoded broker or account names.
"""
import os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def get_health_detail(strategy_id: str, lookback_days: int = 30) -> dict:
    """
    Compute classifier health score for a strategy based on closed trade outcomes.

    Score = 0.4 * win_rate + 0.3 * sample_factor + 0.3 * r_factor
    Returns score 0.0 if fewer than 3 closed trades (insufficient data).
    Also returns closed_trades count and has_baseline flag.
    """
    from db_adapter import get_connection
    conn = get_connection()
    if not conn:
        return {"score": 0.0, "closed_trades": 0, "has_baseline": False, "wins": 0, "avg_r": 0.0}

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) as n,
                COUNT(*) FILTER (WHERE pnl > 0) as wins,
                COALESCE(AVG(r_multiple) FILTER (WHERE r_multiple IS NOT NULL), 0) as avg_r
            FROM paper_trades
            WHERE strategy_id = %s
              AND status = 'closed'
              AND closed_at > NOW() - INTERVAL '%s days'
        """.replace("%s days", f"{int(lookback_days)} days"), (strategy_id,))
        row = cur.fetchone()
        if not row:
            return {"score": 0.0, "closed_trades": 0, "has_baseline": False, "wins": 0, "avg_r": 0.0}

        n, wins, avg_r = int(row[0] or 0), int(row[1] or 0), float(row[2] or 0)

        if n < 3:
            return {"score": 0.0, "closed_trades": n, "has_baseline": False, "wins": wins, "avg_r": round(avg_r, 3)}

        win_rate = wins / n
        sample_factor = min(1.0, n / 10.0)
        r_factor = min(1.0, max(0.0, (avg_r + 1.0) / 2.0))  # maps -1..1 to 0..1
        score = round(0.4 * win_rate + 0.3 * sample_factor + 0.3 * r_factor, 3)

        return {"score": score, "closed_trades": n, "has_baseline": True, "wins": wins, "avg_r": round(avg_r, 3)}
    except Exception:
        return {"score": 0.0, "closed_trades": 0, "has_baseline": False, "wins": 0, "avg_r": 0.0}


def get_health(strategy_id: str, lookback_days: int = 30) -> float:
    """Backwards-compatible wrapper — returns just the score."""
    return get_health_detail(strategy_id, lookback_days)["score"]
