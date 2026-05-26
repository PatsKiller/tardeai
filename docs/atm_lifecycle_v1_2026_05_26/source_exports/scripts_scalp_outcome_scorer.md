# Source Export: scripts/scalp_outcome_scorer.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/scalp_outcome_scorer.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `0bf8b01076e8556f8965759dd253a5635447ce7a2c86d5139903ccb246296a90` |
| **File Size** | 4450 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""Score yesterday's scalp alerts against actual price moves. Runs 5 PM weekdays."""
import json, logging, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [scalp_outcomes] %(message)s")
logger = logging.getLogger(__name__)


def _get_conn():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def _fetch_current_price(symbol, conn):
    """Get latest price from market_quotes table."""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT price FROM market_quotes WHERE symbol=%s ORDER BY fetched_at DESC LIMIT 1",
        (symbol,),
    )
    row = cur.fetchone()
    return float(row["price"]) if row else None


def score_alerts(conn):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    # Get alerted scans from 6-36 hours ago that haven't been scored yet
    cur.execute("""
        SELECT s.id, s.symbol, s.grade, s.score, s.scanned_at, s.price as alert_price,
               s.rvol, s.gap_pct
        FROM scalp_scan_results s
        WHERE s.alerted = true
          AND s.scanned_at > NOW() - INTERVAL '36 hours'
          AND s.scanned_at < NOW() - INTERVAL '6 hours'
          AND NOT EXISTS (SELECT 1 FROM scalp_decision_outcomes o WHERE o.scan_id = s.id)
        ORDER BY s.scanned_at DESC
    """)
    alerts = cur.fetchall()
    logger.info(f"Scoring {len(alerts)} unscored alerts")

    scored = 0
    for alert in alerts:
        try:
            current_price = _fetch_current_price(alert["symbol"], conn)
            if not current_price:
                logger.debug(f"No price for {alert['symbol']}, skipping")
                continue
            alert_price = float(alert["alert_price"] or 0)
            if alert_price <= 0:
                continue

            pct_move = (current_price - alert_price) / alert_price * 100

            if pct_move >= 8:
                status = "profit_8pct"
            elif pct_move >= 3:
                status = "profit_3pct"
            elif pct_move <= -10:
                status = "loss_10pct"
            elif pct_move <= -5:
                status = "loss_5pct"
            else:
                status = "flat"

            wcur = conn.cursor()
            wcur.execute("""
                INSERT INTO scalp_decision_outcomes
                    (scan_id, symbol, grade, score, alert_at, alert_price, eod_price,
                     pct_move_24h, outcome_status, rvol_at_alert)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, [alert["id"], alert["symbol"], alert["grade"], alert["score"],
                  alert["scanned_at"], alert_price, current_price,
                  round(pct_move, 2), status, alert.get("rvol")])
            scored += 1
        except Exception as e:
            logger.warning(f"Failed to score {alert['symbol']}: {e}")

    conn.commit()
    logger.info(f"Scored {scored}/{len(alerts)} alerts")

    # Send summary via Telegram if any scored
    if scored > 0:
        try:
            from telegram_alert import send_telegram
            cur2 = conn.cursor(cursor_factory=RealDictCursor)
            cur2.execute("""
                SELECT count(*) as total,
                       count(*) FILTER (WHERE outcome_status LIKE 'profit%%') as wins,
                       count(*) FILTER (WHERE outcome_status LIKE 'loss%%') as losses,
                       count(*) FILTER (WHERE outcome_status = 'flat') as flat
                FROM scalp_decision_outcomes
                WHERE scored_at > NOW() - INTERVAL '24 hours'
            """)
            s = cur2.fetchone()
            msg = (f"\U0001f4ca *Scalp scorecard:* {s['total']} alerts scored\n"
                   f"  Wins: {s['wins']} | Flat: {s['flat']} | Losses: {s['losses']}")
            send_telegram(msg)
        except Exception as e:
            logger.warning(f"Telegram notify failed: {e}")

    return scored


if __name__ == "__main__":
    conn = _get_conn()
    score_alerts(conn)
    conn.close()
```
