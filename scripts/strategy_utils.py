#!/usr/bin/env python3
"""strategy_utils.py — strategy performance gate for proposal generation (operator 2026-06-19, Task 4).

`is_strategy_promotable()` is a READ-ONLY gate: a strategy with a real losing record (>=10 closed paper
trades at <25% win rate) stops generating new proposals until its edge recovers; below 5 closed trades
it's always eligible (insufficient data). Adapted to the real paper_trades schema (status='closed',
pnl>0 for a win). Currently DORMANT — no strategy meets the gate. Never modifies any trade/proposal row.
"""
from __future__ import annotations
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

STRATEGY_GATE_MIN_TRADES = 5     # below this: always eligible (no data)
STRATEGY_GATE_MIN_WR = 0.25      # floor win rate once enough trades
STRATEGY_GATE_MIN_WR_N = 10      # min closed trades before the WR gate activates

_DDL = """
CREATE TABLE IF NOT EXISTS proposal_suppression_log (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  suppression_reason TEXT NOT NULL,
  suppressed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_suppression_log_strategy ON proposal_suppression_log(strategy_id, suppressed_at DESC);
"""


def ensure_table(conn) -> None:
    try:
        cur = conn.cursor(); cur.execute(_DDL); conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def is_strategy_promotable(strategy_id: str, conn) -> tuple[bool, str]:
    """Return (eligible, reason). Read-only. <5 closed → INSUFFICIENT_DATA (eligible); >=10 closed at
    <25% WR → blocked (WIN_RATE_BELOW_GATE); else ELIGIBLE. Fail-open on any error."""
    if not strategy_id:
        return True, "NO_STRATEGY"
    try:
        cur = conn.cursor()
        cur.execute("""SELECT count(*) FILTER (WHERE status='closed' AND pnl IS NOT NULL) AS closed,
                              count(*) FILTER (WHERE status='closed' AND pnl > 0) AS wins
                         FROM paper_trades WHERE strategy_id = %s""", (strategy_id,))
        row = cur.fetchone()
        closed = (row[0] or 0) if row else 0
        wins = (row[1] or 0) if row else 0
        if closed < STRATEGY_GATE_MIN_TRADES:
            return True, "INSUFFICIENT_DATA"
        wr = wins / closed
        if closed >= STRATEGY_GATE_MIN_WR_N and wr < STRATEGY_GATE_MIN_WR:
            return False, (f"WIN_RATE_BELOW_GATE ({wr:.0%} over {closed} closed; "
                           f"gate requires {STRATEGY_GATE_MIN_WR:.0%} at >={STRATEGY_GATE_MIN_WR_N})")
        return True, "ELIGIBLE"
    except Exception as e:
        logging.warning(f"is_strategy_promotable({strategy_id}) error: {e} — fail-open ELIGIBLE")
        try:
            conn.rollback()
        except Exception:
            pass
        return True, f"ERROR_FALLBACK:{str(e)[:60]}"


def log_suppression(conn, symbol: str, strategy_id: str, reason: str) -> None:
    try:
        ensure_table(conn)
        cur = conn.cursor()
        cur.execute("""INSERT INTO proposal_suppression_log (symbol, strategy_id, suppression_reason)
                       VALUES (%s,%s,%s)""", (symbol, strategy_id, reason))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


if __name__ == "__main__":
    from db_adapter import _get_conn
    conn = _get_conn(); ensure_table(conn); cur = conn.cursor()
    cur.execute("SELECT DISTINCT strategy_id FROM paper_trades WHERE strategy_id IS NOT NULL")
    for (sid,) in cur.fetchall():
        ok, reason = is_strategy_promotable(sid, conn)
        if reason != "INSUFFICIENT_DATA":
            print(f"  {sid:28} eligible={ok}  {reason}")
    print("(strategies not shown are INSUFFICIENT_DATA — gate dormant)")
