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
import argparse
import json, os, sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import NamedTuple


LANE_ID = "price-db-sync"


def _receipt_lib():
    try:
        from scripts.lib import lane_last_receipt as lr
    except ImportError:
        from lib import lane_last_receipt as lr
    return lr

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# One write path per store (One Source of Truth, Phase 9): every ticker_prices statement in this
# file goes through lib/writers/ticker_prices_writer.py. The conflict rule each caller relied on
# is now a named parameter (finviz: overwrite; holdings + yfinance: nothing; the quotes->closes
# sync keeps its bounded INSERT..SELECT there verbatim).
from lib.writers.ticker_prices_writer import (  # noqa: E402
    sync_ticker_prices_from_market_quotes,
    write_ticker_prices,
)

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
    from lib.env_bootstrap import load_env
    load_env(names=("DB_PASSWORD",))
    pw = os.environ.get("DB_PASSWORD", "")
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw,
                            application_name="price_db_sync", connect_timeout=10)


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
    _counts = count_price_rows_many(syms) if syms else {}
    short = [s for s in syms if _counts.get(s, 0) < min_rows] if syms else []
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
    _counts = count_price_rows_many(scope)
    short = [s for s in scope if _counts.get(str(s).upper(), 0) < min_rows]
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
                written += write_ticker_prices(
                    cur, [{"symbol": sym, "price_date": today, "close_price": price}],
                    source="finviz", on_conflict="overwrite", round_to=4,
                ).rows_accepted

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
                written += write_ticker_prices(
                    cur, [{"symbol": sym, "price_date": today, "close_price": price}],
                    source="holdings", on_conflict="nothing", round_to=4,
                ).rows_accepted

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
    return count_price_rows_many([symbol]).get(str(symbol).upper(), 0)


