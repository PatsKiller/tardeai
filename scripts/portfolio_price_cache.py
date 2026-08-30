"""
portfolio_price_cache.py — Price History Cache for Portfolio Intelligence
Downloads full OHLCV history for all held/held symbols from Yahoo Finance.
Saves to data/portfolios/state/price_cache.json for zero-latency pipeline use.

Run once manually, then weekly (Sunday 7PM via Task Scheduler).

Usage:
    python scripts/portfolio_price_cache.py                # build/refresh cache
    python scripts/portfolio_price_cache.py --force        # force re-download all
    python scripts/portfolio_price_cache.py --symbol V     # single symbol test
"""
from __future__ import annotations
import json, sys, os, time, argparse, logging
from datetime import datetime, date, timedelta
from pathlib import Path

# Load .env before db_adapter import so USE_DB evaluates correctly
# (systemd does NOT inherit shell environment)
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

try:
    from db_adapter import load_price_cache as _db_load_cache, save_price_cache as _db_save_cache
except ImportError:
    _db_load_cache = None
    _db_save_cache = None
from typing import Dict, List, Optional

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("peewee").setLevel(logging.CRITICAL)

# ── Constants ────────────────────────────────────────────────────────────────
CACHE_START     = "2020-01-01"          # Jan 1 2020 per user spec
STALE_DAYS      = 7                     # re-download if older than this
BATCH_SIZE      = 10                    # symbols per yfinance batch call
RETRY_DELAY     = 2.0                   # seconds between retries
MAX_RETRIES     = 2

DELISTED = frozenset([
    "SGBX","CDEX","LPIH","SRNE","MEMI","ACHV","AGMH","AIRE","ALXO",
    "AUUD","AXTI","BNAI","12507E201","628518102","MEMI","BOF","ACNB",
])

# Cash-equivalent symbols — always $1.00/share, never fetch from Yahoo
# Schwab exports "CASH" as a money-market placeholder; these are all NAV=$1.00
CASH_EQUIV = frozenset([
    "CASH", "SWVXX", "SWGXX", "SNSXX", "MMDA1", "MMDA10",
    "GABXX", "FDRXX", "SPRXX", "VMMXX", "VMFXX",
])

# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_clean(sym: str) -> bool:
    """Return True if symbol should be fetched."""
    if sym in DELISTED:
        return False
    if sym in CASH_EQUIV:
        return False  # Always $1.00 — no Yahoo fetch needed
    if len(sym) > 6:
        return False
    if not sym.replace("-","").isalpha():
        return False
    return True


def _all_symbols(portfolio: Dict, txns: List[Dict]) -> List[str]:
    """Collect every symbol ever held: current holdings + transaction history."""
    syms = set()
    for acct in portfolio.get("accounts", []):
        for h in acct.get("holdings", []):
            s = h.get("symbol","").strip().upper()
            if s: syms.add(s)
    for h in portfolio.get("holdings", []):
        s = h.get("symbol","").strip().upper()
        if s: syms.add(s)
    for t in txns:
        s = t.get("symbol","").strip().upper()
        if s: syms.add(s)
    clean = sorted(s for s in syms if _is_clean(s))
    return clean


def _load_cache(cache_path: Path) -> Dict:
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"_meta": {}}


def _save_cache(cache: Dict, cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, separators=(",", ":")),
        encoding="utf-8"
    )


def _is_stale(cache: Dict, sym: str, force: bool) -> bool:
    if force or sym not in cache:
        return True
    meta = cache.get("_meta", {}).get(sym, {})
    updated = meta.get("updated", "")
    if not updated:
        return True
    try:
        days_old = (date.today() - date.fromisoformat(updated)).days
        return days_old >= STALE_DAYS
    except Exception:
        return True


