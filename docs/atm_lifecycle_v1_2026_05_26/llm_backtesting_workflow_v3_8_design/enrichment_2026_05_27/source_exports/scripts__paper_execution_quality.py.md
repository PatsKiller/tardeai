# Source: scripts/paper_execution_quality.py (11763 bytes)
```python
#!/usr/bin/env python3
"""paper_execution_quality.py — TCA / execution quality analytics for paper trades.

Computes slippage, fill quality, spread, MAE/MFE, R multiples for entries/exits.
Writes to paper_execution_quality_events and paper_trade_outcome_analytics.

PAPER ONLY. No live trading.

Usage:
    .venv/bin/python scripts/paper_execution_quality.py --all-open --dry-run --json
    .venv/bin/python scripts/paper_execution_quality.py --trade-id 123 --apply --json
    .venv/bin/python scripts/paper_execution_quality.py --closed-since 48 --apply
"""
import argparse, json, logging, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from decimal import Decimal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn

log = logging.getLogger("paper_execution_quality")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

QUALITY_THRESHOLDS = [(5, "EXCELLENT"), (15, "GOOD"), (50, "FAIR")]  # in bps


def classify_grade(slippage_bps):
    if slippage_bps is None:
        return "UNKNOWN"
    a = abs(slippage_bps)
    for thresh, label in QUALITY_THRESHOLDS:
        if a < thresh:
            return label
    return "POOR"


def _f(v):
    """Convert Decimal to float safely."""
    if isinstance(v, Decimal):
        return float(v)
    return v


def get_trades(conn, trade_id=None, all_open=False, closed_since_hours=None, symbol=None):
    cur = conn.cursor()
    conditions = ["account = 'ALPACA_PAPER'"]
    params = []
    if trade_id:
        conditions.append("id = %s")
        params.append(trade_id)
    elif all_open:
        conditions.append("status = 'open'")
    elif closed_since_hours:
        conditions.append("status = 'closed'")
        conditions.append("closed_at >= NOW() - INTERVAL '%s hours'" % int(closed_since_hours))
    else:
        conditions.append("status IN ('open', 'closed')")
        conditions.append("created_at >= NOW() - INTERVAL '30 days'")

    if symbol:
        conditions.append("symbol = %s")
        params.append(symbol)

    sql = f"""SELECT id, symbol, strategy_id, entry_price, exit_price, shares,
                     stop_loss, target_1, status, broker_order_id, broker_filled_at,
                     broker_closed_at, entry_time, exit_time, planned_entry,
                     current_price, unrealized_pnl, pnl, pnl_pct, hold_time_min,
                     r_multiple, dollar_risk, exit_reason
              FROM paper_trades WHERE {' AND '.join(conditions)}
              ORDER BY created_at DESC"""
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def compute_tca(trade):
    """Compute TCA metrics for a single trade."""
    events = []
    entry = _f(trade.get("entry_price"))
    planned = _f(trade.get("planned_entry"))
    exit_p = _f(trade.get("exit_price"))
    stop = _f(trade.get("stop_loss"))
    target = _f(trade.get("target_1"))
    shares = _f(trade.get("shares")) or 0
    status = trade.get("status", "")

    # Entry fill quality
    if entry and planned and planned > 0:
        slip_abs = entry - planned
        slip_bps = (slip_abs / planned) * 10000
        events.append({
            "paper_trade_id": trade["id"], "symbol": trade["symbol"],
            "event_type": "entry_fill", "broker_order_id": trade.get("broker_order_id"),
            "expected_price": planned, "actual_price": entry,
```
