#!/usr/bin/env python3
"""record_decision_outcome.py — Record and backfill decision outcomes.

Links synthesis recommendations to actual price outcomes for learning.

Usage:
    python3 scripts/record_decision_outcome.py --backfill [--json]
"""
import json, os, sys
from datetime import datetime, date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def record_current_decisions(real_only: bool = True) -> int:
    """Record all current actionable synthesis decisions for real outcome tracking."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Find syntheses without outcome records
    cur.execute("""
        SELECT fs.symbol, fs.recommendation, fs.confidence, fs.updated_at,
               tsc.strategy_type,
               sc.latest_price
        FROM watchlist_final_synthesis fs
        LEFT JOIN ticker_strategy_classifications tsc ON tsc.symbol = fs.symbol
        LEFT JOIN watchlist_strategy_cards sc ON sc.symbol = fs.symbol
        WHERE fs.superseded IS NOT TRUE
        AND NOT EXISTS (SELECT 1 FROM decision_outcomes dout WHERE dout.symbol = fs.symbol AND dout.created_at > fs.updated_at - INTERVAL '1 day')
    """)
    decisions = cur.fetchall()

    recorded = 0
    for d in decisions:
        cur.execute("""
            INSERT INTO decision_outcomes
                (symbol, strategy_type, recommendation, price_at_decision, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (d["symbol"], d.get("strategy_type"), d["recommendation"],
              float(d["latest_price"]) if d.get("latest_price") else None,
              d["updated_at"]))
        recorded += 1

    conn.commit()
    conn.close()
    print(f"[outcomes] Recorded {recorded} new decision outcomes")
    return recorded


def backfill_prices(days: int = 30) -> int:
    """Backfill price outcomes for existing decision records."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT dout.id, dout.symbol, dout.created_at, dout.price_at_decision
        FROM decision_outcomes dout
        WHERE dout.evaluated_at IS NULL AND dout.price_at_decision IS NOT NULL
        AND dout.created_at < NOW() - INTERVAL '1 day'
        LIMIT 100
    """)
    outcomes = cur.fetchall()

    updated = 0
    for o in outcomes:
        sym = o["symbol"]
        decision_date = o["created_at"].date() if hasattr(o["created_at"], "date") else o["created_at"]

        # Try to get prices at +1d, +7d, +30d from ticker_prices
        prices = {}
        for label, delta in [("1d", 1), ("7d", 7), ("30d", 30)]:
            target_date = decision_date + timedelta(days=delta)
            cur.execute("""
                SELECT close_price FROM ticker_prices
                WHERE symbol=%s AND price_date BETWEEN %s AND %s
                ORDER BY ABS(price_date - %s::date) LIMIT 1
            """, (sym, target_date - timedelta(days=3), target_date + timedelta(days=3), target_date))
            r = cur.fetchone()
            if r:
                prices[label] = float(r["close_price"])

        if prices:
            p_at = float(o["price_at_decision"] or 0)
            p_1d = prices.get("1d")
            p_7d = prices.get("7d")
            p_30d = prices.get("30d")

            # Compute simple outcome score: did price go in recommended direction?
            outcome_score = None
            if p_7d and p_at > 0:
                change_pct = (p_7d - p_at) / p_at * 100
                # Positive score if BUY/ADD and price went up, or SELL/TRIM and price went down
                outcome_score = change_pct  # Simple: positive = good for BUY, bad for SELL

            cur.execute("""
                UPDATE decision_outcomes
                SET price_1d = %s, price_7d = %s, price_30d = %s,
                    outcome_score = %s, evaluated_at = NOW()
                WHERE id = %s
            """, (p_1d, p_7d, p_30d, outcome_score, o["id"]))
            updated += 1

    conn.commit()
    conn.close()
    print(f"[outcomes] Backfilled {updated} price outcomes")
    return updated


if __name__ == "__main__":
    recorded = record_current_decisions()
    if "--backfill" in sys.argv:
        backfill_prices()
    if "--json" in sys.argv:
        print(json.dumps({"recorded": recorded}, indent=2))
