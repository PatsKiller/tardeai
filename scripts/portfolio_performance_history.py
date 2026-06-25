""" portfolio_performance_history.py — Transaction-Based Historical Performance
Reconstructs portfolio value at historical dates using:
  1. Schwab transaction logs (buy/sell/transfer history)
  2. Yahoo Finance closing prices for each holding at each target date
  3. Falls back to daily snapshots when available

Fidelity 401k: proprietary symbols (FID-CONTRA-F, SP500-D, etc.) are mapped
to real Yahoo-priceable tickers via fidelity_ticker_map in portfolio_accounts.yaml.
This enables per-position pricing and correct period-return calculations.

Periods: 1D, 1W, 1M, 3M, 6M, YTD, 1Y
"""
from __future__ import annotations

import json, os
from collections import defaultdict
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Dict, Optional

# Share-changing transaction types
_ADDS    = {"buy", "reinvest_shares", "transfer_in"}
_REMOVES = {"sell"}
_EITHER  = {"journaled_shares", "transfer", "internal_transfer"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _txn_applies(txn_type: str, qty: float) -> tuple[str, float]:
    """Return ('add'|'remove'|'skip', abs_qty) for a transaction."""
    tt = txn_type.lower().replace(" ", "_").replace("-", "_")
    if any(k in tt for k in ["buy", "reinvest_share", "qual_div_reinvest",
                              "long_term_cap_gain_reinvest"]):
        return "add", abs(qty)
    if "sell" in tt:
        return "remove", abs(qty)
    if any(k in tt for k in ["journal", "transfer", "internal"]):
        return ("add" if qty > 0 else "remove"), abs(qty)
    return "skip", 0.0


def _holdings_at(txns: list, target: str,
                 current_holdings: Dict[str, float] = None) -> Dict[str, float]:
    """
    Return {symbol: shares} as of target date using BACKWARD reconstruction.
    Starts from current known holdings and UNDOES transactions after target date.
    """
    if current_holdings:
        h: Dict[str, float] = {s: q for s, q in current_holdings.items() if q > 0}
        for t in txns:
            if t.get("date", "") <= target:
                continue
            sym = t.get("symbol", "").strip().upper()
            qty = float(t.get("quantity") or 0)
            if not sym or qty == 0:
                continue
            action, adj = _txn_applies(t.get("txn_type", t.get("action", "")), qty)
            if action == "add":
                h[sym] = max(0, h.get(sym, 0) - adj)
            elif action == "remove":
                h[sym] = h.get(sym, 0) + adj
        return {s: q for s, q in h.items() if q > 0.001}
    else:
        h2: Dict[str, float] = defaultdict(float)
        for t in txns:
            if t.get("date", "") > target:
                continue
            sym = t.get("symbol", "").strip().upper()
            qty = float(t.get("quantity") or 0)
            if not sym or qty == 0:
                continue
            action, adj = _txn_applies(t.get("txn_type", t.get("action", "")), qty)
            if action == "add":
                h2[sym] += adj
            elif action == "remove":
                h2[sym] = max(0, h2[sym] - adj)
        return {s: q for s, q in h2.items() if q > 0.001}


# Symbols confirmed delisted — skip Yahoo lookups, value = $0
_DELISTED = frozenset([
    'SGBX','CDEX','LPIH','SRNE','MEMI','ACHV','AGMH','AIRE','ALXO',
    'AUUD','AXTI','BNAI','12507E201','628518102',
])

# Cash-equivalent symbols — always $1.00/share regardless of Yahoo price
_CASH_EQUIV = frozenset([
    'CASH','SWVXX','SWGXX','SNSXX','MMDA1','MMDA10',
    'GABXX','FDRXX','SPRXX','VMMXX','VMFXX',
])

# ── Fidelity proprietary fund symbol detection ────────────────────────────────
# These symbols are internal Fidelity/fund codes that do NOT trade on any
# public exchange.  They require translation via fidelity_ticker_map before
# Yahoo pricing can be attempted.
_PROPRIETARY_FUND_PREFIXES = (
    'FID-', 'SP500-', 'SS-', 'TRP-', 'VANG-', 'JPM-', 'WM-',
    'AB-', 'PIMCO-', 'MFS-', 'DODGE-', 'PUTNAM-', 'COLUMBIA-',
    'AMERICAN-', 'PGIM-', 'INVESCO-', 'OPPENHEIMER-',
)

def _is_proprietary_fund(symbol: str) -> bool:
    """Return True if symbol is a proprietary fund code (not directly Yahoo-priceable)."""
    if not symbol:
        return False
    s = symbol.upper()
    if '-' in s and len(s) > 6:
        return True
    return any(s.startswith(pfx) for pfx in _PROPRIETARY_FUND_PREFIXES)


def _load_fidelity_ticker_map(state_dir: Path) -> Dict[str, str]:
    """
    Load fidelity_ticker_map from assets/portfolio_accounts.yaml.
    Returns {internal_code: real_ticker}, e.g. {'FID-CONTRA-F': 'FCNTX'}.
    Falls back to a hardcoded set of common mappings if yaml unavailable.
    """
    # Try loading from portfolio_accounts.yaml (canonical source)
    try:
        import yaml
        # Walk up from state_dir to find project root, then assets/
        candidate = state_dir
        for _ in range(5):
            cfg = candidate / "assets" / "portfolio_accounts.yaml"
            if cfg.exists():
                raw = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
                m = raw.get("fidelity_ticker_map", {})
                if m:
                    return {str(k).upper(): str(v).upper() for k, v in m.items()}
            candidate = candidate.parent
    except Exception:
        pass

    # Hardcoded fallback covering the known Omnicom 401k funds
    return {
        'FID-CONTRA-F':   'FCNTX',
        'SP500-D':        'FXAIX',
        'SS-SMMD':        'SLYG',
        'TRP-LVAL':       'TILCX',
        'VANG-FTSE-SOC':  'VFTNX',
        'JPM-LGCG':       'JLGMX',
        'WM-BLAIR':       'WBIGX',
        'AB-DISC-Z':      'ABDZX',
        'FID-DIVINTL':    'FDIVX',
        'SS-GACEQ':       'SSGLX',
    }


# ── Price cache helpers ───────────────────────────────────────────────────────

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
        dt    = datetime.strptime(target, "%Y-%m-%d")
        start = (dt - timedelta(days=7)).strftime("%Y-%m-%d")
        end   = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
        # Only fetch symbols that are public tickers (not proprietary fund codes)
        clean = [
            s for s in symbols
            if len(s) <= 6
            and s.replace("-", "").isalpha()
            and s not in _DELISTED
            and s not in _CASH_EQUIV
            and not _is_proprietary_fund(s)
        ]
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


# ── Portfolio value at a historical date ─────────────────────────────────────

def _portfolio_value_at(
    txns: list,
    target_date: str,
    price_cache: Dict[str, Dict[str, float]],
    yahoo_cache: Dict = None,
    portfolio: Dict = None,
    fidelity_map: Dict[str, str] = None,
) -> Optional[float]:
    """
    Compute estimated portfolio value at target_date.

    APPROACH: Reprice CURRENT holdings at historical prices.
    No transaction reconstruction — avoids scalp trade noise.

    Fidelity 401k proprietary symbols are translated to their Yahoo-priceable
    equivalents via fidelity_map before pricing.  If a symbol has no mapping
    and no Yahoo price, the position's current market_value is used as a
    stable approximation (401k funds change slowly week-to-week).
    """
    fm = fidelity_map or {}

    # Build priceable holdings dict, translating proprietary symbols
    # Key: yahoo_symbol, Value: (shares, fallback_market_value)
    curr: Dict[str, tuple] = {}   # {yahoo_sym: (shares, mv_fallback)}
    fid_lump_fallback = 0.0       # sum of unmapped 401k positions

    for h in portfolio.get("holdings", []):
        raw_sym = (h.get("symbol") or "").strip().upper()
        q       = float(h.get("shares") or h.get("quantity") or 0)
        mv      = float(h.get("market_value") or 0)

        if not raw_sym or h.get("is_loan"):
            continue

        if raw_sym in _CASH_EQUIV:
            # Cash equiv: always price at $1.00
            curr[raw_sym] = (q if q > 0 else mv, mv)
            continue

        if _is_proprietary_fund(raw_sym):
            mapped = fm.get(raw_sym)
            if mapped:
                # Use mapped ticker with original share count
                curr[mapped] = (q if q > 0 else mv, mv)
            else:
                # No mapping — add as stable lump-sum fallback
                fid_lump_fallback += mv
            continue

        # Regular Yahoo-priceable symbol
        if q > 0:
            existing = curr.get(raw_sym)
            if existing:
                curr[raw_sym] = (existing[0] + q, existing[1] + mv)
            else:
                curr[raw_sym] = (q, mv)

    if not curr and fid_lump_fallback == 0:
        return None

    # Collect all symbols that need pricing
    price_syms = [s for s in curr if s not in _CASH_EQUIV and s not in _DELISTED]

    # 1. Look up from pre-built price cache
    prices = _yahoo_prices_from_cache(price_syms, target_date, yahoo_cache or {})

    # 2. Fetch missing from Yahoo
    missing = [s for s in price_syms if s not in prices and not _is_proprietary_fund(s)]
    if missing:
        if target_date not in price_cache:
            price_cache[target_date] = _yahoo_prices(missing, target_date)
        prices.update(price_cache.get(target_date, {}))

    # Compute total value
    total    = fid_lump_fallback   # any unmapped 401k positions
    coverage = 0
    missed_mv = 0.0

    for sym, (qty, mv_fallback) in curr.items():
        if sym in _CASH_EQUIV:
            total    += qty * 1.00
            coverage += 1
            continue
        if sym in _DELISTED:
            continue
        p = prices.get(sym)
        if p and p > 0:
            total    += qty * p
            coverage += 1
        else:
            # No price found — use current market value as stable approximation
            # (acceptable for 401k mutual funds that change slowly)
            missed_mv += mv_fallback

    # If we got prices for most positions, fill in the rest with current MV
    total_positions = len([s for s in curr if s not in _DELISTED])
    if total_positions > 0:
        coverage_ratio = coverage / total_positions
        if coverage_ratio >= 0.4:
            # Good enough coverage — add current MV for unpriced positions
            total += missed_mv
        elif coverage == 0 and fid_lump_fallback == 0:
            return None

    return round(total, 2)


# ── Period definitions ────────────────────────────────────────────────────────

def _period_start_date(period: str, ref: date) -> Optional[date]:
    if period == "1D":
        return ref - timedelta(days=1)
    if period == "1W":
        return ref - timedelta(days=7)
    if period == "1M":
        return date(
            ref.year if ref.month > 1 else ref.year - 1,
            ref.month - 1 if ref.month > 1 else 12,
            ref.day,
        )
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


# ── Main entry point ──────────────────────────────────────────────────────────

def compute_period_returns(portfolio: Dict, state_dir: Path) -> Dict:
    """
    Compute period returns using price cache + Yahoo Finance.
    Fidelity 401k proprietary symbols are mapped to real tickers for pricing.
    Returns dict consumed by _build_performance() / _build_period_returns()
    in portfolio_dashboard.py.
    """
    txns        = portfolio.get("trade_journal", portfolio.get("transactions", []))
    current_val = (
        portfolio.get("portfolio_totals", {}).get("total_value")
        or portfolio.get("total_value")
        or 0.0
    )
    today     = date.today()
    today_str = today.strftime("%Y-%m-%d")

    # Load Fidelity ticker map
    fidelity_map = _load_fidelity_ticker_map(Path(state_dir))
    if fidelity_map:
        mapped_str = ", ".join(f"{k}→{v}" for k, v in list(fidelity_map.items())[:5])
        print(f"  [perf] Fidelity map: {mapped_str}" +
              (f" + {len(fidelity_map)-5} more" if len(fidelity_map) > 5 else ""))

    # ── Load pre-built price cache ────────────────────────────────────────────
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

    # ── Snapshots ─────────────────────────────────────────────────────────────
    snap_dir = Path(state_dir) / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)

    snap_today = snap_dir / f"{today_str}.json"
    if not snap_today.exists() and current_val > 0:
        # Guard: check previous snapshot for >25% drift before writing
        _prev_snaps = sorted(snap_dir.glob("*.json"), key=lambda f: f.name, reverse=True)
        _write_ok = True
        for _pf in _prev_snaps[:3]:
            try:
                _pd = json.loads(_pf.read_text())
                _pv = float(_pd.get("total_value", 0))
                if _pv > 0:
                    _drift = abs(current_val - _pv) / _pv * 100
                    if _drift > 25:
                        print(f"  [perf] SNAPSHOT REJECTED: ${current_val:,.0f} vs prev ${_pv:,.0f} ({_drift:.1f}% drift > 25%)")
                        _write_ok = False
                    break
            except Exception:
                continue
        if _write_ok:
            snap_today.write_text(json.dumps({
                "date": today_str,
                "total_value": current_val,
                "source": "live",
            }))

    from portfolio_snapshot_sanity import (
        account_market_days,
        holding_phantom_corrections,
        load_snapshots_from_dir,
        portfolio_market_day,
        snapshot_period_return_reliable,
    )

    _raw_snaps = load_snapshots_from_dir(snap_dir)
    _outlier_dates = set(holding_phantom_corrections(_raw_snaps).keys())
    if _outlier_dates:
        print(f"  [perf] Reconciliation outlier dates (excluded from 1D baseline): {sorted(_outlier_dates)}")

    snapshots: Dict[str, float] = {}
    account_snapshots: Dict[str, Dict[str, float]] = {}  # {date: {acct_key: value}}
    for d in _raw_snaps:
        try:
            dt = d["date"]
            if dt in _outlier_dates:
                continue
            snapshots[dt] = float(d["total_value"])
            if "accounts" in d:
                acct_vals = {}
                for ak, av in d["accounts"].items():
                    if isinstance(av, dict):
                        acct_vals[ak] = float(av.get("value", av.get("total_value", 0)) or 0)
                if acct_vals:
                    account_snapshots[dt] = acct_vals
        except Exception:
            pass

    # Guard: reject outlier snapshots (>25% jump from median)
    _sorted_dates = sorted(snapshots.keys())
    _rejected = []
    if len(_sorted_dates) >= 3:
        _vals = [snapshots[d] for d in _sorted_dates]
        _median = sorted(_vals)[len(_vals) // 2]
        for d in _sorted_dates:
            v = snapshots[d]
            if _median > 0 and abs(v - _median) / _median > 0.25:
                _rejected.append((d, v, _median))
                print(f"  [perf] OUTLIER SNAPSHOT EXCLUDED: {d} ${v:,.0f} vs median ${_median:,.0f} ({abs(v - _median) / _median * 100:.1f}% drift)")
        for d, _, _ in _rejected:
            del snapshots[d]

    snap_count = len(snapshots)
    snap_dates = sorted(snapshots.keys())

    # ── Reconstruct historical values ─────────────────────────────────────────
    price_cache: Dict[str, Dict] = {}
    periods = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y"]
    results = {}

    for period in periods:
        start_dt = _period_start_date(period, today)
        if start_dt is None:
            continue
        start_str = start_dt.strftime("%Y-%m-%d")

        # Source 1: snapshot match (±3 days, then widen to ±14 for monthly+)
        hist_val  = None
        src_label = None
        max_delta = 4 if period in ("1D", "1W") else 45
        for delta in range(0, max_delta):
            for sign in [0, -1, 1]:
                candidate = (start_dt + timedelta(days=delta * sign)).strftime("%Y-%m-%d")
                if candidate in snapshots:
                    hist_val  = snapshots[candidate]
                    src_label = "snapshot"
                    break
            if hist_val:
                break

        # Source 2: repricing DISABLED — produces inaccurate values after trades.
        # Only real snapshots/statement anchors are used. Periods without
        # snapshot coverage show as unavailable until an anchor is added.
        # See incident_performance_import_2026-04-21.md for full rationale.

        if hist_val and hist_val > 0 and current_val > 0:
            change     = round(current_val - hist_val, 2)
            change_pct = round((change / hist_val) * 100, 2)

            # Guard: reject impossible short-term returns
            max_pct = 25 if period in ("1D", "1W") else 50
            if abs(change_pct) > max_pct:
                print(f"  [perf] RETURN REJECTED: {period} {change_pct:+.1f}% exceeds {max_pct}% guard (start=${hist_val:,.0f} end=${current_val:,.0f})")
                results[period] = {
                    "period": period, "start_date": start_str,
                    "change": None, "change_pct": None,
                    "source": "rejected",
                    "note": f"Computed {change_pct:+.1f}% exceeds sanity threshold — likely bad snapshot",
                }
                continue

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
                "period":     period,
                "start_date": start_str,
                "change":     None,
                "change_pct": None,
                "source":     "pending",
                "note":       f"No data near {start_str} — accumulates over time",
            }

    # ── All-time from cost basis ───────────────────────────────────────────────
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

    # ── Per-account period returns ────────────────────────────────────────────
    account_labels = {
        "fidelity_401k": "Fidelity 401k",
        "schwab_rollover_ira": "Rollover IRA",
        "schwab_roth": "Roth IRA",
        "schwab_taxable": "Taxable",
    }
    acct_summaries = portfolio.get("account_summaries", {})
    accounts_out = {}
    for acct_key, label in account_labels.items():
        acct_cv = acct_summaries.get(acct_key, {}).get("total_value", 0) or 0
        if acct_cv <= 0:
            continue
        acct_holdings = [h for h in portfolio.get("holdings", [])
                         if h.get("account") == acct_key]
        if not acct_holdings:
            continue
        acct_portfolio = {**portfolio, "holdings": acct_holdings}
        acct_periods = {}
        for period in periods:
            start_dt = _period_start_date(period, today)
            if start_dt is None:
                continue
            start_str = start_dt.strftime("%Y-%m-%d")
            # Snapshot match
            hist_val = None
            src_label = None
            for delta in range(0, 4):
                for sign in [0, -1, 1]:
                    candidate = (start_dt + timedelta(days=delta * sign)).strftime("%Y-%m-%d")
                    acct_snap = account_snapshots.get(candidate, {})
                    if acct_key in acct_snap:
                        hist_val = acct_snap[acct_key]
                        src_label = "snapshot"
                        break
                if hist_val:
                    break
            # Reprice fallback
            if hist_val is None and period != "1D":
                hist_val = _portfolio_value_at(
                    txns, start_str, price_cache, yahoo_cache, acct_portfolio, fidelity_map
                )
                src_label = "repriced"
            if hist_val and hist_val > 0 and acct_cv > 0:
                change = round(acct_cv - hist_val, 2)
                change_pct = round((change / hist_val) * 100, 2)
                acct_periods[period] = {
                    "period": period, "start_date": start_str,
                    "start_value": hist_val, "end_value": acct_cv,
                    "change": change, "change_pct": change_pct,
                    "source": src_label,
                }
            else:
                acct_periods[period] = None

        # 1D: prefer market day (sum of holding day_change) over snapshot delta
        _acct_md = account_market_days(portfolio).get(acct_key)
        if _acct_md:
            _snap_1d = (acct_periods.get("1D") or {}) if isinstance(acct_periods.get("1D"), dict) else {}
            _snap_pct = _snap_1d.get("change_pct")
            if not snapshot_period_return_reliable(_snap_pct, "1D", market_day_pct=_acct_md.get("change_pct")):
                _acct_md = {**_acct_md, "snapshot_1d_pct": _snap_pct, "snapshot_replaced": True}
            acct_periods["1D"] = _acct_md

        accounts_out[acct_key] = {
            "label": label,
            "current_value": acct_cv,
            "periods": acct_periods,
        }

    # Portfolio-level 1D: canonical market day (matches header TODAY)
    _md = portfolio_market_day(portfolio)
    if _md:
        _snap_1d = results.get("1D") if isinstance(results.get("1D"), dict) else {}
        _snap_pct = _snap_1d.get("change_pct")
        if not snapshot_period_return_reliable(_snap_pct, "1D", market_day_pct=_md.get("change_pct")):
            _md = {**_md, "snapshot_1d_pct": _snap_pct, "snapshot_1d_change": _snap_1d.get("change"), "snapshot_replaced": True}
        results["1D"] = _md

    return {
        "periods":        results,
        "snapshot_count": snap_count,
        "snapshot_dates": snap_dates[-7:],
        "snapshot_outliers": sorted(_outlier_dates),
        "building":       [p for p, d in results.items() if d.get("source") == "pending"],
        "reconstructed":  [p for p, d in results.items() if d.get("source") == "repriced"],
        "current_value":  current_val,
        "has_data":       True,
        "accounts":       accounts_out,
    }
