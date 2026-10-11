"""
finviz_enrichment.py — Comprehensive Finviz Elite data enrichment
Version: 1.0 | April 16, 2026

Single source of truth for ALL Finviz data across Trade AI and Portfolio Intelligence.
Pulls 5 views per ticker batch, merges into one comprehensive record per ticker.
Shared cache prevents duplicate API calls across systems.

VIEWS USED:
  v=111  Base: Price, Change%, Volume, Sector, Company
  v=131  Ownership: Float, Short Float, Short Ratio, Avg Volume, Inst Ownership
  v=141  Performance: Week/Month/Quarter/HalfYr/YTD/Year, RVOL, Volatility
  v=161  Fundamentals: PE, ROE, Dividend Yield, Margins, Debt ratios
  v=171  Technical: RSI, SMA20/50/200%, ATR, Beta, 52wk H/L, Gap%

OUTPUT per ticker (~45 fields):
  float_m, short_float_pct, short_ratio, avg_vol
  rvol, perf_week, perf_month, perf_ytd, perf_year
  volatility_w, volatility_m, earnings_date
  div_yield, roe, roa, gross_margin, profit_margin, debt_equity
  rsi, sma20_pct, sma50_pct, sma200_pct, atr, beta
  week52_high_pct, week52_low_pct, gap_pct, change_from_open
  inst_own_pct, insider_own_pct

CACHE: data/state/ticker_enrichment_cache.json
  - Refreshed once per day per ticker
  - Shared across Trade AI + Portfolio Intelligence
  - PostgreSQL-ready schema (one row per ticker)

RATE LIMITS:
  - Finviz Elite API: ~100 req/hour
  - Batch size: 20 tickers per request
  - 5 views × ceil(N/20) batches per full enrichment
  - 70 tickers = 5 × 4 = 20 requests (well within limits)

USAGE:
  from finviz_enrichment import enrich_tickers, get_enriched, load_cache

  # Enrich a list of tickers (uses cache, fetches missing)
  results = enrich_tickers(['MAMO','V','SCHD'], project_root='.')

  # Get single ticker from cache
  mamo = get_enriched('MAMO', project_root='.')
  print(mamo['rsi'], mamo['float_m'], mamo['rvol'])

LANE (cron L142, ``finviz-enrichment``): ``python scripts/finviz_enrichment.py [SYMBOL ...] [--dry-run]``.
``--dry-run`` resolves the same universe as a real run (watchlist_items through a READ ONLY session +
holdings.json), reads the cache file without creating its directory, and prints which tickers are stale,
the views and the Finviz Elite export request count a real run would spend. It returns before
pipeline_registry.run_start, before any Finviz request (paid, rate-limited: never called by a dry run),
before save_cache and before the intelligence-entity write-back. It reads no Finviz credential. No receipt.

A real run writes ``<state_root>/data/runtime/finviz-enrichment_last.json`` (LaneRunReceipt@v1; ``ok_at``
only on success). Exit codes: 0 = ran (all tickers fresh in cache, an empty universe, or some views /
batches failing while others returned data are findings); 1 = the run failed: crash (failed receipt,
exception re-raised), the watchlist universe query failed (DB unavailable), or tickers were stale and no
view returned any ticker (no auth, HTTP errors, throttle: nothing could be fetched when work existed).

SCALP HOT TIER (``--scalp-hot``, lane ``finviz-enrichment-scalp-hot``; operator decision (4) 2026-10-10): every 5 min
on market days 06:00-16:00 ET, ONE custom-column export (``v=152&c=...``: price, RVOL, gap, float, ATR, RSI,
change-from-open, volume; ceil(N/20) requests) for the symbols on the scalp list (``lib.data_broker.scalp_list``,
cap 100). The hot fields are merged into the existing record and stamped ``hot_cached_at``; ``cached_at`` (the
six-view refresh stamp the 6 h TTL reads) is never touched, so a hot refresh cannot make a record look fully fresh.
Inert unless ``SCALP_HOT_TIER=1`` and no kill file (prints SKIPPED_FLAG_OFF, exit 0). ``--dry-run`` reads the list
and the cache only and prints the request count; it returns before any Finviz request and before save_cache.
"""
from __future__ import annotations

import csv
import io
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests

try:  # GAP 14 (2026-10-10): one shared ticker check before any Finviz request
    from lib.provider_ticker_guard import partition as _ticker_partition
except ImportError:  # imported as scripts.finviz_enrichment
    from scripts.lib.provider_ticker_guard import partition as _ticker_partition

# ── Constants ─────────────────────────────────────────────────────────────────
CACHE_FILE = "data/state/ticker_enrichment_cache.json"
CACHE_TTL_HOURS = 6          # refresh if older than 6 hours
BATCH_SIZE = 20              # Finviz max tickers per export request
REQUEST_DELAY = 0.5          # seconds between requests
FINVIZ_EXPORT = "https://elite.finviz.com/export"
LANE_ID = "finviz-enrichment"
HOT_LANE_ID = "finviz-enrichment-scalp-hot"
#: Finviz Elite custom-column export for the scalp hot tier: 1 Ticker, 25 Float, 49 ATR, 59 RSI, 60 Change from
#: Open, 61 Gap, 63 Avg Volume, 64 Rel Volume, 65 Price, 66 Change, 67 Volume. Parsed BY HEADER NAME (aliases below):
#: a column id that maps to another header is reported as SCHEMA DRIFT and left unset, never read positionally.
HOT_VIEW = 152
HOT_COLUMNS = "1,25,49,59,60,61,63,64,65,66,67"
HOT_COLUMN_MAP = {
    "Ticker": "ticker",
    "Shares Float": "float_m", "Float": "float_m",
    "Average True Range": "atr", "ATR": "atr", "ATR (14)": "atr",
    "Relative Strength Index (14)": "rsi", "RSI (14)": "rsi", "RSI": "rsi",
    "Change from Open": "change_from_open_pct",
    "Gap": "gap_pct",
    "Average Volume": "avg_vol_m", "Avg Volume": "avg_vol_m",
    "Relative Volume": "rvol", "Rel Volume": "rvol",
    # price/change/volume are dropped from every six-view record (SKIP_DUPLICATES), so the cache has never held a
    # price; the hot tier stores them under hot_* names so no existing raw reader starts reading a new field.
    "Price": "hot_price", "Change": "hot_change_pct", "Volume": "hot_volume",
}
#: the fields a hot refresh owns; merge_cache_records carries them from whichever side has the newer hot stamp
HOT_FIELDS = ("float_m", "atr", "rsi", "change_from_open_pct", "gap_pct", "avg_vol_m", "rvol", "hot_price",
              "hot_change_pct", "hot_volume")
