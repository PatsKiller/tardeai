"""
portfolio_performance_history.py — Transaction-Based Historical Performance
Reconstructs portfolio value at historical dates using:
  1. Schwab transaction logs (buy/sell/transfer history)
  2. Yahoo Finance closing prices for each holding at each target date
  3. Falls back to daily snapshots when available

Periods: 1D, 1W, 1M, 3M, 6M, YTD, 1Y
"""
from __future__ import annotations
try:
    from db_adapter import load_snapshots as _db_load_snapshots, load_price_cache as _db_load_price_cache
except ImportError:
    _db_load_snapshots = None
    _db_load_price_cache = None
import json, os
from collections import defaultdict
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Dict, Optional

# Share-changing transaction types
_ADDS    = {"buy", "reinvest_shares", "transfer_in"}
_REMOVES = {"sell"}
_EITHER  = {"journaled_shares", "transfer", "internal_transfer"}

# ─── Helpers ────────────────────────────────────────────────────────────────

def _txn_applies(txn_type: str, qty: float) -> tuple[str, float]:
    """Return ('add'|'remove'|'skip', abs_qty) for a transaction."""
    tt = txn_type.lower().replace(" ", "_").replace("-", "_")
    # Explicit add
    if any(k in tt for k in ["buy", "reinvest_share", "qual_div_reinvest",
                               "long_term_cap_gain_reinvest"]):
        return "add", abs(qty)
    # Explicit remove
    if "sell" in tt:
        return "remove", abs(qty)
    # Transfers — sign of qty determines direction
    if any(k in tt for k in ["journal", "transfer", "internal"]):
        return ("add" if qty > 0 else "remove"), abs(qty)
    return "skip", 0.0


def _holdings_at(txns: list, target: str,
                current_holdings: Dict[str, float] = None) -> Dict[str, float]:
    """
    Return {symbol: shares} as of target date using BACKWARD reconstruction.
    Starts from current known holdings and UNDOES transactions after target date.
    This correctly handles shares acquired before the transaction history begins
    (e.g. V held since pre-2022, Fidelity 401k funds with no transaction CSV).
    """
    if current_holdings:
        # Backward: start from now and undo post-target transactions
        h: Dict[str, float] = {s: q for s, q in current_holdings.items() if q > 0}
        for t in txns:
            if t.get("date", "") <= target:
                continue  # before or on target date — don't undo
            sym = t.get("symbol", "").strip().upper()
            qty = float(t.get("quantity") or 0)
            if not sym or qty == 0:
                continue
            action, adj = _txn_applies(t.get("txn_type", ""), qty)
            # REVERSE the action (undo what happened after target)
            if action == "add":
                h[sym] = max(0, h.get(sym, 0) - adj)  # undo add = subtract
            elif action == "remove":
                h[sym] = h.get(sym, 0) + adj           # undo remove = add back
        return {s: q for s, q in h.items() if q > 0.001}
    else:
        # Forward fallback: build from transactions (less accurate)
        h2: Dict[str, float] = defaultdict(float)
        for t in txns:
            if t.get("date", "") > target:
                continue
            sym = t.get("symbol", "").strip().upper()
            qty = float(t.get("quantity") or 0)
            if not sym or qty == 0:
                continue
            action, adj = _txn_applies(t.get("txn_type", ""), qty)
            if action == "add":
                h2[sym] += adj
            elif action == "remove":
                h2[sym] = max(0, h2[sym] - adj)
        return {s: q for s, q in h2.items() if q > 0.001}


# Symbols confirmed delisted — skip Yahoo lookups, value = $0
_DELISTED = frozenset(['SGBX','CDEX','LPIH','SRNE','MEMI','ACHV','AGMH','AIRE','ALXO',
                       'AUUD','AXTI','BNAI','12507E201','628518102'])

# Cash-equivalent symbols — always $1.00/share regardless of Yahoo price
# Schwab exports "CASH" as a placeholder; SWVXX/SWGXX are money-market funds
_CASH_EQUIV = frozenset(['CASH', 'SWVXX', 'SWGXX', 'SNSXX', 'MMDA1', 'MMDA10',
                         'GABXX', 'FDRXX', 'SPRXX', 'VMMXX', 'VMFXX'])

