# Source: scripts/feedback_loop_processor.py (16916 bytes)
```python
#!/usr/bin/env python3
"""feedback_loop_processor.py — Close feedback loops across the system.

Runs daily. Connects:
  1. Proposals → paper trades → P&L outcomes → agent calibration
  2. CIO decisions → alert effectiveness scoring
  3. Strategy performance snapshots (weekly)
  4. Agent sample size tracking
  5. Recovery watch outcome detection

Usage:
    .venv/bin/python scripts/feedback_loop_processor.py
    .venv/bin/python scripts/feedback_loop_processor.py --dry-run
"""
import argparse
import json
import os
import sys
from datetime import datetime, date, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def _get_conn():
    import psycopg2
    pw = os.getenv("DB_PASSWORD", "")
    return psycopg2.connect(host="127.0.0.1", port=5432,
                            dbname="trade_ai", user="trade_ai", password=pw)


# ── 1. Proposal → Trade → Outcome Chain ─────────────────────────────────

def link_proposal_outcomes(conn, dry_run=False):
    """Find proposals that have been linked to paper trades and track outcomes."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Find proposals not yet in the chain
    cur.execute("""
        SELECT p.id, p.symbol, p.strategy_id, p.status, p.proposed_by, p.created_at
        FROM paper_trade_proposals p
        WHERE NOT EXISTS (
            SELECT 1 FROM proposal_outcome_chain poc WHERE poc.proposal_id = p.id
        )
        AND p.status IN ('APPROVED', 'APPROVED_FOR_PAPER_TEST', 'REJECTED', 'EXPIRED', 'expired')
        ORDER BY p.created_at DESC LIMIT 100
    """)
    proposals = cur.fetchall()

    linked = 0
    for p in proposals:
        # Try to find a matching paper trade
        cur.execute("""
            SELECT id, status, pnl, r_multiple
            FROM paper_trades
            WHERE symbol = %s AND strategy_id = %s
            AND created_at >= %s
            ORDER BY created_at ASC LIMIT 1
        """, (p["symbol"], p["strategy_id"], p["created_at"]))
        trade = cur.fetchone()

        chain_status = "pending"
        trade_id = None
        trade_pnl = None
        trade_r = None
        trade_status = None

        if trade:
            trade_id = trade["id"]
            trade_status = trade["status"]
            trade_pnl = _f(trade.get("pnl"))
            trade_r = _f(trade.get("r_multiple"))
            if trade_status == "closed":
                chain_status = "closed"
            else:
                chain_status = "linked"
        elif p["status"] in ("REJECTED", "EXPIRED", "expired"):
            chain_status = "orphaned"

        if not dry_run:
            cur.execute("""
                INSERT INTO proposal_outcome_chain
                    (proposal_id, symbol, strategy_id, proposing_agent,
                     proposal_created, proposal_status, paper_trade_id,
                     trade_status, trade_pnl, trade_r_multiple, chain_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (proposal_id) DO UPDATE SET
                    trade_status = EXCLUDED.trade_status,
                    trade_pnl = EXCLUDED.trade_pnl,
                    trade_r_multiple = EXCLUDED.trade_r_multiple,
```
