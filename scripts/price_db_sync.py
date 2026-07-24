#!/usr/bin/env python3
"""price_db_sync.py — Persist daily prices to PostgreSQL ticker_prices table.

Called after repricing in the daily pipeline. Reads current prices from:
1. finviz_quote_cache.json (Schwab tickers)
2. holdings.json (Fidelity current prices)
3. market_quotes (watchlist + proposal symbols — via ensure_price_history)
4. yfinance gap-fill for symbols still short on close history

Writes to: ticker_prices (symbol, price_date, close_price, source)
Dedupes via UPSERT (ON CONFLICT DO UPDATE).

Consumers: watchlist strategy cards, agent synthesis, paper/broker proposals
(support/resistance, backtest, broker curator), portfolio backfill scripts.
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


PROPOSAL_ACTIVE_STATUSES = (
    "PENDING", "APPROVED_FOR_PAPER_TEST", "PROPOSED", "MODIFIED",
    "BROKER_SUBMITTED", "APPROVED",
)


def active_proposal_symbols(*, statuses: tuple[str, ...] | None = None) -> list[str]:
    """Distinct equity tickers on active paper/broker proposal queue."""
    conn = _get_conn()
    cur = conn.cursor()
    st = list(statuses or PROPOSAL_ACTIVE_STATUSES)
    cur.execute(
        """SELECT DISTINCT UPPER(symbol) FROM paper_trade_proposals
           WHERE status = ANY(%s)
             AND symbol IS NOT NULL AND symbol <> ''
             AND symbol ~ '^[A-Z]{1,5}$'
           ORDER BY 1""",
        (st,),
    )
    syms = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return syms


REENTRY_EXIT_CACHE_KEY = "portfolio.reentry.exit-universe.v1"
PRICE_STALE_AFTER_DAYS = 5


def reentry_exit_symbols() -> list[str]:
    """Distinct equity tickers from the Re-Entry exit universe.

    The Re-Entry desk reasons entirely about *exited* positions, but the daily scope
    is built from held, ranked, and actively-proposed symbols only. An exited ticker
    therefore ages out of the price universe and its Re-Entry row goes blank — which
    is exactly the coverage the page needs. Schwab reports a 9-char CUSIP in place of
    a ticker only when the security is delisted, so the same `^[A-Z]{1,5}$` guard the
    sibling scope queries use also drops those permanently un-fetchable rows.
    """
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM ui_prefs WHERE key = %s", (REENTRY_EXIT_CACHE_KEY,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    payload = row[0] if row else None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = None
    if not isinstance(payload, dict):
        return []
    out = []
    for entry in payload.get("rows") or []:
        sym = str((entry or {}).get("symbol") or "").upper().strip()
        if sym and sym.isalpha() and 1 <= len(sym) <= 5:
            out.append(sym)
    return sorted(dict.fromkeys(out))


def price_backfill_candidates(
    symbols: list[str],
    *,
    min_rows: int = 60,
    max_age_days: int = PRICE_STALE_AFTER_DAYS,
) -> list[str]:
    """Symbols needing a yfinance fill: too little history OR a stale newest close.

    Row count alone cannot detect staleness. A symbol that stopped updating months ago
    still carries ~180 rows — far above min_rows — so it never qualified for backfill
    and silently froze. Batched into one query because the daily scope is now several
    hundred symbols and the old path opened a connection per symbol.
    """
    syms = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    syms = list(dict.fromkeys(syms))
    if not syms:
        return []
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT s.sym
           FROM unnest(%s::text[]) AS s(sym)
           LEFT JOIN (
               SELECT UPPER(symbol) AS sym, COUNT(*) AS n, MAX(price_date) AS last_date
               FROM ticker_prices GROUP BY 1
           ) tp ON tp.sym = s.sym
           WHERE tp.sym IS NULL
              OR tp.n < %s
              OR tp.last_date < CURRENT_DATE - %s""",
        (syms, int(min_rows), int(max_age_days)),
    )
    out = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return out


def _hermes_top_symbols(top: int = 250) -> list[str]:
    """Distinct watchlist tickers in the Hermes top-N window."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT symbol FROM watchlist_items
           WHERE status IN ('active','researched')
             AND hermes_rank IS NOT NULL AND hermes_rank <= %s
             AND symbol ~ '^[A-Z]{1,5}$'
           ORDER BY symbol""",
        (int(top),),
    )
    syms = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return syms


def ensure_price_history(
    symbols: list[str] | None = None,
    *,
    min_rows: int = 60,
    yfinance_cap: int | None = None,
) -> dict:
    """Sync market_quotes → ticker_prices and yfinance-gap-fill symbols still short on history.

    Used by watchlist refresh, proposal enrichment, and broker/paper proposal refresh endpoints.
    """
    syms = [str(s).upper().strip() for s in (symbols or []) if s and str(s).strip()]
    syms = list(dict.fromkeys(syms))
    n_quotes = sync_quotes_to_ticker_prices(syms if syms else None)
    short = [s for s in syms if count_price_rows(s) < min_rows] if syms else []
    cap = yfinance_cap if yfinance_cap is not None else (len(short) if len(short) <= 50 else 40)
    yf_result = {"filled": 0}
    if short and cap > 0:
        yf_result = backfill_yfinance_history(short[:cap])
    return {
        "symbols": len(syms),
        "quotes_synced": n_quotes,
        "short_candidates": len(short),
        "yfinance": yf_result,
    }


# Back-compat alias
sync_watchlist_prices = ensure_price_history


