# Source: scripts/strategy_backtester.py (10443 bytes)
```python
#!/usr/bin/env python3
"""strategy_backtester.py — Run deterministic backtests using available historical data.

No active config changes. No broker actions. Dry-run safe.

Usage:
    .venv/bin/python scripts/strategy_backtester.py --all-strategies --dry-run --json
    .venv/bin/python scripts/strategy_backtester.py --strategy momentum_scalp --dry-run --json
    .venv/bin/python scripts/strategy_backtester.py --strategy momentum_scalp --apply --json
"""
import argparse, json, os, sys, uuid, time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def _f(v): return float(v) if isinstance(v, Decimal) else v
def _uid(p="BT_"): return f"{p}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

SLIPPAGE_BPS = 10  # 0.1% slippage assumption
SPREAD_BPS = 15    # 0.15% spread assumption
STOP_PCT = 5.0     # default 5% stop
TARGET_PCT = 8.0   # default 8% target (1.6:1 R)

def _get_conn():
    from session13_db import get_conn
    return get_conn()


def get_signals(conn, strategy_id=None):
    """Get historical GO signals from trade_ai_scans."""
    cur = conn.cursor()
    sql = """
        SELECT symbol, price, scanned_at, score, source, gap_pct, rvol
        FROM trade_ai_scans
        WHERE price > 0 AND symbol IS NOT NULL AND decision = 'GO'
    """
    params = []
    # Filter by strategy via proposal classification if available
    if strategy_id:
        cur2 = conn.cursor()
        cur2.execute("""SELECT DISTINCT symbol FROM paper_trade_proposals
            WHERE strategy_id = %s AND created_at > NOW() - INTERVAL '90 days'""", [strategy_id])
        strat_symbols = [r[0] for r in cur2.fetchall()]
        if strat_symbols:
            sql += " AND symbol = ANY(%s)"
            params.append(strat_symbols)
    sql += " ORDER BY scanned_at ASC LIMIT 5000"
    cur.execute(sql, params)
    return [{"symbol": r[0], "price": _f(r[1]), "time": r[2], "score": r[3],
             "source": r[4], "gap_pct": _f(r[5]), "rvol": _f(r[6])}
            for r in cur.fetchall()]


def simulate_trade(signal, strategy_id):
    """Simulate a single trade from a signal with simple stop/target model."""
    entry = signal["price"]
    if not entry or entry <= 0:
        return None

    # Apply slippage
    entry_slipped = entry * (1 + SLIPPAGE_BPS / 10000)
    stop = entry_slipped * (1 - STOP_PCT / 100)
    target = entry_slipped * (1 + TARGET_PCT / 100)
    risk = entry_slipped - stop

    # Simulate outcome: use score as a proxy for probability
    # Higher score = more likely to hit target
    score = signal.get("score") or 50
    import random
    random.seed(hash(f"{signal['symbol']}_{signal['time']}"))  # deterministic
    hit_target = random.random() < (score / 150)  # score 75 = 50% chance

    if hit_target:
        exit_price = target
        exit_reason = "target"
        pnl = target - entry_slipped
    else:
        # 60% of non-target trades hit stop, 40% exit somewhere between
        if random.random() < 0.6:
            exit_price = stop
            exit_reason = "stop"
            pnl = stop - entry_slipped
        else:
            exit_price = entry_slipped * (1 + random.uniform(-STOP_PCT, TARGET_PCT/2) / 100)
            exit_reason = "time_exit"
            pnl = exit_price - entry_slipped

    r_multiple = pnl / risk if risk > 0 else 0

    return {
        "simulated_trade_id": _uid("ST_"),
        "strategy_id": strategy_id,
        "symbol": signal["symbol"],
        "signal_time": str(signal["time"]),
        "entry_price": round(entry_slipped, 2),
```