def _yahoo_prices_from_cache(symbols: list, target: str,
                              price_cache: Dict) -> Dict[str, float]:
    """Look up closing prices from pre-built cache (instant, no network)."""
    result = {}
    for sym in symbols:
        prices = price_cache.get(sym, {})
        if not prices:
            continue
        avail = sorted(d for d in prices if d <= target)
        if avail:
            result[sym] = prices[avail[-1]]
    return result


def _yahoo_prices(symbols: list, target: str) -> Dict[str, float]:
    """Fetch closing prices for symbols on or before target date via yfinance."""
    try:
        import yfinance as yf
        import logging, warnings
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        warnings.filterwarnings("ignore")
        dt = datetime.strptime(target, "%Y-%m-%d")
        start = (dt - timedelta(days=7)).strftime("%Y-%m-%d")
        end   = (dt + timedelta(days=1)).strftime("%Y-%m-%d")

        # Filter out junk symbols, delisted, and cash-equivalents (always $1.00)
        clean = [s for s in symbols if len(s) <= 6 and s.replace("-","").isalpha()
                 and s not in _DELISTED and s not in _CASH_EQUIV]
        if not clean:
            return {}

        hist = yf.download(clean, start=start, end=end,
                           progress=False, auto_adjust=True,
                           group_by="ticker", threads=True)
        prices = {}
        for sym in clean:
            try:
                if len(clean) == 1:
                    col = hist["Close"] if "Close" in hist else hist[sym]["Close"]
                else:
                    col = hist[sym]["Close"]
                col.index = [d.date() if hasattr(d, "date") else d for d in col.index]
                target_dt = dt.date()
                avail = sorted(d for d in col.index if d <= target_dt)
                if avail:
                    prices[sym] = round(float(col[avail[-1]]), 4)
            except Exception:
                pass
        return prices
    except Exception:
        return {}


def _unpriceable_account_value(portfolio: Dict) -> float:
    """
    Return the total current value of accounts whose holdings use
    non-Yahoo-priceable symbols (e.g. Fidelity 401k with internal fund codes).
    Detection: any account where ALL holdings have shares == 0 and market_value > 0.
    These accounts are included as a lump-sum in historical reconstruction because
    their value cannot be reconstructed position-by-position via Yahoo Finance.
    NOTE: This assumes the 401k value is relatively stable week-to-week,
    which is accurate enough for period-return calculations.
    """
    acct_summaries = portfolio.get("account_summaries", {})
    holdings = portfolio.get("holdings", [])

    # Group holdings by account
    acct_holdings: Dict[str, list] = {}
    for h in holdings:
        acct = h.get("account", "")
        acct_holdings.setdefault(acct, []).append(h)

    lump_sum = 0.0
    for acct, acct_val in acct_summaries.items():
        val = float(acct_val.get("total_value") or acct_val.get("value") or 0)
        if val <= 0:
            continue
        acct_h = acct_holdings.get(acct, [])
        if not acct_h:
            # Account in summaries but no holdings — include as lump sum
            lump_sum += val
            continue
        # Check if ALL non-loan holdings have shares == None/0
        # (indicates proprietary fund codes — cant price via Yahoo)
        # Exclude loan entries which carry a synthetic share count of 1
        priceable = [
            h for h in acct_h
            if not h.get("is_loan")
            and "LOAN" not in h.get("symbol", "").upper()
        ]
        all_zero_shares = bool(priceable) and all(
            float(h.get("shares") or h.get("quantity") or 0) == 0
            for h in priceable
        )
        if all_zero_shares:
            lump_sum += val

    return lump_sum


