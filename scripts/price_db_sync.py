#!/usr/bin/env python3
"""price_db_sync.py — Persist daily prices to PostgreSQL ticker_prices table.

Called after repricing in the daily pipeline. Reads current prices from:
1. finviz_quote_cache.json (Schwab tickers)
2. holdings.json (Fidelity current prices)
3. price_cache.json (Yahoo historical — only new dates)

Writes to: ticker_prices (symbol, price_date, close_price, source)
Dedupes via UPSERT (ON CONFLICT DO UPDATE).

Also provides get_price_from_db() for the backfill script to use DB as source of truth.
"""
import json, os, sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _get_conn():
    import psycopg2
    pw = os.environ.get("DB_PASSWORD", "")
    if not pw:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("DB_PASSWORD="):
                    pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def sync_daily_prices():
    """Persist today's prices from finviz cache + holdings to DB."""
    conn = _get_conn()
    cur = conn.cursor()
    today = date.today().isoformat()
    written = 0

    # 1. Finviz quote cache (most accurate for Schwab tickers)
    fq_path = STATE_DIR / "finviz_quote_cache.json"
    if fq_path.exists():
        fq = json.loads(fq_path.read_text())
        for sym, data in fq.items():
            if sym.startswith("_") or not isinstance(data, dict):
                continue
            price = data.get("price")
            if isinstance(price, (int, float)) and price > 0:
                cur.execute("""
                    INSERT INTO ticker_prices (symbol, price_date, close_price, source)
                    VALUES (%s, %s, %s, 'finviz')
                    ON CONFLICT (symbol, price_date) DO UPDATE SET close_price = EXCLUDED.close_price, source = 'finviz'
                """, (sym, today, round(float(price), 4)))
                written += 1

    # 2. Holdings (catches Fidelity + any symbols missed by Finviz)
    h_path = STATE_DIR / "holdings.json"
    if h_path.exists():
        h = json.loads(h_path.read_text())
        for holding in h.get("holdings", []):
            sym = holding.get("symbol", "")
            price = holding.get("price", 0)
            if sym and price and price > 0 and sym not in ("CASH", "MMKT"):
                cur.execute("""
                    INSERT INTO ticker_prices (symbol, price_date, close_price, source)
                    VALUES (%s, %s, %s, 'holdings')
                    ON CONFLICT (symbol, price_date) DO NOTHING
                """, (sym, today, round(float(price), 4)))
                written += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"  [price-db] Synced {written} prices to DB for {today}")
    return written


def get_price_from_db(symbol: str, date_str: str, fidelity_map: dict = None) -> float | None:
    """Get price from DB, with Fidelity mapping support.

    This is the canonical price lookup — use this instead of JSON cache.
    Falls back to nearest date within 5 days.
    """
    mapped = symbol
    if fidelity_map and symbol in fidelity_map:
        mapped = fidelity_map[symbol]

    conn = _get_conn()
    cur = conn.cursor()

    # Exact date
    cur.execute("SELECT close_price FROM ticker_prices WHERE symbol=%s AND price_date=%s", (mapped, date_str))
    row = cur.fetchone()
    if row:
        cur.close(); conn.close()
        return float(row[0])

    # Nearest within 5 days
    cur.execute("""
        SELECT close_price, price_date FROM ticker_prices
        WHERE symbol=%s AND price_date BETWEEN %s::date - 5 AND %s::date + 5
        ORDER BY ABS(price_date - %s::date) LIMIT 1
    """, (mapped, date_str, date_str, date_str))
    row = cur.fetchone()
    cur.close(); conn.close()
    return float(row[0]) if row else None


def get_latest_price_from_db(symbol: str) -> float | None:
    """Get most recent price for a symbol from DB."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT close_price FROM ticker_prices WHERE symbol=%s ORDER BY price_date DESC LIMIT 1", (symbol,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return float(row[0]) if row else None


if __name__ == "__main__":
    sync_daily_prices()