#: a hot refresh skips a symbol whose hot stamp is younger than this (a */5 grid fires ~every 5 min)
HOT_MIN_REFRESH_MIN = 4.0
#: per-run measurements of the last enrich_tickers() call (read by main() for the receipt / exit code)
_RUN_STATS: Dict[str, Any] = {}
#: universe read failures seen by the last default_universe_symbols() call
_UNIVERSE_ERRORS: List[str] = []


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.finviz_enrichment
        from scripts.lib import lane_last_receipt as lr
    return lr

# Views to pull and their column mappings.
#
# Format: {view: {finviz_header_name: field_name}}
#
# KEYED BY HEADER NAME, NEVER BY POSITION. The previous map was positional, and
# Finviz silently inserted three columns into v=141 -- "Performance (3 Years)",
# "(5 Years)" and "(10 Years)" at indices 8-10 -- which shifted every later field
# right by three without any error. Index 10 had been labelled "recom"; it was in
# fact "Performance (10 Years)", so a stock down -100% over ten years was scored
# -100 on a 1-5 analyst scale and rendered "Strong Buy", while a +95,699% winner
# rendered "Strong Sell". 131,050 of 132,894 rows (98.6%) were wrong, for five
# months, and the ratings were ANTI-correlated with reality. Index 12 had been
# labelled "rvol" and was really "Volatility (Month)", so RVOL was wrong too.
#
# A positional map cannot detect this: every shifted value still parses as a
# float. A name-keyed map fails loudly instead -- an absent column is reported
# and left None, never filled from whichever neighbour happens to sit there.
#
# Header names below were captured live from elite.finviz.com/export on
# 2026-09-13 and are pinned in tests/test_finviz_column_map_20260913.py.
VIEWS = {
    111: {  # Base — Price, Change, Volume, Sector, Company
        "Ticker": "ticker", "Company": "company", "Sector": "sector",
        "Industry": "industry", "Country": "country",
        "Market Cap": "market_cap_b", "P/E": "pe",
        "Price": "price", "Change": "change_pct", "Volume": "volume",
    },
    131: {  # Ownership — Float, Short, Institutional
        "Ticker": "ticker", "Market Cap": "market_cap_b",
        "Shares Outstanding": "shares_outstanding_m", "Shares Float": "float_m",
        "Insider Ownership": "insider_own_pct",
        "Insider Transactions": "insider_trans_pct",
        "Institutional Ownership": "inst_own_pct",
        "Institutional Transactions": "inst_trans_pct",
        "Short Float": "short_float_pct", "Short Ratio": "short_ratio",
        "Average Volume": "avg_vol_m",
        "Price": "price", "Change": "change_pct", "Volume": "volume",
    },
    141: {  # Performance + RVOL — NOTE: this view carries NO "Recom" column.
        "Ticker": "ticker",
        "Performance (Week)": "perf_week_pct",
        "Performance (Month)": "perf_month_pct",
        "Performance (Quarter)": "perf_quarter_pct",
        "Performance (Half Year)": "perf_halfyr_pct",
        "Performance (YTD)": "perf_ytd_pct",
        "Performance (Year)": "perf_year_pct",
        "Performance (3 Years)": "perf_3y_pct",
        "Performance (5 Years)": "perf_5y_pct",
        "Performance (10 Years)": "perf_10y_pct",
        "Volatility (Week)": "volatility_w_pct",
        "Volatility (Month)": "volatility_m_pct",
        "Average Volume": "avg_vol_m2",
        "Relative Volume": "rvol",
        "Price": "price", "Change": "change_pct", "Volume": "volume",
    },
    161: {  # Fundamentals
        "Ticker": "ticker", "Market Cap": "market_cap_b2",
        "Dividend Yield": "div_yield_pct",
        "Return on Assets": "roa_pct", "Return on Equity": "roe_pct",
        "Return on Invested Capital": "roic_pct",
        "Current Ratio": "current_ratio", "Quick Ratio": "quick_ratio",
        "LT Debt/Equity": "lt_debt_equity",
        "Total Debt/Equity": "total_debt_equity",
        "Gross Margin": "gross_margin_pct",
        "Operating Margin": "oper_margin_pct",
        "Profit Margin": "profit_margin_pct",
        "Earnings Date": "earnings_date2",
        "Price": "price", "Change": "change_pct", "Volume": "volume",
    },
    121: {  # Valuation — EPS growth, Forward PE
        "Ticker": "ticker", "Market Cap": "market_cap_b3",
        "P/E": "pe2", "Forward P/E": "forward_pe", "PEG": "peg",
        "P/S": "ps", "P/B": "pb", "P/Cash": "pc", "P/Free Cash Flow": "pfcf",
        "EPS Growth This Year": "eps_growth_this_y_pct",
        "EPS Growth Next Year": "eps_growth_next_y_pct",
        "EPS Growth Past 5 Years": "eps_growth_past_5y_pct",
        "EPS Growth Next 5 Years": "eps_growth_next_5y_pct",
        "Sales Growth Past 5 Years": "sales_growth_past_5y_pct",
        "Price": "price2", "Change": "change_pct2", "Volume": "volume2",
    },
    171: {  # Technical — RSI, SMA, ATR, Beta (NO COOKIE NEEDED)
        "Ticker": "ticker", "Beta": "beta", "Average True Range": "atr",
        "20-Day Simple Moving Average": "sma20_pct",
        "50-Day Simple Moving Average": "sma50_pct",
        "200-Day Simple Moving Average": "sma200_pct",
        "52-Week High": "week52_high_pct", "52-Week Low": "week52_low_pct",
        "Relative Strength Index (14)": "rsi",
        "Price": "price", "Change": "change_pct",
        "Change from Open": "change_from_open_pct", "Gap": "gap_pct",
        "Volume": "volume",
    },
}