def count_price_rows_many(symbols: list[str]) -> dict[str, int]:
    """Row counts for many symbols over ONE connection and ONE query.

    The callers filtered `[s for s in syms if count_price_rows(s) < min_rows]`, which opened and
    closed a connection per symbol from api_v2 request threads (n8nmat/b6, 2026-10-09)."""
    syms = list(dict.fromkeys(str(s).upper() for s in symbols if s))
    if not syms:
        return {}
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT symbol, COUNT(*) FROM ticker_prices WHERE symbol = ANY(%s) GROUP BY symbol",
                    (syms,))
        found = {str(r[0]).upper(): int(r[1]) for r in cur.fetchall()}
        cur.close()
    finally:
        conn.close()
    return {s: found.get(s, 0) for s in syms}


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
    # The bounded INSERT..SELECT lives in the ticker_prices write module, verbatim.
    n = sync_ticker_prices_from_market_quotes(
        cur, syms, min_ratio=PRICE_OUTLIER_MIN_RATIO, max_ratio=PRICE_OUTLIER_MAX_RATIO,
    ).rows_written
    # Quarantine the rows the INSERT skipped. Do not DELETE ticker_prices.
    cur.execute(  # nosemgrep: tq-py-sql-fstring -- symbol_filter is a literal fragment with a named param
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


# ── the session close, for the lanes that read it the same evening ───────────────────────────
#
# ticker_prices gains a session's bars from exactly one full-universe writer — this file's
# main() -> sync_daily_prices() -> sync_daily_watchlist_prices() -> sync_quotes_to_ticker_prices()
# — and it runs at ~06:10 ET (measured: 2026-11-06T11:10:31Z), hours before the session it would
# capture. At that hour the newest quote date is the PREVIOUS session: the first quote of the new
# day lands at 07:15. So the table's newest full-coverage date is always one session behind the
# one the evening desks ask about. Every other caller is per-symbol (proposal enrichment, the
# curator, remediation, three API endpoints, the watchlist sweep), so a symbol acquires a
# session bar only when an unrelated lane happens to touch it, and at whatever price that touch
# saw. Measured 2026-11-06: 5,577 symbols quoted, 1,101 session bars, and NO bar for SPY — the
# benchmark sector_momentum_engine date-aligns every sector to — so the 17:25 run dated the
# whole table 2026-11-05 again, raised nothing, and /v3/defense/classic read "STALE AS OF
# 2026-11-05". Of the 659 quote-derived 11-06 bars, 289 differ from that session's own post-close
# quote by more than 5 bp (QQQ: 660.79 written at 11:39, post-close 656.31) — the intraday touch.
#
# This fills the missing session bars from the same source the 06:10 lane uses — market_quotes,
# the broker read, never yfinance — for the session whose close the feed printed inside the
# window config/session_close.json declares. It writes only where no bar exists for
# (symbol, session), so it cannot displace finviz, holdings, portfolio_repricer, or the
# consolidated close eod_consolidated_close_sync wrote, and it cannot replace an intraday-written
# bar with a better one either (a separate, larger change).
#
# WHICH PRINT IS THE CLOSE (LQ-20261107-459). It is the FIRST print at or after the close inside
# a configured window, never the last print of the date. Measured read-only for 2026-11-06: every
# symbol in the sector universe printed at 16:00:04 ET — the consolidated close — and then the
# feed refreshed at 16:30:03 and 16:45:02. Taking the last print stored the refresh as the close:
# XLF 57.13 instead of 57.16 (5.2 bp), SPY 735.53 instead of 735.40, XLK 164.80 instead of 164.79.
# A symbol with quotes that day but none inside the window is reported (never guessed at), so a
# missing close shows up as `no_close_print` instead of as an after-hours price wearing its name.
SESSION_CLOSE_CONFIG = PROJECT_ROOT / "config" / "session_close.json"
SECTOR_UNIVERSE = ("XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
                   "SPY", "QQQ")
# The sectors page ranks these names. The ETF-only session fill left them without
# the benchmark's latest close, so 20-session RS stayed unmeasured. Same stored
# market_quotes close, never yfinance.
SCREENED_LEADER_SQL = """
SELECT DISTINCT upper(wi.symbol) AS symbol
  FROM watchlist_items wi
 WHERE wi.status IN ('active','researched')
   AND wi.score IS NOT NULL
   AND upper(wi.symbol) ~ '^[A-Z]{1,5}$'
   AND upper(wi.symbol) IN (
         SELECT DISTINCT upper(symbol) FROM incubator_universe
          WHERE sector IS NOT NULL AND btrim(sector) <> ''
       )
"""


def session_close_symbols(cur) -> list:
    """ETF universe plus screened sector leaders. Reads the cursor only.

    A failure of the leader query rolls back to a savepoint so the ETF fill
    still runs. The query is a read. It does not call a price provider.
    """
    try:
        cur.execute("SAVEPOINT screened_leaders")
        cur.execute(SCREENED_LEADER_SQL)
        leaders = [str(r[0]).upper() for r in (cur.fetchall() or []) if r and r[0]]
        cur.execute("RELEASE SAVEPOINT screened_leaders")
    except Exception:
        try:
            cur.execute("ROLLBACK TO SAVEPOINT screened_leaders")
        except Exception:
            return list(SECTOR_UNIVERSE)
        return list(SECTOR_UNIVERSE)
    return list(dict.fromkeys([*SECTOR_UNIVERSE, *leaders]))


class CloseWindow(NamedTuple):
    """The close print window: [close, end) in ET, and the config label the reasons quote."""

    close: time
    end: time
    minutes: int

    @property
    def label(self) -> str:
        return f"{self.close:%H:%M}-{self.end:%H:%M} ET"


def session_close_window(cfg_path=None) -> CloseWindow:
    """Load ``config/session_close.json``: the close time ET and how long its print may take.

    Config, not a constant: how late the consolidated close arrives is a property of the feed,
    and widening the window is an operator decision. Missing or malformed config raises — a price
    writer must not silently fall back to a guess about which price is a close.
    """
    path = Path(cfg_path or os.environ.get("TRADEAI_SESSION_CLOSE_CONFIG") or SESSION_CLOSE_CONFIG)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"session close window config unreadable: {path}: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError(f"session close window config is not JSON: {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"session close window config must be an object: {path}")
    try:
        hh, mm = str(doc["close_time_et"]).strip().split(":")
        close = time(int(hh), int(mm))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"session close window config needs close_time_et 'HH:MM': {path}: {exc}") from exc
    try:
        minutes = int(doc["window_minutes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"session close window config needs an integer window_minutes: {path}: {exc}") from exc
    if not 1 <= minutes <= 240:
        raise ValueError(f"session close window_minutes out of range (1..240): {minutes}")
    end_dt = datetime.combine(date(2000, 1, 1), close) + timedelta(minutes=minutes)
    if end_dt.date() != date(2000, 1, 1):
        raise ValueError(f"session close window {close:%H:%M}+{minutes}m crosses midnight")
    return CloseWindow(close=close, end=end_dt.time(), minutes=minutes)


def _et():
    from zoneinfo import ZoneInfo
    return ZoneInfo("America/New_York")


def _to_et(ts):
    """A DB timestamp in ET. Naive values are already ET (the server's TimeZone)."""
    return ts.astimezone(_et()) if getattr(ts, "tzinfo", None) else ts


def resolve_session_close_date(cur, symbols, *, today=None, window=None):
    """The newest session whose feed printed a close inside the configured window.

    A date qualifies only when at least one of these symbols printed inside
    ``[close_time_et, close_time_et + window_minutes)`` — the consolidated close. Both halves
    matter: a date whose newest print is premarket or intraday never closed (on 11-06, 289 of the
    659 quote-derived bars differed from that session's own post-close quote by more than 5 bp),
    and a date whose only post-close prints are after-hours refreshes has no close to store (that
    is what put a 16:45 print on XLF as the 11-06 close). A date that does not qualify is skipped,
    not fatal: at 08:00 ET on a trading day the newest date is today (premarket) and yesterday is
    the answer.
    """
    win = window or session_close_window()
    syms = [str(s).upper() for s in (symbols or []) if s]
    if not syms:
        return None, "no symbols"
    cur.execute(
        """SELECT fetched_at::date AS d,
                  max(fetched_at) AS last_q,
                  count(*) AS n,
                  count(*) FILTER (
                      WHERE (fetched_at AT TIME ZONE 'America/New_York')::time >= %(close)s
                        AND (fetched_at AT TIME ZONE 'America/New_York')::time <  %(end)s
                  ) AS n_close,
                  min(fetched_at) FILTER (
                      WHERE (fetched_at AT TIME ZONE 'America/New_York')::time >= %(close)s
                        AND (fetched_at AT TIME ZONE 'America/New_York')::time <  %(end)s
                  ) AS first_close,
                  EXTRACT(ISODOW FROM fetched_at::date) AS dow
           FROM market_quotes
           WHERE UPPER(symbol) = ANY(%(syms)s) AND price IS NOT NULL AND price > 0
             AND fetched_at::date <= COALESCE(%(today)s, CURRENT_DATE)
           GROUP BY 1
           ORDER BY 1 DESC
           LIMIT 10""",
        {"syms": syms, "today": today, "close": win.close, "end": win.end},
    )
    skipped = []
    for d, last_q, n, n_close, first_close, dow in cur.fetchall() or []:
        if int(dow) >= 6:                       # a weekend print is not a session
            skipped.append(f"{d} is a weekend")
            continue
        if not n_close:                         # count() FILTER is 0, never NULL: 0 = no close print
            skipped.append(f"{d} has no close print in {win.label} (last {_to_et(last_q):%H:%M} "
                           f"ET, {n} quotes)")
            continue
        why = (f"first close print {_to_et(first_close):%H:%M:%S} ET on {d} "
               f"({n_close} of {n} quotes inside {win.label}; last {_to_et(last_q):%H:%M} ET)")
        return d, (f"{why}; skipped {'; '.join(skipped)}" if skipped else why)
    return None, "; ".join(skipped[:3]) or "no quoted session date"


def plan_session_closes(cur, session, symbols, *, window=None):
    """Read-only: what a session fill would write, one row per symbol. Never writes.

    ``price`` is the FIRST print at or after the close inside the window — the close — and is
    NULL for a symbol that quoted that day but not inside it (``no_close_print``).
    """
    win = window or session_close_window()
    syms = [str(s).upper() for s in (symbols or []) if s]
    cur.execute(
        """WITH day_q AS (
               SELECT UPPER(symbol) AS symbol, max(fetched_at) AS last_q
               FROM market_quotes
               WHERE UPPER(symbol) = ANY(%(syms)s) AND price IS NOT NULL AND price > 0
                 AND fetched_at::date = %(session)s
               GROUP BY 1
           ), close_q AS (
               SELECT DISTINCT ON (UPPER(symbol))
                      UPPER(symbol) AS symbol, price, fetched_at
               FROM market_quotes
               WHERE UPPER(symbol) = ANY(%(syms)s) AND price IS NOT NULL AND price > 0
                 AND fetched_at::date = %(session)s
                 AND (fetched_at AT TIME ZONE 'America/New_York')::time >= %(close)s
                 AND (fetched_at AT TIME ZONE 'America/New_York')::time <  %(end)s
               ORDER BY UPPER(symbol), fetched_at ASC
           )
           SELECT d.symbol, c.price, c.fetched_at, d.last_q,
                  tp.close_price AS bar_close, tp.source AS bar_source,
                  (SELECT p.close_price FROM ticker_prices p
                    WHERE p.symbol = d.symbol AND p.price_date < %(session)s
                    ORDER BY p.price_date DESC LIMIT 1) AS prior_close
           FROM day_q d
           LEFT JOIN close_q c ON c.symbol = d.symbol
           LEFT JOIN ticker_prices tp
             ON tp.symbol = d.symbol AND tp.price_date = %(session)s
           ORDER BY d.symbol""",
        {"syms": syms, "session": session, "close": win.close, "end": win.end},
    )
    rows = []
    for sym, price, fetched_at, last_q, bar_close, bar_source, prior_close in cur.fetchall() or []:
        if bar_close is not None:
            action, detail = "has_bar", f"{bar_source} {float(bar_close):.4f}"
        elif price is None:
            action = "no_close_print"
            detail = f"no print inside {win.label} (last {_to_et(last_q):%H:%M:%S} ET)"
        else:
            outlier, reason = is_price_outlier(price, prior_close)
            action = "outlier" if outlier else "would_write"
            detail = reason if outlier else f"prior {prior_close}"
        rows.append({"symbol": sym, "session": str(session),
                     "close": float(price) if price is not None else None,
                     "quoted_at": str(fetched_at)[:19] if fetched_at is not None else None,
                     "last_quote": str(last_q)[:19],
                     "action": action, "detail": detail})
    missing = sorted(set(syms) - {r["symbol"] for r in rows})
    return {"session": str(session), "close_window": win.label, "rows": rows,
            "would_write": [r["symbol"] for r in rows if r["action"] == "would_write"],
            "has_bar": [r["symbol"] for r in rows if r["action"] == "has_bar"],
            "outliers": [r["symbol"] for r in rows if r["action"] == "outlier"],
            "no_close_print": [r["symbol"] for r in rows if r["action"] == "no_close_print"],
            "no_quote": missing}



def sync_session_closes(symbols=None, *, session=None, dry_run=False, window=None) -> dict:
    """Fill the missing session bars for ``symbols`` (default: ETFs plus screened leaders).

    Broker-read closes only (``market_quotes``); yfinance is never consulted. The close is the
    FIRST print inside the configured window, so an after-hours refresh can never be stored as
    the close (LQ-20261107-459). ``dry_run`` reports the plan and writes nothing.
    """
    from datetime import date as _date
    win = window or session_close_window()
    if isinstance(session, str) and session.strip():
        session = _date.fromisoformat(session.strip()[:10])
    conn = _get_conn()
    cur = conn.cursor()
    try:
        if symbols is None:
            syms = session_close_symbols(cur)
        else:
            syms = [str(s).upper() for s in symbols if s]
        why = "session given"
        if session is None:
            session, why = resolve_session_close_date(cur, syms, window=win)
        if session is None:
            return {"ok": False, "session": None, "reason": why, "symbols": len(syms),
                    "close_window": win.label, "written": 0, "would_write": [], "has_bar": [],
                    "outliers": [], "no_close_print": [], "no_quote": []}
        plan = plan_session_closes(cur, session, syms, window=win)
        written = 0
        if plan["would_write"] and not dry_run:
            receipt = sync_ticker_prices_from_market_quotes(
                cur, plan["would_write"],
                min_ratio=PRICE_OUTLIER_MIN_RATIO, max_ratio=PRICE_OUTLIER_MAX_RATIO,
                session=session, only_missing=True, close_window=(win.close, win.end),
            )
            written = receipt.rows_written
            conn.commit()
        return {"ok": True, "session": str(session), "reason": why, "symbols": len(syms),
                "dry_run": bool(dry_run), "written": written, **plan}
    except BaseException:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


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
            px_rows = []
            for idx, row in hist.iterrows():
                px = float(row.get("Close") or 0)
                if px <= 0:
                    continue
                d = idx.date() if hasattr(idx, "date") else idx
                px_rows.append({"symbol": sym, "price_date": d, "close_price": px})
            rows = write_ticker_prices(cur, px_rows, source="yfinance", on_conflict="nothing",
                                       round_to=4).rows_written
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
    _counts = count_price_rows_many(syms) if syms else {}
    short = [s for s in syms if _counts.get(s, 0) < min_rows] if syms else []
    yf_result = backfill_yfinance_history(short) if short else {"filled": 0}
    return {"quotes_synced": n_quotes, "yfinance": yf_result}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--dry-run", action="store_true", help="offline price-sync plan")
    ap.add_argument("--session-close", action="store_true",
                    help="fill missing session bars for --symbols (default: the sector universe) "
                         "from market_quotes; writes nothing with --dry-run")
    ap.add_argument("--session", metavar="YYYY-MM-DD",
                    help="the session --session-close fills (default: the newest post-close session)")
    ap.add_argument("--symbols", metavar="CSV", help="symbols for --session-close")
    args = ap.parse_args(argv)
    if args.session_close:
        syms = [s.strip().upper() for s in (args.symbols or "").split(",") if s.strip()] or None
        res = sync_session_closes(syms, session=args.session, dry_run=args.dry_run)
        print(json.dumps(res, indent=2, sort_keys=True))
        if not res.get("ok"):
            print(f"{LANE_ID}: no closed session to fill — {res.get('reason')}", file=sys.stderr)
            return 1
        filled = len(res["would_write"]) if args.dry_run else res["written"]
        print(f"{'DRY-RUN' if args.dry_run else 'APPLIED'} {LANE_ID} --session-close "
              f"{res['session']}: {'would write' if args.dry_run else 'wrote'} {filled} bars; "
              f"{len(res['has_bar'])} already had one, {len(res['outliers'])} out of bounds, "
              f"{len(res.get('no_close_print') or [])} without a print in "
              f"{res.get('close_window') or 'the close window'}, "
              f"{len(res['no_quote'])} unquoted")
        return 0
    if args.dry_run:
        print(f"DRY-RUN {LANE_ID}: would persist daily cache/holdings prices, sync market_quotes "
              "and fill short watchlist history via yfinance; reject outliers before ticker_prices writes")
        return 0
    lr = _receipt_lib()
    started = lr.now_iso()
    try:
        written = sync_daily_prices()
    except BaseException as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="price_db_sync.py", error=type(exc).__name__)
        raise
    lr.write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started,
                          script="price_db_sync.py", summary={"prices_written": written})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
