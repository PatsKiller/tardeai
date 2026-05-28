# Source: scripts/paper_execution_quality_analyzer.py (11040 bytes)
```python
#!/usr/bin/env python3
"""paper_execution_quality_analyzer.py — TCA: paper trade execution quality analysis.

Computes slippage, fill quality, and arrival-price analysis for paper trades.
Inserts results into paper_execution_quality table.

PAPER ONLY. No live trading.

Usage:
    .venv/bin/python scripts/paper_execution_quality_analyzer.py --recent --dry-run
    .venv/bin/python scripts/paper_execution_quality_analyzer.py --recent --apply
    .venv/bin/python scripts/paper_execution_quality_analyzer.py --paper-trade-id 123 --apply
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn
from local_llm_config import get_local_llm_model  # noqa: F401

log = logging.getLogger("execution_quality")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# Fill quality thresholds (absolute slippage %)
QUALITY_THRESHOLDS = [
    (0.05, "EXCELLENT"),
    (0.15, "GOOD"),
    (0.50, "ACCEPTABLE"),
]


def classify_fill_quality(slippage_pct):
    """Classify fill quality based on slippage percentage."""
    if slippage_pct is None:
        return "UNKNOWN"
    abs_slip = abs(slippage_pct)
    for threshold, label in QUALITY_THRESHOLDS:
        if abs_slip < threshold:
            return label
    return "POOR"


def get_recent_paper_trades(conn, days=7, paper_trade_id=None):
    """Fetch recent paper trades not yet analyzed for execution quality."""
    cur = conn.cursor()
    if paper_trade_id:
        cur.execute("""
            SELECT pt.id, pt.symbol, pt.strategy_id, pt.proposal_id,
                   pt.entry_price, pt.planned_entry, pt.entry_time,
                   pt.broker_order_id, pt.shares, pt.dollar_size,
                   pt.stop_loss, pt.target_1, pt.account
            FROM paper_trades pt
            WHERE pt.id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM paper_execution_quality peq
                  WHERE peq.paper_trade_id = pt.id
              )
        """, [paper_trade_id])
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cur.execute("""
            SELECT pt.id, pt.symbol, pt.strategy_id, pt.proposal_id,
                   pt.entry_price, pt.planned_entry, pt.entry_time,
                   pt.broker_order_id, pt.shares, pt.dollar_size,
                   pt.stop_loss, pt.target_1, pt.account
            FROM paper_trades pt
            WHERE pt.created_at >= %s
              AND NOT EXISTS (
                  SELECT 1 FROM paper_execution_quality peq
                  WHERE peq.paper_trade_id = pt.id
              )
            ORDER BY pt.created_at DESC
        """, [cutoff])

    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_evidence_snapshot(conn, proposal_id):
    """Get evidence snapshot for a proposal at submit time."""
    if not proposal_id:
        return None
    cur = conn.cursor()
    cur.execute("""
        SELECT quote_snapshot, execution_snapshot
        FROM proposal_evidence_snapshots
        WHERE proposal_id = %s
        ORDER BY created_at ASC
        LIMIT 1
    """, [proposal_id])
    row = cur.fetchone()
```
