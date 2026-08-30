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

# Outlier guard (Stage A, 2026-08-27; audit finding C3): the only prior check
# on a price write anywhere in this file was `price > 0`. The 2026-07-24-era
# corrupt-bar incident (NVDA priced at $0.05) was never actually fixed — a
# direct query found the original rows still unscrubbed plus 59 fresh 10x+
# single-day moves in a trailing 30-day window. A single bad tick reaching
# ticker_prices feeds Watch, Hermes research, and rebalance/proposal sizing
# with no guard in between.
#
# Bounds are ratio-based, not absolute-dollar, since a $0.50 stock and a
# $500 stock both need the same relative protection. Defaults match the
# audit's own outlier definition (>=10x move) so this directly prevents
# recurrence of what was found. Env-overridable without a code change, since
# a real split or a genuine multi-bagger day is a false positive this bound
# WILL reject — an operator who hits that should widen the ratio, not read
# it as a bug in the guard.
PRICE_OUTLIER_MIN_RATIO = float(os.environ.get("TICKER_PRICE_OUTLIER_MIN_RATIO", "0.1"))
PRICE_OUTLIER_MAX_RATIO = float(os.environ.get("TICKER_PRICE_OUTLIER_MAX_RATIO", "10.0"))
QUARANTINE_NAME = "price_outlier_quarantine.jsonl"


def is_price_outlier(new_price, prior_price, *,
                     min_ratio: float = PRICE_OUTLIER_MIN_RATIO,
                     max_ratio: float = PRICE_OUTLIER_MAX_RATIO) -> tuple:
    """(is_outlier, reason). Pure — no DB. `prior_price` of None/0 means no
    prior close exists for this symbol yet, which is not an outlier: it is
    the first price on record and there is nothing to compare against."""
    try:
        new_price = float(new_price)
    except (TypeError, ValueError):
        return True, f"non-numeric price {new_price!r}"
    if new_price <= 0:
        return True, f"non-positive price {new_price}"
    if not prior_price:
        return False, ""
    try:
        prior_price = float(prior_price)
    except (TypeError, ValueError):
        return False, ""
    if prior_price <= 0:
        return False, ""
    ratio = new_price / prior_price
    if ratio < min_ratio or ratio > max_ratio:
        return True, (f"{new_price} is {ratio:.2f}x the prior close {prior_price} "
                      f"(bounds {min_ratio}x-{max_ratio}x)")
    return False, ""


def quarantine_path(root: Path | None = None) -> Path:
    base = Path(root) if root is not None else STATE_DIR
    return base / QUARANTINE_NAME


