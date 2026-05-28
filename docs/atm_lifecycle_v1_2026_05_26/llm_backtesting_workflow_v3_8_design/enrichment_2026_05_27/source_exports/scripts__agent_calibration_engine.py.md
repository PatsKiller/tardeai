# Source: scripts/agent_calibration_engine.py (15339 bytes)
```python
#!/usr/bin/env python3
"""agent_calibration_engine.py — Score agent recommendations against outcomes.

Generates calibration events, windows, learning evidence and recommendations.
No active config changes. Dry-run safe.

Usage:
    .venv/bin/python scripts/agent_calibration_engine.py --dry-run --json
    .venv/bin/python scripts/agent_calibration_engine.py --apply --json
    .venv/bin/python scripts/agent_calibration_engine.py --agent Maria --dry-run --json
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def _f(v): return float(v) if isinstance(v, Decimal) else v
def _uid(prefix="ACE_"): return f"{prefix}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

AGENT_SAMPLE_INSIGHT = 25
AGENT_SAMPLE_SHADOW = 100

def _get_conn():
    from session13_db import get_conn
    return get_conn()


def score_recommendations(conn, agent_filter=None, window_days=90):
    """Score linked recommendations against outcomes."""
    cur = conn.cursor()
    sql = """
        SELECT r.recommendation_id, r.agent_name, r.symbol, r.strategy_id,
               r.recommendation_type, r.confidence, r.recommendation_time,
               l.outcome_type, l.paper_trade_id, l.proposal_id, l.link_confidence
        FROM agent_recommendation_registry r
        JOIN agent_recommendation_outcome_links l ON r.recommendation_id = l.recommendation_id
        WHERE r.recommendation_time > now() - interval '%s days'
    """ % window_days
    params = []
    if agent_filter:
        sql += " AND r.agent_name ILIKE %s"
        params.append(f"%{agent_filter}%")
    sql += " ORDER BY r.recommendation_time DESC LIMIT 2000"
    cur.execute(sql, params)

    events = []
    for row in cur.fetchall():
        rec_id, agent, symbol, strat, rec_type, conf, rec_time = row[:7]
        outcome_type, trade_id, proposal_id, link_conf = row[7:]

        actual = "unresolved"
        outcome_score = 0
        pnl = None
        r_mult = None
        explanation = "no_outcome_data"

        # ── Check if this symbol is a relist (no true stop-out) ──
        is_relist = False
        try:
            cur.execute("""
                SELECT 1 FROM stopped_out_watch
                WHERE symbol = %s AND is_active = true
                  AND explicit_stop_out = false
                  AND (relisted_without_stop_out = true OR market_reconnection_event = true)
                LIMIT 1
            """, [symbol])
            is_relist = cur.fetchone() is not None
        except Exception:
            pass  # table may not have new columns yet

        # Check paper trade outcome
        if trade_id:
            cur.execute("SELECT status, pnl, r_multiple FROM paper_trades WHERE id=%s", [trade_id])
            trade = cur.fetchone()
            if trade:
                status, t_pnl, t_r = trade
                pnl = _f(t_pnl)
                r_mult = _f(t_r)
                if status == "closed":
                    if rec_type in ("buy", "add", "approve_trade"):
                        if (pnl or 0) > 0:
                            actual = "correct"
                            outcome_score = 1
                        elif is_relist:
                            # Relist: loss is market noise, not recommendation failure
                            actual = "relist_neutral"
                            outcome_score = 0
                        else:
                            actual = "incorrect"
                            outcome_score = -1
                        explanation = f"trade closed pnl={pnl}" + (" [relist]" if is_relist else "")
                    elif rec_type in ("sell", "trim", "avoid", "reject_trade"):
                        if (pnl or 0) <= 0:
                            actual = "correct"
                            outcome_score = 1
```