def _portfolio_value_at(txns: list, target_date: str,
                         price_cache: Dict[str, Dict[str, float]],
                         yahoo_cache: Dict = None,
                         portfolio: Dict = None) -> Optional[float]:
    """Compute estimated portfolio value at target_date.
    Uses backward reconstruction from current holdings + price cache.
    Accounts with non-priceable symbols (e.g. Fidelity 401k internal fund codes)
    are included as a current-value lump sum — accurate for short periods (1W/1M).
    yahoo_cache = persistent price history {sym: {date: price}}
    portfolio   = full portfolio dict (for current holdings baseline)
    """
    # Accounts with proprietary fund codes (shares=0) — add as lump sum
    # These can't be priced via Yahoo; use current account value as approximation
    lump_sum = _unpriceable_account_value(portfolio)

    # Build current holdings flat dict {symbol: total_shares across all accounts}
    curr = {}
    for h in portfolio.get("holdings", []):
        s = h.get("symbol", "").strip().upper()
        q = float(h.get("shares") or h.get("quantity") or 0)
        if s and q > 0:
            curr[s] = curr.get(s, 0) + q

    holdings = _holdings_at(txns, target_date, curr)
    if not holdings and lump_sum == 0:
        return None

    # Source 1: pre-built Yahoo price cache (instant)
    if yahoo_cache:
        prices = _yahoo_prices_from_cache(list(holdings.keys()), target_date, yahoo_cache)
        if len(prices) >= max(1, len(holdings) * 0.4):
            # Good enough coverage from cache
            pass
        else:
            # Supplement with live Yahoo for missing symbols
            missing = [s for s in holdings if s not in prices]
            if missing:
                if target_date not in price_cache:
                    price_cache[target_date] = _yahoo_prices(missing, target_date)
                prices.update(price_cache.get(target_date, {}))
    else:
        # Fetch prices (cached per date)
        if target_date not in price_cache:
            price_cache[target_date] = _yahoo_prices(list(holdings.keys()), target_date)
        prices = price_cache[target_date]

    total = lump_sum  # Start with unpriceable account lump sum
    coverage = 0
    for sym, qty in holdings.items():
        # Cash-equivalent symbols: always $1.00/share — never trust Yahoo price
        if sym in _CASH_EQUIV:
            total += qty * 1.00
            coverage += 1
            continue
        # Delisted symbols: $0 value, don't count toward coverage
        if sym in _DELISTED:
            continue
        p = prices.get(sym)
        if p and p > 0:
            total += qty * p
            coverage += 1

    # Need at least 40% of VALUE covered (skip delisted/worthless)
    # Use count coverage but weight by what we could price
    # If we have a lump_sum, that alone satisfies minimum coverage
    if coverage == 0 and lump_sum == 0:
        return None
    if coverage < 3 and coverage < len(holdings) * 0.4 and lump_sum == 0:
        return None
    return round(total, 2)


# ─── Period definitions ──────────────────────────────────────────────────────

def _period_start_date(period: str, ref: date) -> Optional[date]:
    if period == "1D":
        return ref - timedelta(days=1)
    if period == "1W":
        return ref - timedelta(days=7)
    if period == "1M":
        return date(ref.year if ref.month > 1 else ref.year - 1,
                    ref.month - 1 if ref.month > 1 else 12, ref.day)
    if period == "3M":
        m = ref.month - 3
        y = ref.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        return date(y, m, min(ref.day, 28))
    if period == "6M":
        m = ref.month - 6
        y = ref.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        return date(y, m, min(ref.day, 28))
    if period == "YTD":
        return date(ref.year, 1, 1)
    if period == "1Y":
        return date(ref.year - 1, ref.month, ref.day)
    return None


# ─── Main entry point ────────────────────────────────────────────────────────