# Fields that are percentages — strip % and convert to float
PCT_FIELDS = {
    "change_pct", "perf_week_pct", "perf_month_pct", "perf_quarter_pct",
    "perf_halfyr_pct", "perf_ytd_pct", "perf_year_pct", "volatility_w_pct",
    "volatility_m_pct", "short_float_pct", "insider_own_pct", "inst_own_pct",
    "insider_trans_pct", "inst_trans_pct", "div_yield_pct", "roa_pct",
    "roe_pct", "roic_pct", "gross_margin_pct", "oper_margin_pct",
    "profit_margin_pct", "sma20_pct", "sma50_pct", "sma200_pct",
    "week52_high_pct", "week52_low_pct", "change_from_open_pct", "gap_pct",
    # Long-horizon performance: these are the columns Finviz inserted into v=141
    # and are the reason the positional map rotted. They are percentages.
    "perf_3y_pct", "perf_5y_pct", "perf_10y_pct",
    # v=121 carries EPS/sales GROWTH percentages, not EPS dollar amounts. The
    # positional map read "EPS Growth This Year" into a field named eps_ttm.
    "eps_growth_this_y_pct", "eps_growth_next_y_pct", "eps_growth_past_5y_pct",
    "eps_growth_next_5y_pct", "sales_growth_past_5y_pct",
    "hot_change_pct",
}

# Skip these duplicate fields from secondary views
SKIP_DUPLICATES = {"price", "change_pct", "volume", "market_cap_b2", "market_cap_b3",
                   "avg_vol_m2", "earnings_date2", "pe2", "price2", "change_pct2", "volume2"}


def _classify_recom(recom_raw):
    """Map a Finviz recom value to (score, rating, reject_reason).

    Finviz recom is a 1-5 scale. Anything else is refused rather than coerced,
    and the caller gets a reason instead of a fabricated rating.

    This exists because the previous inline version did

        rs = float(str(recom_raw).replace("%","").strip())

    and the "%" was the one signal that the value was the WRONG FIELD. Stripping
    it laundered a percentage into a rating: when the upstream view's columns
    moved, values like "351.79%" arrived here, and 351.79 >= 4.5 rendered
    "Strong Sell".

    Measured on the live table 2026-09-13, before this change:

        last 30 days    5,774 out-of-range vs 105 valid
        since 2026-04   ~81,000 out-of-range vs ~1,800 valid
        every out-of-range row rendered "Strong Sell"

    WMT read "Strong Sell" on 351.79 while Yahoo had it at "buy" with 40
    analysts and a 137.98 mean target. Refusing is the honest outcome: no rating
    is a fact, an invented one is not.

    Returns (None, None, reason) on refusal so callers can record WHY, rather
    than being unable to distinguish "no data" from "bad data".
    """
    if recom_raw is None:
        return None, None, "missing"
    text = str(recom_raw).strip()
    if not text:
        return None, None, "empty"
    if "%" in text:
        # A percent sign means this is not a recommendation at all.
        return None, None, "percent_sign_not_a_1_5_rating"
    try:
        rs = float(text)
    except (ValueError, TypeError):
        return None, None, "unparseable"
    if not (1.0 <= rs <= 5.0):
        return None, None, f"out_of_range_{rs:g}_not_in_1_5"
    rating = (
        "Strong Buy"  if rs < 1.5 else
        "Buy"         if rs < 2.5 else
        "Hold"        if rs < 3.5 else
        "Sell"        if rs < 4.5 else
        "Strong Sell"
    )
    return round(rs, 2), rating, None


def _env(key: str, default: str = "") -> str:
    """Prefer SM tmpfs for Finviz auth keys; never log values."""
    if key in ("FINVIZ_COOKIE", "FINVIZ_API_TOKEN", "FINVIZ_USER_AGENT"):
        try:
            import sys as _sys
            _sec = Path(__file__).resolve().parent / "secrets"
            if str(_sec) not in _sys.path:
                _sys.path.insert(0, str(_sec))
            from resolve_secret import resolve_secret
            return resolve_secret(key, default)
        except Exception:
            pass
    return os.getenv(key, default).strip()


def _load_env(root: Path) -> None:
    """Load tmpfs SM render first, then disk .env (setdefault — first wins)."""
    try:
        import sys as _sys
        _sec = Path(__file__).resolve().parent / "secrets"
        if str(_sec) not in _sys.path:
            _sys.path.insert(0, str(_sec))
        from resolve_secret import parse_env_file, render_env_path
        for path in (render_env_path(), root / ".env"):
            if path.is_file():
                for k, v in parse_env_file(path).items():
                    if k:
                        os.environ.setdefault(k, v)
        return
    except Exception:
        pass
    env_path = root / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def _parse_float(val: str) -> Optional[float]:
    """Parse a Finviz value to float, handling %, B, M suffixes."""
    if not val or val in ("-", "N/A", "", "nan"):
        return None
    val = val.strip().strip('"')
    multiplier = 1.0
    if val.endswith("B"):
        multiplier = 1000.0
        val = val[:-1]
    elif val.endswith("M"):
        multiplier = 1.0
        val = val[:-1]
    elif val.endswith("K"):
        multiplier = 0.001
        val = val[:-1]
    val = val.replace("%", "").replace("+", "").replace(",", "")
    try:
        return round(float(val) * multiplier, 4)
    except (ValueError, TypeError):
        return None