def _fetch_symbols(symbols: List[str], start: str, end: str) -> Dict[str, Dict[str, float]]:
    """Fetch closing prices for a batch of symbols. Returns {sym: {date_str: price}}."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import yfinance as yf

    results: Dict[str, Dict[str, float]] = {}
    if not symbols:
        return results

    for attempt in range(MAX_RETRIES + 1):
        try:
            if len(symbols) == 1:
                sym = symbols[0]
                hist = yf.download(sym, start=start, end=end,
                                   progress=False, auto_adjust=True,
                                   threads=False)
                if hist.empty:
                    return results
                close = hist["Close"]
                prices = {}
                for idx_val, price in close.items():
                    try:
                        d = idx_val.date() if hasattr(idx_val, "date") else idx_val
                        if float(price) > 0:
                            prices[str(d)] = round(float(price), 4)
                    except Exception:
                        pass
                if prices:
                    results[sym] = prices
            else:
                hist = yf.download(symbols, start=start, end=end,
                                   progress=False, auto_adjust=True,
                                   group_by="ticker", threads=True)
                if hist.empty:
                    return results
                for sym in symbols:
                    try:
                        col = hist[sym]["Close"] if sym in hist.columns.get_level_values(0) else None
                        if col is None or col.empty:
                            continue
                        prices = {}
                        for idx_val, price in col.items():
                            try:
                                d = idx_val.date() if hasattr(idx_val, "date") else idx_val
                                if float(price) > 0:
                                    prices[str(d)] = round(float(price), 4)
                            except Exception:
                                pass
                        if prices:
                            results[sym] = prices
                    except Exception:
                        pass
            return results
        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                continue
            print(f"  [cache] fetch error ({symbols}): {e}")
            return results

    return results


# ── Price lookup (used by other modules) ─────────────────────────────────────

def _quarantined_pairs_failsoft() -> set:
    """G-PRICE-01: load quarantine pairs; empty set if DB/table unavailable."""
    try:
        from scripts.lib.ticker_price_quarantine import load_quarantined_pairs_failsoft
        return load_quarantined_pairs_failsoft()
    except Exception:
        try:
            from lib.ticker_price_quarantine import load_quarantined_pairs_failsoft  # type: ignore
            return load_quarantined_pairs_failsoft()
        except Exception:
            return set()


def _apply_quarantine_to_cache(cache: Dict) -> Dict:
    """Strip quarantined (symbol, date) bars from a price cache dict."""
    q = _quarantined_pairs_failsoft()
    if not q:
        return cache
    try:
        from scripts.lib.ticker_price_quarantine import filter_price_cache
    except Exception:
        try:
            from lib.ticker_price_quarantine import filter_price_cache  # type: ignore
        except Exception:
            return cache
    return filter_price_cache(cache, q)


def get_price(sym: str, date_str: str, cache: Dict,
              fallback_live: bool = True) -> Optional[float]:
    """
    Look up closing price for sym on or before date_str.
    Uses cache first; optionally falls back to live Yahoo.

    G-PRICE-01: skip dates present in ticker_prices_quarantine.
    """
    sym = sym.upper()
    # Cash-equivalents are always $1.00 — never trust Yahoo
    if sym in CASH_EQUIV:
        return 1.00
    # Delisted are $0 — no lookup
    if sym in DELISTED:
        return 0.0

    quarantined = _quarantined_pairs_failsoft()
    try:
        from scripts.lib.ticker_price_quarantine import is_quarantined
    except Exception:
        try:
            from lib.ticker_price_quarantine import is_quarantined  # type: ignore
        except Exception:
            is_quarantined = None  # type: ignore

    prices = cache.get(sym, {})
    if prices:
        # Find closest date on or before target, skipping quarantined bars
        target = date_str
        avail = sorted(
            d for d in prices
            if d <= target and not (is_quarantined and is_quarantined(sym, d, quarantined))
        )
        if avail:
            return prices[avail[-1]]

    if not fallback_live or sym in DELISTED:
        return None

    # Live fallback (single date window) — still skip quarantine dates
    try:
        import warnings, yfinance as yf
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            start = (dt - timedelta(days=5)).strftime("%Y-%m-%d")
            end   = (dt + timedelta(days=2)).strftime("%Y-%m-%d")
            hist  = yf.download(sym, start=start, end=end,
                                progress=False, auto_adjust=True)
            if hist.empty:
                return None
            close = hist["Close"]
            avail = sorted(
                str(d.date() if hasattr(d, "date") else d)
                for d in close.index
            )
            avail_before = [
                d for d in avail
                if d <= date_str and not (is_quarantined and is_quarantined(sym, d, quarantined))
            ]
            if avail_before:
                price = float(close.iloc[avail.index(avail_before[-1])])
                return round(price, 4)
    except Exception:
        pass
    return None


def load_price_cache(state_dir: Path) -> Dict:
    """Load price cache. Uses PostgreSQL on Linux, JSON on Windows.

    G-PRICE-01: strip quarantined (symbol, date) bars after load (fail-soft).
    """
    if _db_load_cache:
        data = _db_load_cache(state_dir)
        if data and len([k for k in data if not k.startswith("_")]) > 0:
            return _apply_quarantine_to_cache(data)
    cache_path = Path(state_dir) / "price_cache.json"
    return _apply_quarantine_to_cache(_load_cache(cache_path))


# ── Main build/refresh logic ──────────────────────────────────────────────────

def build_price_cache(project_root: Path, force: bool = False,
                      single_symbol: str = None) -> Dict:
    root       = Path(project_root)
    state_dir  = root / "data" / "portfolios" / "state"
    cache_path = state_dir / "price_cache.json"

    print("\n============================================================")
    print("  Portfolio Price Cache Builder")
    print(f"  Start date: {CACHE_START} → today")
    print("============================================================\n")

    # Load existing cache
    cache = _load_cache(cache_path)
    meta  = cache.setdefault("_meta", {})

    # Load portfolio + transactions
    holdings_path = state_dir / "holdings.json"
    if not holdings_path.exists():
        print("  ❌ holdings.json not found — run pipeline first")
        return cache

    portfolio = json.loads(holdings_path.read_text())
    txns      = portfolio.get("transactions", [])

    # Collect symbols
    if single_symbol:
        symbols = [single_symbol.upper()]
    else:
        symbols = _all_symbols(portfolio, txns)

    # Filter to what needs updating
    to_fetch = [s for s in symbols if _is_stale(cache, s, force)]
    skipped  = [s for s in symbols if s not in to_fetch]

    print(f"  Total symbols:    {len(symbols)}")
    print(f"  Already cached:   {len(skipped)}")
    print(f"  Fetching:         {len(to_fetch)}")
    print(f"  Delisted skipped: {len([s for s in symbols if s in DELISTED])}")
    print()

    today_str = date.today().isoformat()
    end_date  = (date.today() + timedelta(days=1)).isoformat()

    # Determine start per symbol (full history vs incremental)
    done = 0
    errors = []

    for i in range(0, len(to_fetch), BATCH_SIZE):
        batch = to_fetch[i:i+BATCH_SIZE]

        # Split: full fetch vs incremental update
        full_fetch = [s for s in batch if s not in cache or force]
        incremental = [s for s in batch if s in cache and not force]

        # Full history fetch
        if full_fetch:
            print(f"  Fetching full history: {', '.join(full_fetch)}")
            results = _fetch_symbols(full_fetch, CACHE_START, end_date)
            for sym, prices in results.items():
                cache[sym] = prices
                meta[sym] = {"updated": today_str, "days": len(prices), "source": "yahoo"}
                print(f"    ✅ {sym}: {len(prices)} trading days ({min(prices)} → {max(prices)})")
            for sym in full_fetch:
                if sym not in results:
                    errors.append(sym)
                    print(f"    ⚠️  {sym}: no data returned")

        # Incremental (last 30 days only)
        if incremental:
            incr_start = (date.today() - timedelta(days=35)).isoformat()
            print(f"  Refreshing recent:   {', '.join(incremental)}")
            results = _fetch_symbols(incremental, incr_start, end_date)
            for sym, new_prices in results.items():
                cache.setdefault(sym, {}).update(new_prices)
                meta[sym] = {
                    "updated": today_str,
                    "days": len(cache[sym]),
                    "source": "yahoo"
                }
                print(f"    ✅ {sym}: +{len(new_prices)} new days (total {len(cache[sym])})")
            for sym in incremental:
                if sym not in results:
                    errors.append(sym)
                    print(f"    ⚠️  {sym}: no data")

        done += len(batch)

        # Save after each batch (resume-safe)
        meta["_cache_built"]     = today_str
        meta["_symbols_total"]   = done
        meta["_symbols_skipped"] = list(DELISTED & set(symbols))
        _save_cache(cache, cache_path)

        # Rate limit courtesy pause
        if i + BATCH_SIZE < len(to_fetch):
            time.sleep(0.5)

    # Final save
    meta["_cache_built"]     = today_str
    meta["_symbols_total"]   = len(symbols)
    meta["_symbols_skipped"] = list(DELISTED & set(symbols))
    meta["_errors"]          = errors
    _save_cache(cache, cache_path)
    # Also persist via db_adapter (PostgreSQL on Linux)
    if _db_save_cache:
        _db_save_cache(cache, state_dir)

    # Summary
    cached_syms = [k for k in cache if not k.startswith("_")]
    print(f"\n============================================================")
    print(f"  ✅ Cache complete")
    print(f"  Symbols cached:  {len(cached_syms)}")
    print(f"  Cache file:      {cache_path}")
    print(f"  Size:            {cache_path.stat().st_size/1024:.0f} KB")
    if errors:
        print(f"  Warnings:        {errors}")
    print("============================================================\n")

    return cache


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Portfolio Price Cache Builder")
    parser.add_argument("--project-root", default=".",
                        help="Project root directory")
    parser.add_argument("--force",  action="store_true",
                        help="Force re-download of all symbols")
    parser.add_argument("--symbol", default=None,
                        help="Download single symbol only (test mode)")
    args = parser.parse_args()

    build_price_cache(
        project_root  = args.project_root,
        force         = args.force,
        single_symbol = args.symbol,
    )