def quarantine_outlier(
    *,
    symbol: str,
    price,
    prior_close,
    reason: str,
    source: str,
    price_date: str,
    path: Path | None = None,
    write: bool = True,
) -> dict:
    """Log a rejected ingest. Never deletes ticker_prices history."""
    from datetime import datetime, timezone
    rec = {
        "schema": "PriceOutlierQuarantine@v1",
        "symbol": str(symbol or "").upper(),
        "price": price,
        "prior_close": prior_close,
        "reason": reason,
        "source": source,
        "price_date": str(price_date),
        "action": "rejected_not_written",
        "history_scrubbed": False,
        "authority": "READ_ONLY_ADVISORY",
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    if write:
        dest = path or quarantine_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    return rec


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


def sync_daily_watchlist_prices(*, yfinance_cap: int = 40, min_rows: int = 60) -> dict:
    """Keep watchlist + active proposal ticker_prices current (daily cron)."""
    n_quotes = sync_quotes_to_ticker_prices()
    scope = list(dict.fromkeys(_hermes_top_symbols() + active_proposal_symbols()))
    # Defense Desk: all 11 sector ETFs must stay priced regardless of watchlist/portfolio
    # membership — the sector_momentum_engine dates each row to its own last close, so
    # a missing price feed silently ages sectors (XLRE 24d, XLC 14d as of Aug 6).
    SECTOR_ETFS = ["XLE","XLB","XLF","XLK","XLI","XLV","XLY","XLC","XLP","XLRE","XLU"]
    for etf in SECTOR_ETFS:
        if etf not in scope:
            scope.append(etf)
    short = [s for s in scope if count_price_rows(s) < min_rows]
    yf_result = {"filled": 0}
    if short and yfinance_cap > 0:
        yf_result = backfill_yfinance_history(short[:yfinance_cap])
    return {
        "quotes_synced": n_quotes,
        "scope_symbols": len(scope),
        "short_candidates": len(short),
        "yfinance": yf_result,
    }


def sync_daily_prices():
    """Persist today's prices from finviz cache + holdings to DB."""
    conn = _get_conn()
    cur = conn.cursor()
    today = date.today().isoformat()
    written = 0
    rejected = []

    def _prior_close(sym: str):
        cur.execute("""SELECT close_price FROM ticker_prices
                       WHERE symbol=%s AND price_date < %s
                       ORDER BY price_date DESC LIMIT 1""", (sym, today))
        row = cur.fetchone()
        return float(row[0]) if row else None

    # 1. Finviz quote cache (most accurate for Schwab tickers)
    fq_path = STATE_DIR / "finviz_quote_cache.json"
    if fq_path.exists():
        fq = json.loads(fq_path.read_text())
        for sym, data in fq.items():
            if sym.startswith("_") or not isinstance(data, dict):
                continue
            price = data.get("price")
            if isinstance(price, (int, float)) and price > 0:
                outlier, reason = is_price_outlier(price, _prior_close(sym))
                if outlier:
                    rejected.append(f"{sym}(finviz):{reason}")
                    quarantine_outlier(
                        symbol=sym, price=price, prior_close=_prior_close(sym),
                        reason=reason, source="finviz", price_date=today,
                    )
                    continue
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
                outlier, reason = is_price_outlier(price, _prior_close(sym))
                if outlier:
                    rejected.append(f"{sym}(holdings):{reason}")
                    quarantine_outlier(
                        symbol=sym, price=price, prior_close=_prior_close(sym),
                        reason=reason, source="holdings", price_date=today,
                    )
                    continue
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
    if rejected:
        print(f"  [price-db] REJECTED {len(rejected)} outlier price(s), not written: "
              f"{'; '.join(rejected[:10])}" + (" ..." if len(rejected) > 10 else ""))
    wl = sync_daily_watchlist_prices()
    print(f"  [price-db] Watchlist quotes→ticker_prices: {wl.get('quotes_synced', 0)} rows; "
          f"yfinance filled {wl.get('yfinance', {}).get('filled', 0)}")
    return written


def get_price_from_db(symbol: str, date_str: str, fidelity_map: dict = None) -> float | None:
    """Get price from DB, with Fidelity mapping support.

    This is the canonical price lookup — use this instead of JSON cache.
    Falls back to nearest date within 5 days.

    G-PRICE-01: skip (symbol, date) pairs present in ticker_prices_quarantine
    (fail-soft if that table is missing).
    """
    mapped = symbol
    if fidelity_map and symbol in fidelity_map:
        mapped = fidelity_map[symbol]

    conn = _get_conn()
    try:
        from scripts.lib.ticker_price_quarantine import is_quarantined, quarantined_pairs
    except Exception:
        try:
            from lib.ticker_price_quarantine import is_quarantined, quarantined_pairs  # type: ignore
        except Exception:
            is_quarantined = None  # type: ignore
            quarantined_pairs = None  # type: ignore

    q: set = set()
    if quarantined_pairs is not None:
        q = quarantined_pairs(conn)

    cur = conn.cursor()
    try:
        # Exact date — honor quarantine skip
        if not (is_quarantined and is_quarantined(mapped, date_str, q)):
            cur.execute(
                "SELECT close_price FROM ticker_prices WHERE symbol=%s AND price_date=%s",
                (mapped, date_str),
            )
            row = cur.fetchone()
            if row:
                return float(row[0])

        # Nearest within 5 days, skipping quarantined bars
        cur.execute("""
            SELECT close_price, price_date FROM ticker_prices
            WHERE symbol=%s AND price_date BETWEEN %s::date - 5 AND %s::date + 5
            ORDER BY ABS(price_date - %s::date)
        """, (mapped, date_str, date_str, date_str))
        for price, pdt in cur.fetchall() or []:
            if is_quarantined and is_quarantined(mapped, pdt, q):
                continue
            return float(price)
        return None
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def get_latest_price_from_db(symbol: str) -> float | None:
    """Get most recent price for a symbol from DB.

    G-PRICE-01: walk recent bars newest-first, skipping quarantined dates.
    """
    conn = _get_conn()
    try:
        from scripts.lib.ticker_price_quarantine import is_quarantined, quarantined_pairs
    except Exception:
        try:
            from lib.ticker_price_quarantine import is_quarantined, quarantined_pairs  # type: ignore
        except Exception:
            is_quarantined = None  # type: ignore
            quarantined_pairs = None  # type: ignore

    q: set = set()
    if quarantined_pairs is not None:
        q = quarantined_pairs(conn)

    cur = conn.cursor()
    try:
        # Bound the walk so a fully-quarantined symbol cannot scan forever.
        cur.execute(
            "SELECT close_price, price_date FROM ticker_prices "
            "WHERE symbol=%s ORDER BY price_date DESC LIMIT 60",
            (symbol,),
        )
        for price, pdt in cur.fetchall() or []:
            if is_quarantined and is_quarantined(symbol, pdt, q):
                continue
            return float(price)
        return None
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


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
    """Upsert daily closes from market_quotes (last quote per symbol per day).

    Bounded against the last known close per symbol (outlier guard, C3): a
    candidate whose price is outside [MIN_RATIO, MAX_RATIO] of the most
    recent PRIOR ticker_prices row for that symbol is dropped rather than
    written. A symbol with no prior row (first price on record) always
    passes — there is nothing to bound it against yet.
    """
    conn = _get_conn()
    cur = conn.cursor()
    syms = [str(s).upper() for s in (symbols or []) if s]
    symbol_filter = "AND UPPER(symbol) = ANY(%(syms)s)" if syms else ""
    cur.execute(
        f"""WITH candidates AS (
               SELECT DISTINCT ON (UPPER(symbol), fetched_at::date)
                      UPPER(symbol) AS symbol, fetched_at::date AS price_date, price
               FROM market_quotes
               WHERE price IS NOT NULL AND price > 0
                 {symbol_filter}
               ORDER BY UPPER(symbol), fetched_at::date, fetched_at DESC
           ),
           bounded AS (
               SELECT c.symbol, c.price_date, c.price, prior.close_price AS prior_price
               FROM candidates c
               LEFT JOIN LATERAL (
                   SELECT tp.close_price FROM ticker_prices tp
                   WHERE tp.symbol = c.symbol AND tp.price_date < c.price_date
                   ORDER BY tp.price_date DESC LIMIT 1
               ) prior ON true
           )
           INSERT INTO ticker_prices (symbol, price_date, close_price, source)
           SELECT symbol, price_date, price, 'market_quotes'
           FROM bounded
           WHERE prior_price IS NULL
              OR price BETWEEN prior_price * %(min_ratio)s AND prior_price * %(max_ratio)s
           ON CONFLICT (symbol, price_date) DO UPDATE SET
             close_price = EXCLUDED.close_price,
             source = CASE
               WHEN ticker_prices.source IN ('finviz', 'holdings', 'portfolio_repricer')
               THEN ticker_prices.source
               ELSE EXCLUDED.source
             END""",
        {"syms": syms, "min_ratio": PRICE_OUTLIER_MIN_RATIO, "max_ratio": PRICE_OUTLIER_MAX_RATIO},
    )
    n = cur.rowcount
    # Quarantine the rows the INSERT skipped. Do not DELETE ticker_prices.
    cur.execute(
        f"""WITH candidates AS (
               SELECT DISTINCT ON (UPPER(symbol), fetched_at::date)
                      UPPER(symbol) AS symbol, fetched_at::date AS price_date, price
               FROM market_quotes
               WHERE price IS NOT NULL AND price > 0
                 {symbol_filter}
               ORDER BY UPPER(symbol), fetched_at::date, fetched_at DESC
           ),
           bounded AS (
               SELECT c.symbol, c.price_date, c.price, prior.close_price AS prior_price
               FROM candidates c
               LEFT JOIN LATERAL (
                   SELECT tp.close_price FROM ticker_prices tp
                   WHERE tp.symbol = c.symbol AND tp.price_date < c.price_date
                   ORDER BY tp.price_date DESC LIMIT 1
               ) prior ON true
           )
           SELECT symbol, price_date, price, prior_price
           FROM bounded
           WHERE prior_price IS NOT NULL
             AND (price < prior_price * %(min_ratio)s OR price > prior_price * %(max_ratio)s)""",
        {"syms": syms, "min_ratio": PRICE_OUTLIER_MIN_RATIO, "max_ratio": PRICE_OUTLIER_MAX_RATIO},
    )
    for row in cur.fetchall() or []:
        prior = row[3]
        price = row[2]
        outlier, reason = is_price_outlier(price, prior)
        if outlier:
            quarantine_outlier(
                symbol=row[0], price=price, prior_close=prior,
                reason=reason, source="market_quotes", price_date=str(row[1]),
            )
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
