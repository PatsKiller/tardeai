# Source: scripts/trade_learning_engine.py (11911 bytes)
```python
#!/usr/bin/env python3
"""trade_learning_engine.py — Evaluate paper trade outcomes and strategy performance.

Generates learning hypotheses and recommendations. No active config changes.

Usage:
    .venv/bin/python scripts/trade_learning_engine.py --analyze --dry-run --json
    .venv/bin/python scripts/trade_learning_engine.py --strategy momentum_scalp --dry-run --json
"""
import argparse, json, os, sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def _get_conn():
    from session13_db import get_conn
    return get_conn()


def analyze_strategies(conn, strategy_filter=None, window_days=90):
    """Analyze strategy performance from paper trades.

    Separates true stop-out losses from relist/market-reconnection events.
    Relist events do not count as strategy failures — they contribute to
    patience scoring instead.
    """
    cur = conn.cursor()
    window_start = datetime.now(timezone.utc) - timedelta(days=window_days)

    # Strategy-level paper trade stats
    sql = """
        SELECT pt.strategy_id,
               COUNT(*) as total,
               COUNT(*) FILTER (WHERE pt.status='closed') as closed,
               COUNT(*) FILTER (WHERE pt.status='closed' AND pt.pnl > 0) as wins,
               COUNT(*) FILTER (WHERE pt.status='closed' AND pt.pnl <= 0) as losses,
               COALESCE(SUM(CASE WHEN pt.pnl > 0 THEN pt.pnl ELSE 0 END), 0) as gross_profit,
               COALESCE(SUM(CASE WHEN pt.pnl < 0 THEN ABS(pt.pnl) ELSE 0 END), 0) as gross_loss,
               AVG(pt.r_multiple) FILTER (WHERE pt.status='closed') as avg_r
        FROM paper_trades pt
        WHERE pt.created_at > %s
    """
    params = [window_start]
    if strategy_filter:
        sql += " AND pt.strategy_id = %s"
        params.append(strategy_filter)
    sql += " GROUP BY pt.strategy_id"
    cur.execute(sql, params)

    # ── Fetch relist context: symbols with active relists (not true stop-outs) ──
    relist_symbols = set()
    relist_patience = {}
    try:
        cur2 = conn.cursor()
        cur2.execute("""
            SELECT symbol, patience_score, relist_count
            FROM stopped_out_watch
            WHERE is_active = true
              AND explicit_stop_out = false
              AND (relisted_without_stop_out = true OR market_reconnection_event = true)
        """)
        for row in cur2.fetchall():
            relist_symbols.add(row[0])
            relist_patience[row[0]] = {"patience_score": _f(row[1]) or 0, "relist_count": row[2] or 0}
    except Exception:
        pass  # table may not have new columns yet

    strategies = []
    for r in cur.fetchall():
        strat_id = r[0] or "unknown"
        closed = r[2] or 0
        wins = r[3] or 0
        losses = r[4] or 0
        gp = _f(r[5]) or 0
        gl = _f(r[6]) or 0

        # ── Adjust losses: subtract relist-related losses ──
        # Query trades that closed at a loss on relist symbols
        relist_loss_count = 0
        try:
            cur3 = conn.cursor()
            relist_sym_list = list(relist_symbols)
            if relist_sym_list:
                cur3.execute("""
                    SELECT COUNT(*) FROM paper_trades pt
                    WHERE pt.strategy_id = %s AND pt.status = 'closed' AND pt.pnl <= 0
                      AND pt.created_at > %s AND pt.symbol = ANY(%s)
                """, [strat_id, window_start, relist_sym_list])
                relist_loss_count = cur3.fetchone()[0] or 0
```