def sync_daily_watchlist_prices(*, yfinance_cap: int = 80, min_rows: int = 60) -> dict:
    """Keep watchlist, active proposal, and Re-Entry exit ticker_prices current (daily cron)."""
    n_quotes = sync_quotes_to_ticker_prices()
    exits = reentry_exit_symbols()
    scope = list(dict.fromkeys(_hermes_top_symbols() + active_proposal_symbols() + exits))
    candidates = price_backfill_candidates(scope, min_rows=min_rows)
    yf_result = {"filled": 0}
    if candidates and yfinance_cap > 0:
        yf_result = backfill_yfinance_history(candidates[:yfinance_cap])
    return {
        "quotes_synced": n_quotes,
        "scope_symbols": len(scope),
        "reentry_exit_symbols": len(exits),
        "short_candidates": len(candidates),
        "skipped_over_cap": max(0, len(candidates) - yfinance_cap),
        "yfinance": yf_result,
    }


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
    wl = sync_daily_watchlist_prices()
    print(f"  [price-db] Watchlist quotes→ticker_prices: {wl.get('quotes_synced', 0)} rows; "
          f"yfinance filled {wl.get('yfinance', {}).get('filled', 0)}")
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


def count_price_rows(symbol: str) -> int:
    """Count daily close rows for a symbol in ticker_prices."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM ticker_prices WHERE symbol=%s", (symbol.upper(),))
    n = int((cur.fetchone() or [0])[0])
    cur.close()
    conn.close()
    return n


def sync_quotes_to_ticker_prices(symbols: list[str] | None = None) -> int:
    """Upsert daily closes from market_quotes (last quote per symbol per day)."""
    conn = _get_conn()
    cur = conn.cursor()
    syms = [str(s).upper() for s in (symbols or []) if s]
    if syms:
        cur.execute(
            """INSERT INTO ticker_prices (symbol, price_date, close_price, source)
               SELECT DISTINCT ON (UPPER(symbol), fetched_at::date)
                      UPPER(symbol), fetched_at::date, price, 'market_quotes'
               FROM market_quotes
               WHERE price IS NOT NULL AND price > 0
                 AND UPPER(symbol) = ANY(%s)
               ORDER BY UPPER(symbol), fetched_at::date, fetched_at DESC
               ON CONFLICT (symbol, price_date) DO UPDATE SET
                 close_price = EXCLUDED.close_price,
                 source = CASE
                   WHEN ticker_prices.source IN ('finviz', 'holdings', 'portfolio_repricer')
                   THEN ticker_prices.source
                   ELSE EXCLUDED.source
                 END""",
            (syms,),
        )
    else:
        cur.execute(
            """INSERT INTO ticker_prices (symbol, price_date, close_price, source)
               SELECT DISTINCT ON (UPPER(symbol), fetched_at::date)
                      UPPER(symbol), fetched_at::date, price, 'market_quotes'
               FROM market_quotes
               WHERE price IS NOT NULL AND price > 0
               ORDER BY UPPER(symbol), fetched_at::date, fetched_at DESC
               ON CONFLICT (symbol, price_date) DO UPDATE SET
                 close_price = EXCLUDED.close_price,
                 source = CASE
                   WHEN ticker_prices.source IN ('finviz', 'holdings', 'portfolio_repricer')
                   THEN ticker_prices.source
                   ELSE EXCLUDED.source
                 END"""
        )
    n = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return n


def backfill_yfinance_history(
    symbols: list[str],
    *,
    period: str = "1y",
    sleep_sec: float = 0.25,
) -> dict:
    """Fetch yfinance daily closes into ticker_prices for symbols still missing history."""
    import time

    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance not installed", "filled": 0}

    conn = _get_conn()
    cur = conn.cursor()
    filled, failed = [], []
    for sym in symbols:
        sym = str(sym).upper().strip()
        if not sym:
            continue
        try:
            hist = yf.Ticker(sym).history(period=period, interval="1d", auto_adjust=False)
            if hist is None or len(hist) == 0:
                failed.append(sym)
                continue
            rows = 0
            for idx, row in hist.iterrows():
                px = float(row.get("Close") or 0)
                if px <= 0:
                    continue
                d = idx.date() if hasattr(idx, "date") else idx
                cur.execute(
                    """INSERT INTO ticker_prices (symbol, price_date, close_price, source)
                       VALUES (%s, %s, %s, 'yfinance')
                       ON CONFLICT (symbol, price_date) DO NOTHING""",
                    (sym, d, round(px, 4)),
                )
                rows += cur.rowcount
            conn.commit()
            if rows:
                filled.append(sym)
        except Exception:
            conn.rollback()
            failed.append(sym)
        if sleep_sec:
            time.sleep(sleep_sec)
    cur.close()
    conn.close()
    return {"filled": len(filled), "failed": len(failed), "symbols": filled[:20], "failed_sample": failed[:20]}


def sync_watchlist_prices(symbols: list[str] | None = None, *, min_rows: int = 60) -> dict:
    """Quotes sync + yfinance gap-fill for watchlist symbols (used by refresh + daily pipeline)."""
    syms = [str(s).upper() for s in (symbols or []) if s]
    n_quotes = sync_quotes_to_ticker_prices(syms if syms else None)
    short = [s for s in syms if count_price_rows(s) < min_rows] if syms else []
    yf_result = backfill_yfinance_history(short) if short else {"filled": 0}
    return {"quotes_synced": n_quotes, "yfinance": yf_result}


if __name__ == "__main__":
    sync_daily_prices()