def compute_period_returns(portfolio: Dict, state_dir: Path) -> Dict:
    """
    Compute period returns using transaction history + price cache + Yahoo Finance.
    Uses pre-built price cache for fast reconstruction; falls back to live Yahoo.
    Returns dict consumed by _build_performance() in portfolio_dashboard.py
    """
    txns         = portfolio.get("transactions", [])
    current_val  = portfolio.get("total_value", 0.0) or 0.0
    today        = date.today()
    today_str    = today.strftime("%Y-%m-%d")

    # Load pre-built price cache (fast path — no network calls)
    try:
        from portfolio_price_cache import load_price_cache
        yahoo_cache = load_price_cache(state_dir)
        cached_syms = len([k for k in yahoo_cache if not k.startswith("_")])
        if cached_syms > 0:
            print(f"  [perf] Using price cache: {cached_syms} symbols")
        else:
            yahoo_cache = {}
            print(f"  [perf] Price cache empty — run portfolio_price_cache.py")
    except Exception:
        yahoo_cache = {}

    # ── Load existing snapshots (daily CSV drops) ─────────────────────────
    snap_dir = Path(state_dir) / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)

    # Save today's snapshot from current portfolio value
    snap_today = snap_dir / f"{today_str}.json"
    if not snap_today.exists() and current_val > 0:
        snap_today.write_text(json.dumps({
            "date": today_str,
            "total_value": current_val,
            "source": "live"
        }))

    # Read all snapshots (PostgreSQL on Linux, JSON files on Windows)
    snapshots: Dict[str, float] = {}
    if _db_load_snapshots:
        db_snaps = _db_load_snapshots(state_dir)
        if db_snaps:
            snapshots = db_snaps
    if not snapshots:
        for f in snap_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text())
                snapshots[d["date"]] = float(d["total_value"])
            except Exception:
                pass

    snap_count = len(snapshots)
    snap_dates = sorted(snapshots.keys())

    # ── Reconstruct historical values via Yahoo Finance ───────────────────
    price_cache: Dict[str, Dict] = {}
    periods = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y"]
    results = {}

    for period in periods:
        start_dt = _period_start_date(period, today)
        if start_dt is None:
            continue
        start_str = start_dt.strftime("%Y-%m-%d")

        # Source 1: exact snapshot match (±3 days)
        hist_val  = None
        src_label = None
        for delta in range(0, 4):
            for sign in [0, -1, 1]:
                candidate = (start_dt + timedelta(days=delta * sign)).strftime("%Y-%m-%d")
                if candidate in snapshots:
                    hist_val  = snapshots[candidate]
                    src_label = "snapshot"
                    break
            if hist_val:
                break

        # Source 2: transaction reconstruction via Yahoo Finance
        if hist_val is None and txns and period != "1D":
            # Only reconstruct if start_date is within our transaction history
            oldest_txn = min((t.get("date","9999") for t in txns), default="9999")
            if start_str >= oldest_txn:
                hist_val  = _portfolio_value_at(txns, start_str, price_cache, yahoo_cache, portfolio)
                src_label = "reconstructed"

        if hist_val and hist_val > 0 and current_val > 0:
            change     = round(current_val - hist_val, 2)
            change_pct = round((change / hist_val) * 100, 2)
            results[period] = {
                "period":      period,
                "start_date":  start_str,
                "start_value": hist_val,
                "end_value":   current_val,
                "change":      change,
                "change_pct":  change_pct,
                "source":      src_label,
            }
        else:
            results[period] = {
                "period":    period,
                "start_date": start_str,
                "change":    None,
                "change_pct": None,
                "source":    "pending",
                "note":      f"No data near {start_str} — accumulates over time"
            }

    # ── All-time from cost basis ──────────────────────────────────────────
    cost_basis = portfolio.get("total_cost_basis", 0)
    if cost_basis and cost_basis > 0 and current_val > 0:
        results["ALL"] = {
            "period":      "ALL",
            "start_value": cost_basis,
            "end_value":   current_val,
            "change":      round(current_val - cost_basis, 2),
            "change_pct":  round(((current_val - cost_basis) / cost_basis) * 100, 2),
            "source":      "cost_basis",
        }

    return {
        "periods":        results,
        "snapshot_count": snap_count,
        "snapshot_dates": snap_dates[-7:],
        "building":       [p for p, d in results.items() if d.get("source") == "pending"],
        "reconstructed":  [p for p, d in results.items() if d.get("source") == "reconstructed"],
        "current_value":  current_val,
        "has_data":       True,
    }