def _cache_path(root: Path) -> Path:
    p = root / CACHE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_cache(root: Path = Path(".")) -> Dict[str, Any]:
    """Load the enrichment cache from disk."""
    path = _cache_path(root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _cached_at_key(record: Any) -> str:
    """Sort key for merge: the record's ``cached_at`` ISO string ('' when absent)."""
    if isinstance(record, dict):
        return str(record.get("cached_at") or "")
    return ""


def _hot_key(record: Any) -> str:
    """When the record's hot fields were last fetched: the newer of ``hot_cached_at`` and ``cached_at``."""
    if isinstance(record, dict):
        return max(str(record.get("hot_cached_at") or ""), str(record.get("cached_at") or ""))
    return ""


def merge_cache_records(on_disk: Dict[str, Any], mine: Dict[str, Any]) -> Dict[str, Any]:
    """Union of two cache snapshots; per ticker the record with the newer ``cached_at`` wins.

    Pure. A ticker present on only one side is kept. On a tie ``mine`` wins (it is the
    writer's latest view). Nothing is dropped here: the cache only grows or refreshes.

    Scalp hot tier (2026-10-10): when the losing side carries a NEWER hot stamp (``hot_cached_at``) than the
    winner's, its HOT_FIELDS and ``hot_cached_at`` are carried onto the winner. A full refresh racing a hot
    refresh therefore keeps both: the six views from one, the fresher price/RVOL/gap from the other.
    """
    merged: Dict[str, Any] = dict(on_disk or {})
    for sym, rec in (mine or {}).items():
        old = merged.get(sym)
        if old is None:
            merged[sym] = rec
            continue
        win, lose = (rec, old) if _cached_at_key(rec) >= _cached_at_key(old) else (old, rec)
        if (isinstance(win, dict) and isinstance(lose, dict) and lose.get("hot_cached_at")
                and _hot_key(lose) > _hot_key(win)):
            win = dict(win)
            for f in HOT_FIELDS:
                if f in lose:
                    win[f] = lose[f]
            win["hot_cached_at"] = lose["hot_cached_at"]
        merged[sym] = win
    return merged


def save_cache(cache: Dict[str, Any], root: Path = Path(".")) -> None:
    """Save the enrichment cache: locked, merged, atomic (consolidation step 1, 2026-10-10).

    Before: ``write_text`` straight onto the live file. A reader that caught the file mid-write
    got a parse error, ``load_cache`` turned that into ``{}``, and that reader's later save then
    wrote a cache holding only its own few tickers -- the sweep log shows the cache shrinking
    4501 -> 38 -> 67 -> 4501 -> 48 entries, and every consumer refetched from Finviz
    (API_OVERLAP_CONSOLIDATION.md §2.2 A).

    Now: an exclusive ``fcntl`` lock on ``<cache>.lock`` serialises writers; under it the file on
    disk is re-read and merged with ``cache`` (newer ``cached_at`` wins per ticker, nothing is
    dropped), written to a temp file in the same directory, fsync'd and ``os.replace``'d over the
    cache. Readers see either the old file or the new one, never a torn one. The mode of an
    existing cache file is kept. This module stays the single writer of the file.
    """
    import fcntl
    import tempfile

    path = _cache_path(root)
    lock_path = path.with_name(path.name + ".lock")
    with open(lock_path, "a") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            on_disk: Dict[str, Any] = {}
            mode = None
            if path.is_file():
                mode = path.stat().st_mode & 0o777
                try:
                    loaded = json.loads(path.read_text())
                    on_disk = loaded if isinstance(loaded, dict) else {}
                except Exception:
                    on_disk = {}
            merged = merge_cache_records(on_disk, cache)
            fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
            try:
                with os.fdopen(fd, "w") as fh:
                    fh.write(json.dumps(merged, indent=2, default=str))
                    fh.flush()
                    os.fsync(fh.fileno())
                os.chmod(tmp, mode if mode is not None else 0o664)
                os.replace(tmp, path)
            except BaseException:
                # our own temp file only; the live cache is untouched on this path
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            if isinstance(cache, dict):
                cache.clear()
                cache.update(merged)
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def _read_cache_readonly(root: Path) -> Dict[str, Any]:
    """load_cache() without _cache_path()'s mkdir -- the dry run creates nothing."""
    path = root / CACHE_FILE
    try:
        return json.loads(path.read_text()) if path.is_file() else {}
    except Exception:
        return {}


def _default_views(skip_fundamentals: bool = False) -> List[int]:
    views = [111, 121, 131, 141, 171]  # 121=valuation/EPS, skip 161 (fundamentals slow)
    if not skip_fundamentals:
        views.append(161)
    return views


def _stale_symbols(symbols: List[str], cache: Dict[str, Any], force_refresh: bool = False) -> List[str]:
    """Tickers that need refreshing: missing from the cache or older than CACHE_TTL_HOURS."""
    return [s for s in symbols
            if force_refresh or s not in cache or _is_stale(cache.get(s, {}))]


def _is_stale(record: Dict) -> bool:
    """Check if a cache record is stale."""
    cached_at = record.get("cached_at")
    if not cached_at:
        return True
    try:
        dt = datetime.fromisoformat(cached_at)
        return (datetime.now() - dt).total_seconds() > CACHE_TTL_HOURS * 3600
    except Exception:
        return True


def _fetch_view(tickers: List[str], view: int, root: Path, *, col_map: Optional[Dict[str, str]] = None,
                extra_query: str = "") -> Dict[str, Dict]:
    """Fetch one Finviz view for a batch of tickers (``col_map``/``extra_query``: the hot tier's custom export)."""
    _load_env(root)
    token = _env("FINVIZ_API_TOKEN")
    cookie = _env("FINVIZ_COOKIE")
    ua = _env("FINVIZ_USER_AGENT",
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

    results: Dict[str, Dict] = {}
    col_map = col_map if col_map is not None else VIEWS.get(view, {})
    # A CUSIP / ISIN / non-ticker never reaches Finviz (GAP 14): it is dropped here, the one HTTP site in
    # this module, and named once so the caller's universe can be fixed at the source.
    tickers, _rejected = _ticker_partition(tickers, "finviz")
    if _rejected:
        print(f"  [finviz-enrich] v={view} refused {len(_rejected)} non-ticker symbol(s): "
              f"{[r['symbol'] + ':' + r['reason'] for r in _rejected[:10]]}")

    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        ticker_str = ",".join(batch)

        # Build URL — try token auth first, fall back to cookie
        if token:
            url = f"{FINVIZ_EXPORT}?v={view}{extra_query}&t={ticker_str}&auth={token}"
            headers = {"User-Agent": ua}
        elif cookie:
            url = f"{FINVIZ_EXPORT}?v={view}{extra_query}&t={ticker_str}"
            headers = {"User-Agent": ua, "Cookie": cookie,
                       "Referer": "https://elite.finviz.com/"}
        else:
            print(f"  [finviz-enrich] No auth for v={view} — skipping")
            continue

        try:
            try:
                from finviz_throttle import acquire as _fv_acquire, cooldown as _fv_cd
            except Exception:
                _fv_acquire = lambda: None
                _fv_cd = lambda *_a: None
            _fv_acquire()
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code == 429:
                # propagate the global cooldown so every Finviz caller backs off, then retry once
                _fv_cd(float(resp.headers.get('Retry-After') or 60))
                print(f"  [finviz-enrich] Rate limit v={view} — global cooldown, waiting 30s")
                time.sleep(30)
                _fv_acquire()
                resp = requests.get(url, headers=headers, timeout=20)
                if resp.status_code == 429:
                    _fv_cd(float(resp.headers.get('Retry-After') or 60))
            if not resp.ok:
                print(f"  [finviz-enrich] v={view} HTTP {resp.status_code}")
                continue

            # The header is the authority on column order, so parse it instead of
            # discarding it. csv.reader (not str.split(",")) because a quoted
            # field may legitimately contain a comma -- "Alphabet, Inc." would
            # otherwise split into two and shift every column after it.
            rows = list(csv.reader(io.StringIO(resp.text)))
            if not rows:
                print(f"  [finviz-enrich] v={view} empty response")
                continue
            header = [h.strip().strip('"') for h in rows[0]]
            index_of = {name: i for i, name in enumerate(header)}

            # An expected column that is absent is reported once, loudly, and
            # then left unset. It is never back-filled from a neighbouring
            # position: that is precisely how "Performance (10 Years)" came to
            # be stored as an analyst recommendation for five months.
            # an alias whose field another present header already supplies is not missing (hot custom export)
            present_fields = {f for c, f in col_map.items() if c in index_of}
            missing = [c for c in col_map if c not in index_of and col_map[c] not in present_fields]
            if missing:
                print(f"  [finviz-enrich] v={view} SCHEMA DRIFT — columns absent "
                      f"from the Finviz header, fields left unset: {missing}")
            if "Ticker" not in index_of:
                print(f"  [finviz-enrich] v={view} has no Ticker column — skipping view")
                continue
            tkr_i = index_of["Ticker"]

            for parts in rows[1:]:
                if len(parts) < 2 or tkr_i >= len(parts):
                    continue
                sym = parts[tkr_i].strip().strip('"').upper()
                if not sym:
                    continue
                record: Dict[str, Any] = {}
                for col_name, field in col_map.items():
                    if field in SKIP_DUPLICATES:
                        continue
                    idx = index_of.get(col_name)
                    if idx is None or idx >= len(parts):
                        continue
                    raw = parts[idx].strip().strip('"')
                    if field in PCT_FIELDS:
                        record[field] = _parse_float(raw)
                    elif field in ("ticker", "company", "sector", "industry",
                                   "country", "earnings_date", "earnings_time",
                                   "earnings_date2", "recom"):
                        record[field] = raw if raw and raw != "-" else None
                    else:
                        record[field] = _parse_float(raw)
                results[sym] = record

        except Exception as e:
            print(f"  [finviz-enrich] v={view} batch error: {e}")

        time.sleep(REQUEST_DELAY)

    return results


def enrich_tickers(
    symbols: List[str],
    project_root: str = ".",
    views: Optional[List[int]] = None,
    force_refresh: bool = False,
    skip_fundamentals: bool = False,
) -> Dict[str, Dict]:
    """
    Enrich a list of tickers with all Finviz views.
    Uses cache — only fetches tickers that are missing or stale.

    Args:
        symbols: List of ticker symbols
        project_root: Project root path
        views: List of view numbers to fetch (default: all 5)
        force_refresh: Force refresh even if cache is fresh
        skip_fundamentals: Skip v=161 (fundamentals) for speed

    Returns:
        Dict of {symbol: enriched_data}
    """
    root = Path(project_root)
    cache = load_cache(root)

    if views is None:
        views = _default_views(skip_fundamentals)

    # Not a ticker -> no request and no cache record (GAP 14: 12507E201 was cached as a symbol).
    requested = len(symbols)
    symbols, rejected = _ticker_partition(symbols, "finviz")
    if rejected:
        print(f"  [finviz-enrich] refused {len(rejected)} non-ticker symbol(s) before any request: "
              f"{[r['symbol'] + ':' + r['reason'] for r in rejected[:10]]}")

    # Find tickers that need refreshing
    stale = _stale_symbols(symbols, cache, force_refresh)
    _RUN_STATS.clear()
    _RUN_STATS.update({"symbols": requested, "stale": len(stale), "views": {},
                       "rejected_non_ticker": len(rejected)})

    if stale:
        print(f"  [finviz-enrich] Fetching {len(stale)} tickers "
              f"({len(symbols)-len(stale)} cached) views={views}")

        # Fetch each view and merge
        view_results: Dict[int, Dict[str, Dict]] = {}
        for v in views:
            vr = _fetch_view(stale, v, root)
            view_results[v] = vr
            _RUN_STATS["views"][v] = len(vr)
            print(f"  [finviz-enrich] v={v}: {len(vr)} tickers")

        # Merge all views per ticker
        now_str = datetime.now().isoformat()
        for sym in stale:
            merged: Dict[str, Any] = {"symbol": sym, "cached_at": now_str}
            for v in views:
                vdata = view_results.get(v, {}).get(sym, {})
                merged.update(vdata)

            # Derived fields
            merged["float_m"] = merged.get("float_m") or 0.0
            # 2026-09-28: Finviz "Market Cap" is stored under market_cap_b in MILLIONS (AAPL 4967858.67).
            # Publish an unambiguous market_cap_usd next to it; readers prefer it (lib/finviz_csv).
            try:
                _mc_m = merged.get("market_cap_b")
                merged["market_cap_usd"] = round(float(_mc_m) * 1_000_000, 2) if _mc_m not in (None, "", 0) else None
            except (TypeError, ValueError):
                merged["market_cap_usd"] = None
            merged["rvol"] = merged.get("rvol") or 0.0
            merged["rsi"] = merged.get("rsi")
            merged["sma20_pct"] = merged.get("sma20_pct")
            merged["sma50_pct"] = merged.get("sma50_pct")
            merged["sma200_pct"] = merged.get("sma200_pct")

            # Derived: price vs MA levels
            price = merged.get("price") or 0
            if price and merged.get("sma200_pct") is not None:
                sma200 = price / (1 + merged["sma200_pct"] / 100) if merged["sma200_pct"] != -100 else None
                merged["sma200_price"] = round(sma200, 2) if sma200 else None
            if price and merged.get("sma50_pct") is not None:
                sma50 = price / (1 + merged["sma50_pct"] / 100) if merged["sma50_pct"] != -100 else None
                merged["sma50_price"] = round(sma50, 2) if sma50 else None
            if price and merged.get("sma20_pct") is not None:
                sma20 = price / (1 + merged["sma20_pct"] / 100) if merged["sma20_pct"] != -100 else None
                merged["sma20_price"] = round(sma20, 2) if sma20 else None

            # RSI classification
            rsi = merged.get("rsi")
            if rsi is not None:
                if rsi >= 70:
                    merged["rsi_status"] = "overbought"
                elif rsi <= 30:
                    merged["rsi_status"] = "oversold"
                else:
                    merged["rsi_status"] = "neutral"
            else:
                merged["rsi_status"] = "unknown"

            # Trend classification from SMA stack
            s20 = merged.get("sma20_pct")
            s50 = merged.get("sma50_pct")
            s200 = merged.get("sma200_pct")
            if all(x is not None for x in [s20, s50, s200]):
                if s20 > 0 and s50 > 0 and s200 > 0:
                    merged["trend"] = "uptrend"
                elif s20 < 0 and s50 < 0 and s200 < 0:
                    merged["trend"] = "downtrend"
                elif s200 > 0:
                    merged["trend"] = "above_200"
                else:
                    merged["trend"] = "below_200"
            else:
                merged["trend"] = "unknown"

            recom_raw = merged.get("recom")
            if recom_raw is not None:
                score, rating, reason = _classify_recom(recom_raw)
                merged["recom_score"] = score
                merged["analyst_rating"] = rating
                merged["recom_reject_reason"] = reason
                if reason:
                    print(
                        f"  [finviz-enrich] recom refused for {sym}: "
                        f"{recom_raw!r} ({reason})"
                    )

            cache[sym] = merged

        save_cache(cache, root)
        print(f"  [finviz-enrich] Cache saved — {len(cache)} tickers total")

        # === IER WRITE-BACK (non-fatal) ===
        try:
            import psycopg2 as _pg2
            from intelligence_entity_manager import upsert_entity as _iem_upsert
            from datetime import datetime as _dt, timezone as _tz
            _pw = ""
            for _l in (root / ".env").read_text().splitlines():
                if _l.startswith("DB_PASSWORD="): _pw = _l.split("=", 1)[1].strip()
            _iem_conn = _pg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=_pw)
            for _sym in stale:
                _d = cache.get(_sym, {})
                if _d.get("price"):
                    _iem_upsert(_iem_conn, _sym, 'market', {
                        'current_price': float(_d['price']),
                        'rvol': float(_d['rvol']) if _d.get('rvol') else None,
                        'float_m': float(_d['float_m']) if _d.get('float_m') else None,
                        'atr_value': float(_d['atr']) if _d.get('atr') else None,
                        'sector': _d.get('sector'),
                        'industry': _d.get('industry'),
                        'price_updated_at': _dt.now(_tz.utc),
                    }, source='finviz')
            _iem_conn.close()
        except Exception:
            pass
        # === END WRITE-BACK ===

    # Return requested symbols from cache; a refused non-ticker is answered (never cached) so callers that
    # index by what they asked for still find a key, and the reason says why there is no data.
    out = {s: cache.get(s, {"symbol": s}) for s in symbols}
    for r in rejected:
        out.setdefault(r["symbol"], {"symbol": r["symbol"], "rejected_non_ticker": r["reason"]})
    return out


# ── Scalp hot tier (operator decision (4), 2026-10-10) ───────────────────────


def _hot_due(symbols: List[str], cache: Dict[str, Any], now: Optional[datetime] = None) -> List[str]:
    """Scalp symbols whose hot fields are missing or older than HOT_MIN_REFRESH_MIN (naive local stamps)."""
    ref = now or datetime.now()
    due = []
    for sym in symbols:
        key = _hot_key(cache.get(sym))
        try:
            fresh = bool(key) and (ref - datetime.fromisoformat(key)).total_seconds() < HOT_MIN_REFRESH_MIN * 60
        except ValueError:
            fresh = False
        if not fresh:
            due.append(sym)
    return due


def scalp_hot_plan(symbols: List[str], project_root: str = ".") -> Dict[str, Any]:
    """What a hot refresh would fetch. Reads the cache file only; no request, no write."""
    root = Path(project_root)
    cache = _read_cache_readonly(root)
    due = _hot_due(symbols, cache)
    return {"symbols": len(symbols), "due": len(due), "fresh_hot": len(symbols) - len(due),
            "view": HOT_VIEW, "columns": HOT_COLUMNS, "finviz_export_requests": -(-len(due) // BATCH_SIZE),
            "cache_file": str(root / CACHE_FILE), "due_first": due[:10]}


def enrich_scalp_hot(symbols: List[str], project_root: str = ".") -> Dict[str, Any]:
    """ONE custom-column export for the scalp names; merges the hot fields and stamps ``hot_cached_at``.

    ``cached_at`` is left as it was (absent for a name the six-view refresh never saw), so the 6 h full-refresh
    TTL still sees the record as stale/fresh exactly as before. Writes only through save_cache (single writer).
    """
    root = Path(project_root)
    cache = load_cache(root)
    due = _hot_due(symbols, cache)
    stats: Dict[str, Any] = {"symbols": len(symbols), "due": len(due), "requests": -(-len(due) // BATCH_SIZE),
                             "returned": 0}
    if not due:
        return stats
    got = _fetch_view(due, HOT_VIEW, root, col_map=HOT_COLUMN_MAP, extra_query=f"&c={HOT_COLUMNS}")
    stamp = datetime.now().isoformat()
    for sym, fields in got.items():
        if sym not in due:
            continue
        rec = dict(cache.get(sym) or {"symbol": sym})
        for f in HOT_FIELDS:
            if fields.get(f) is not None:
                rec[f] = fields[f]
        rec["hot_cached_at"] = stamp
        cache[sym] = rec
        stats["returned"] += 1
    if stats["returned"]:
        save_cache(cache, root)
    return stats


def _hot_libs():
    try:
        from lib import scalp_hot_tier as hot
        from lib.data_broker import scalp_list as sl
    except ImportError:  # imported as scripts.finviz_enrichment
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from lib import scalp_hot_tier as hot
        from lib.data_broker import scalp_list as sl
    return hot, sl


def main_scalp_hot(dry_run: bool, now: Optional[datetime] = None) -> int:
    """Lane ``finviz-enrichment-scalp-hot``. Inert unless the hot tier is enabled; market days 06:00-16:00 ET."""
    hot, sl = _hot_libs()
    flag = hot.flag_state()
    if not flag["enabled"]:
        print(json.dumps({"lane": HOT_LANE_ID, "status": "SKIPPED_FLAG_OFF", "hot_tier": flag}))
        return 0
    if not hot.in_window("enrichment", now):
        print(json.dumps({"lane": HOT_LANE_ID, "status": "SKIPPED_OFF_WINDOW", "phase": hot.phase(now)}))
        return 0
    lst = sl.get_scalp_list(now=now)
    symbols = list(lst.get("symbols") or [])[: hot.ENRICH_SYMBOL_CAP]
    if dry_run:
        plan = scalp_hot_plan(symbols, ".")
        plan.update(list_source=lst.get("list_source"), list_as_of=lst.get("as_of"), list_stale=lst.get("stale"))
        _receipt_lib().dry_run_report(HOT_LANE_ID, plan,
                                      would_write=[f"{plan['cache_file']} (hot fields of {plan['due']} tickers)"])
        return 0
    started = _receipt_lib().now_iso()
    try:
        stats = enrich_scalp_hot(symbols, ".")
    except Exception as exc:
        _receipt_lib().write_lane_receipt(HOT_LANE_ID, ok=False, exit_code=1, started_at=started,
                                          script="finviz_enrichment.py --scalp-hot",
                                          error=f"{type(exc).__name__}: {exc}")
        raise
    failed = stats["due"] > 0 and stats["returned"] == 0
    stats.update(list_source=lst.get("list_source"), list_as_of=lst.get("as_of"), symbols_list=symbols)
    _receipt_lib().write_lane_receipt(HOT_LANE_ID, ok=not failed, exit_code=int(failed), started_at=started,
                                      script="finviz_enrichment.py --scalp-hot", summary=stats)
    print(json.dumps({"lane": HOT_LANE_ID, "status": "FAILED" if failed else "OK", **stats}, default=str))
    return 1 if failed else 0


def get_enriched(symbol: str, project_root: str = ".") -> Dict:
    """Get enriched data for a single ticker from cache."""
    cache = load_cache(Path(project_root))
    return cache.get(symbol.upper(), {"symbol": symbol})


def enrich_portfolio_holdings(
    holdings: List[Dict],
    project_root: str = ".",
    include_fundamentals: bool = True,
) -> Dict[str, Dict]:
    """
    Enrich all portfolio holdings.
    Skips CASH, mutual funds, and proprietary Fidelity symbols.

    Args:
        holdings: List of holding dicts from holdings.json
        project_root: Project root path
        include_fundamentals: Include v=161 fundamentals data

    Returns:
        Dict of {symbol: enriched_data}
    """
    SKIP_SYMBOLS = {"CASH", "--", "SNSXX", "SWVXX", "SPRXX", "VMFXX", "FDRXX"}

    symbols = []
    for h in holdings:
        sym = h.get("symbol", "")
        if not sym or sym in SKIP_SYMBOLS:
            continue
        if "-" in sym and len(sym) > 5:  # Fidelity proprietary
            continue
        symbols.append(sym.upper())

    symbols = list(set(symbols))  # deduplicate
    print(f"  [finviz-enrich] Portfolio: enriching {len(symbols)} symbols")
    return enrich_tickers(symbols, project_root,
                          skip_fundamentals=not include_fundamentals)


def get_rsi(symbol: str, project_root: str = ".") -> Optional[float]:
    """Quick accessor for RSI without loading full cache."""
    return get_enriched(symbol, project_root).get("rsi")


def get_float_m(symbol: str, project_root: str = ".") -> Optional[float]:
    """Quick accessor for float in millions."""
    return get_enriched(symbol, project_root).get("float_m")


def get_rvol(symbol: str, project_root: str = ".") -> Optional[float]:
    """Quick accessor for relative volume."""
    return get_enriched(symbol, project_root).get("rvol")


def print_enriched(symbol: str, project_root: str = ".") -> None:
    """Pretty print enriched data for a ticker."""
    data = get_enriched(symbol, project_root)
    if not data.get("cached_at"):
        print(f"{symbol}: not in cache")
        return
    print(f"\n{symbol} — enriched {data.get('cached_at','?')[:16]}")
    print(f"  Price: ${data.get('price','?')} | Change: {data.get('change_pct','?')}%")
    print(f"  Float: {data.get('float_m','?')}M | RVOL: {data.get('rvol','?')}x")
    print(f"  RSI: {data.get('rsi','?')} ({data.get('rsi_status','?')})")
    print(f"  SMA20: {data.get('sma20_pct','?')}% | SMA50: {data.get('sma50_pct','?')}% | SMA200: {data.get('sma200_pct','?')}%")
    print(f"  Trend: {data.get('trend','?')} | Beta: {data.get('beta','?')}")
    print(f"  Short Float: {data.get('short_float_pct','?')}% | Inst Own: {data.get('inst_own_pct','?')}%")
    print(f"  Perf 1W: {data.get('perf_week_pct','?')}% | YTD: {data.get('perf_ytd_pct','?')}%")


DEFAULT_UNIVERSE_CAP = 200  # matches WATCHLIST_TOP_N (scripts/lib/watchlist_priority.py)


def default_universe_symbols(project_root: str = ".", *, cap: int = DEFAULT_UNIVERSE_CAP,
                             readonly: bool = False) -> list:
    """Audit finding M4: the two finviz_enrichment.py cron entries (07:10,
    formerly also 13:00) invoke this script bare, no argv — which silently
    fell through to a hardcoded 4-symbol demo list (MAMO/ACHV/V/SCHD) every
    single run, for months, printing "Price: $?" the whole time.

    This is the real default: `status='active'` watchlist symbols
    (stalest-enriched-first, capped) plus every current holding
    (uncapped — a real position always gets refreshed). `status='researched'`
    is deliberately EXCLUDED: it's a ~5,800-row discovery/history pool, not a
    curated watchlist — an earlier version of this fix queried active+researched
    unfiltered and returned 5,260 symbols, which at Finviz's documented
    ~100 req/hour, 20-tickers/batch, 5-views-per-batch limit would have taken
    over 13 hours and risked the API key getting rate-limited or blocked. The
    cap matches WATCHLIST_TOP_N, the same number scripts/watchlist_enrichment_sweep.py
    already uses safely for this exact API.

    Best-effort: a DB error returns an empty list rather than raising, so a
    cron failure here degrades to "nothing enriched this run," not a crash.
    The failure is recorded in _UNIVERSE_ERRORS (the lane exits 1 on it).
    ``readonly=True`` (the dry run) puts the session in READ ONLY at the server.
    """
    root = Path(project_root)
    symbols: set = set()
    _UNIVERSE_ERRORS.clear()
    try:
        import psycopg2
        pw = ""
        env_path = root / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("DB_PASSWORD="):
                    pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        if readonly:
            _receipt_lib().enforce_readonly(conn)
        cur = conn.cursor()
        cur.execute("""SELECT symbol FROM watchlist_items
                       WHERE status = 'active' AND symbol IS NOT NULL
                       ORDER BY last_enriched_at ASC NULLS FIRST
                       LIMIT %s""", (cap,))
        symbols.update(r[0] for r in cur.fetchall() if r[0])
        cur.close()
        conn.close()
    except Exception as exc:
        print(f"  [finviz-enrich] watchlist symbol query failed (non-fatal): {exc}")
        _UNIVERSE_ERRORS.append(f"watchlist_items: {type(exc).__name__}")

    try:
        holdings_path = root / "data" / "portfolios" / "state" / "holdings.json"
        if holdings_path.exists():
            holdings = json.loads(holdings_path.read_text())
            for h in holdings.get("holdings", []):
                sym = h.get("symbol", "")
                if sym and not h.get("is_cash"):
                    symbols.add(sym)
    except Exception as exc:
        print(f"  [finviz-enrich] holdings symbol read failed (non-fatal): {exc}")

    return sorted(symbols)


def dry_run_plan(symbols: List[str], project_root: str = ".") -> Dict[str, Any]:
    """What a real run would fetch and write. Reads the cache file only; no request, no write."""
    root = Path(project_root)
    cache = _read_cache_readonly(root)
    views = _default_views()
    stale = _stale_symbols(symbols, cache)
    batches = -(-len(stale) // BATCH_SIZE)
    return {"symbols": len(symbols), "stale": len(stale), "fresh_in_cache": len(symbols) - len(stale),
            "cache_file": str(root / CACHE_FILE), "cache_exists": (root / CACHE_FILE).is_file(),
            "cache_tickers": len(cache), "views": views,
            "finviz_export_requests": batches * len(views), "stale_first": stale[:10],
            "universe_errors": list(_UNIVERSE_ERRORS)}


def main() -> int:
    import sys
    dry_run = "--dry-run" in sys.argv
    if "--scalp-hot" in sys.argv:
        return main_scalp_hot(dry_run)
    _UNIVERSE_ERRORS.clear()  # explicit argv skips default_universe_symbols(); never carry a stale error
    if dry_run:
        sys.argv = [a for a in sys.argv if a != "--dry-run"]
    symbols = sys.argv[1:] if len(sys.argv) > 1 else default_universe_symbols(".", readonly=dry_run)
    if dry_run:
        # Structural (AGENTS.md §6): returns before run_start, enrich_tickers, save_cache and the IER write-back.
        plan = dry_run_plan(symbols, ".")
        _receipt_lib().dry_run_report(
            LANE_ID, plan,
            would_write=[f"{plan['cache_file']} ({plan['stale']} tickers refreshed)",
                         f"intelligence entities 'market' upsert (<= {plan['stale']}, tickers with a price)",
                         "pipeline_runs row (run_start)"])
        return 1 if _UNIVERSE_ERRORS else 0
    if not symbols:
        print("No symbols to enrich (empty argv and empty default universe) — nothing to do.")
        failed = bool(_UNIVERSE_ERRORS)
        _receipt_lib().write_lane_receipt(LANE_ID, ok=not failed, exit_code=int(failed), script="finviz_enrichment.py",
                                          summary={"symbols": 0, "universe_errors": list(_UNIVERSE_ERRORS)})
        return 1 if failed else 0
    print(f"Running finviz_enrichment.py for {len(symbols)} symbol(s)"
          + (f": {symbols}" if len(symbols) <= 10 else f" (first 10: {symbols[:10]})"))

    started = _receipt_lib().now_iso()
    _run_id = None
    try:
        from pipeline_registry import run_start, run_complete, run_fail
        _run_id = run_start('finviz_enrichment')
    except Exception:
        pass

    try:
        _RUN_STATS.clear()
        results = enrich_tickers(symbols, project_root=".")
        _enriched = sum(1 for v in results.values() if v) if isinstance(results, dict) else len(symbols)
        for sym in symbols:
            print_enriched(sym)
        try:
            if _run_id: run_complete(_run_id, rows_processed=_enriched)
        except Exception:
            pass
    except Exception as _e:
        try:
            if _run_id: run_fail(_run_id, str(_e))
        except Exception:
            pass
        _receipt_lib().write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                          script="finviz_enrichment.py", error=f"{type(_e).__name__}: {_e}")
        raise
    stale = int(_RUN_STATS.get("stale") or 0)
    view_counts = dict(_RUN_STATS.get("views") or {})
    nothing_fetched = stale > 0 and not any(view_counts.values())
    failed = nothing_fetched or bool(_UNIVERSE_ERRORS)
    rc = 1 if failed else 0
    _receipt_lib().write_lane_receipt(LANE_ID, ok=not failed, exit_code=rc, started_at=started,
                                      script="finviz_enrichment.py",
                                      summary={"symbols": len(symbols), "stale": stale,
                                               "views": {str(k): v for k, v in view_counts.items()},
                                               "nothing_fetched": nothing_fetched,
                                               "universe_errors": list(_UNIVERSE_ERRORS)})
    return rc


if __name__ == "__main__":
    import sys
    sys.exit(main())
