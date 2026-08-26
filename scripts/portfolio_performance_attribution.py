"""portfolio_performance_attribution.py — Performance Attribution
Alpha vs blended benchmark (55% SPY / 20% ITA / 25% AGG).
Sharpe ratio, Sortino ratio, rolling 90-day alpha, factor attribution.

Uses price_cache.json (Jan 2020 → today) for all benchmark AND portfolio
return calculations — no live network calls needed during pipeline.
Automatically adds SPY/ITA/AGG to the price cache if missing.
"""
from __future__ import annotations

import json, math, time
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BENCHMARK_WEIGHTS = {"SPY": 0.55, "ITA": 0.20, "AGG": 0.25}
BENCHMARK_SYMS    = list(BENCHMARK_WEIGHTS.keys())
CACHE_START       = "2020-01-01"


# ── Price helpers ─────────────────────────────────────────────────────────────

def _ensure_benchmarks_in_cache(cache: Dict, cache_path: Path) -> None:
    """Download SPY/ITA/AGG into price_cache if missing or stale (>7 days)."""
    missing = []
    today = date.today().isoformat()
    for sym in BENCHMARK_SYMS:
        prices = cache.get(sym, {})
        if not prices:
            missing.append(sym)
            continue
        last = max(prices.keys())
        days_old = (date.today() - date.fromisoformat(last)).days
        if days_old > 7:
            missing.append(sym)

    if not missing:
        return

    print(f"  [attribution] Fetching benchmark prices: {missing}")
    try:
        import warnings, yfinance as yf
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            end = (date.today() + timedelta(days=1)).isoformat()
            for sym in missing:
                hist = yf.download(sym, start=CACHE_START, end=end,
                                   progress=False, auto_adjust=True, threads=False)
                if hist.empty:
                    print(f"  [attribution] ⚠️  {sym}: no data")
                    continue
                prices = {}
                close_col = hist["Close"]
                # yfinance >= 0.2.x returns MultiIndex columns; flatten
                if hasattr(close_col, "columns"):
                    close_col = close_col.iloc[:, 0]
                for idx, price in close_col.items():
                    try:
                        d = idx.date() if hasattr(idx, "date") else idx
                        if float(price) > 0:
                            prices[str(d)] = round(float(price), 4)
                    except Exception:
                        pass
                if prices:
                    cache[sym] = prices
                    print(f"  [attribution] ✅ {sym}: {len(prices)} days "
                          f"({min(prices)} → {max(prices)})")
                time.sleep(0.3)
        # Persist updated cache
        cache_path.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
    except Exception as e:
        print(f"  [attribution] ⚠️  benchmark fetch error: {e}")


def _prices_to_returns(cache: Dict, sym: str,
                       start: str, end: str) -> List[float]:
    """Extract daily returns for sym from price cache between start and end."""
    prices_raw = cache.get(sym, {})
    if not prices_raw:
        return []
    # Filter to date range, sorted
    filtered = sorted(
        (d, v) for d, v in prices_raw.items()
        if start <= d <= end
    )
    if len(filtered) < 2:
        return []
    vals = [v for _, v in filtered]
    return [(vals[i] / vals[i-1]) - 1 for i in range(1, len(vals))]


def _blend_returns(component_returns: Dict[str, List[float]],
                   weights: Dict[str, float]) -> List[float]:
    """Blend component return series into a single weighted benchmark."""
    min_len = min((len(v) for v in component_returns.values() if v), default=0)
    if min_len < 2:
        return []
    return [
        sum(weights.get(sym, 0) * component_returns[sym][i]
            for sym in weights if component_returns.get(sym) and i < len(component_returns[sym]))
        for i in range(min_len)
    ]


# ── Portfolio return reconstruction from price cache ─────────────────────────

def _portfolio_returns_from_cache(portfolio: Dict, cache: Dict,
                                   start: str, end: str) -> List[float]:
    """
    Reconstruct approximate daily portfolio returns using CURRENT holdings
    repriced at each historical date from the price cache.

    This is the same "reprice current holdings at historical prices" approach
    used by portfolio_performance_history.py — accurate for stable long-term
    holdings, noisy for active traders (but we hold V since 2008 and ETFs).

    Returns list of daily return floats over the start→end window.
    """
    from portfolio_performance_history import (
        _is_proprietary_fund, _load_fidelity_ticker_map
    )

    # Load fidelity map so 401k funds price correctly
    state_dir = cache.get("_state_dir_hint")  # injected by caller if available
    fidelity_map: Dict[str, str] = {}
    if state_dir:
        try:
            fidelity_map = _load_fidelity_ticker_map(Path(state_dir))
        except Exception:
            pass

    # Build {yahoo_sym: shares} mapping (skip proprietary without mapping)
    sym_shares: Dict[str, float] = {}
    lump_mv    = 0.0   # 401k funds with no mapping — held constant

    for h in portfolio.get("holdings", []):
        raw = (h.get("symbol") or "").strip().upper()
        qty = float(h.get("shares") or h.get("quantity") or 0)
        mv  = float(h.get("market_value") or 0)
        if not raw or h.get("is_loan"):
            continue
        if _is_proprietary_fund(raw):
            mapped = fidelity_map.get(raw)
            if mapped and qty > 0:
                sym_shares[mapped] = sym_shares.get(mapped, 0) + qty
            else:
                lump_mv += mv   # treat as constant
        else:
            if qty > 0:
                sym_shares[raw] = sym_shares.get(raw, 0) + qty

    if not sym_shares and lump_mv == 0:
        return []

    # Collect all date strings in range that exist in cache for at least one symbol
    all_dates: set = set()
    for sym in sym_shares:
        for d in (cache.get(sym) or {}):
            if start <= d <= end:
                all_dates.add(d)
    sorted_dates = sorted(all_dates)
    if len(sorted_dates) < 2:
        return []

    # Compute portfolio value at each date
    def _val_at(dt: str) -> float:
        total = lump_mv   # constant for unmapped 401k
        for sym, qty in sym_shares.items():
            prices = cache.get(sym, {})
            avail  = [d for d in prices if d <= dt]
            if avail:
                total += qty * prices[max(avail)]
        return total

    values = [_val_at(d) for d in sorted_dates]
    returns = []
    for i in range(1, len(values)):
        prev = values[i-1]
        if prev > 0:
            returns.append(values[i] / prev - 1)
    return returns


# ── Statistical helpers ───────────────────────────────────────────────────────

def _sharpe(returns: List[float], rf: float = 0.045/252) -> Optional[float]:
    if len(returns) < 30:
        return None
    mean = sum(returns) / len(returns)
    var  = sum((r - mean)**2 for r in returns) / (len(returns) - 1)
    std  = math.sqrt(var) if var > 0 else 0
    return round(math.sqrt(252) * (mean - rf) / std, 3) if std else None


def _sortino(returns: List[float], rf: float = 0.045/252) -> Optional[float]:
    if len(returns) < 30:
        return None
    mean = sum(returns) / len(returns)
    neg  = [r for r in returns if r < rf]
    if not neg:
        return None
    ds   = math.sqrt(sum((r - rf)**2 for r in neg) / len(neg))
    return round(math.sqrt(252) * (mean - rf) / ds, 3) if ds else None


def _max_drawdown(returns: List[float]) -> float:
    cum = [1.0]
    for r in returns:
        cum.append(cum[-1] * (1 + r))
    peak = 1.0; max_dd = 0.0
    for v in cum:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd
    return round(max_dd * 100, 2)


def _cagr(returns: List[float]) -> Optional[float]:
    if len(returns) < 30:
        return None
    total = 1.0
    for r in returns:
        total *= (1 + r)
    years = len(returns) / 252
    return round((total ** (1 / years) - 1) * 100, 2) if years > 0 else None


# ── Main entry point ──────────────────────────────────────────────────────────

def compute_attribution(portfolio: Dict, state_dir: Path) -> Dict:
    """
    Compute full performance attribution vs blended benchmark.
    Uses price_cache.json for both benchmark and portfolio return reconstruction.
    Sharpe/Sortino/Alpha computed from up to 6 years of history immediately —
    no need to wait 30+ daily snapshots.
    """
    state_dir = Path(state_dir)
    cache_path = state_dir / "price_cache.json"

    # Load price cache
    cache: Dict = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Inject hint for helper functions
    cache["_state_dir_hint"] = str(state_dir)

    # Ensure SPY/ITA/AGG are in the cache
    _ensure_benchmarks_in_cache(cache, cache_path)

    # Date window: last 2 years (sufficient for meaningful Sharpe/Sortino)
    end_dt   = date.today()
    start_dt = end_dt.replace(year=end_dt.year - 2)
    start    = start_dt.isoformat()
    end      = end_dt.isoformat()

    # ── Benchmark returns ─────────────────────────────────────────────────────
    bench_component: Dict[str, List[float]] = {}
    for sym in BENCHMARK_SYMS:
        bench_component[sym] = _prices_to_returns(cache, sym, start, end)

    blended_ret = _blend_returns(bench_component, BENCHMARK_WEIGHTS)
    print(f"  [attribution] Benchmark: {len(blended_ret)} daily returns "
          f"({start} → {end})")

    # ── Portfolio returns from price cache ────────────────────────────────────
    port_returns = _portfolio_returns_from_cache(portfolio, cache, start, end)
    print(f"  [attribution] Portfolio: {len(port_returns)} daily returns "
          f"reconstructed from price cache")

    # Fall back to snapshot-based returns if price cache reconstruction failed
    if len(port_returns) < 30:
        snap_file = state_dir / "portfolio_snapshots.json"
        snap_values: List[Tuple[str, float]] = []
        if snap_file.exists():
            try:
                snap_data = json.loads(snap_file.read_text())
                for s in sorted(snap_data.get("snapshots", []),
                                key=lambda x: x.get("date", "")):
                    if s.get("date") and s.get("total_value"):
                        snap_values.append((s["date"], float(s["total_value"])))
            except Exception:
                pass
        if len(snap_values) >= 2:
            port_returns = []
            for i in range(1, len(snap_values)):
                prev = snap_values[i-1][1]
                curr = snap_values[i][1]
                if prev > 0:
                    port_returns.append(curr / prev - 1)
            print(f"  [attribution] Fallback: {len(port_returns)} snapshot returns")

    snap_count = len(port_returns)

    # ── Metrics ───────────────────────────────────────────────────────────────
    # Align lengths for apples-to-apples comparison
    align = min(len(port_returns), len(blended_ret))
    p_ret = port_returns[-align:] if align > 0 else port_returns
    b_ret = blended_ret[-align:]  if align > 0 else blended_ret

    bench_sharpe  = _sharpe(b_ret)
    bench_sortino = _sortino(b_ret)
    bench_maxdd   = _max_drawdown(b_ret)
    bench_cagr    = _cagr(b_ret)

    port_sharpe   = _sharpe(p_ret)
    port_sortino  = _sortino(p_ret)
    port_maxdd    = _max_drawdown(p_ret) if p_ret else None
    port_cagr     = _cagr(p_ret)

    # Alpha: annualized portfolio CAGR minus benchmark CAGR
    alpha = None
    if port_cagr is not None and bench_cagr is not None:
        alpha = round(port_cagr - bench_cagr, 2)

    # All-time gain from portfolio totals
    totals          = portfolio.get("portfolio_totals", {})
    inception_gain  = totals.get("total_gain_pct", 0)
    inception_return = round(inception_gain, 2) if inception_gain else None

    # SPY 3-year return for context
    bench_inception = None
    spy_prices = cache.get("SPY", {})
    if spy_prices:
        spy_sorted = sorted(spy_prices.items())
        if len(spy_sorted) > 200:
            # Last 3 years
            cutoff = (end_dt - timedelta(days=756)).isoformat()
            base   = next((v for d, v in spy_sorted if d >= cutoff), None)
            latest = spy_sorted[-1][1]
            if base and base > 0:
                bench_inception = round((latest / base - 1) * 100, 2)

    # ── Rolling 90-day alpha ──────────────────────────────────────────────────
    rolling_alpha = []
    window = 90
    if len(p_ret) >= window and len(b_ret) >= window:
        for i in range(window, align, 5):
            pr_w = p_ret[i-window:i]
            br_w = b_ret[i-window:i]
            pr_ann = sum(pr_w) / len(pr_w) * 252 * 100
            br_ann = sum(br_w) / len(br_w) * 252 * 100
            rolling_alpha.append({
                "index":     i,
                "port_ann":  round(pr_ann, 2),
                "bench_ann": round(br_ann, 2),
                "alpha":     round(pr_ann - br_ann, 2),
            })

    # ── Top contributors ──────────────────────────────────────────────────────
    top_gainers, top_losers = [], []
    for h in portfolio.get("holdings", []):
        gl = h.get("gain_loss", 0) or 0
        if gl > 1000:
            top_gainers.append({"symbol": h.get("symbol", ""), "gain": gl})
        elif gl < -500:
            top_losers.append({"symbol": h.get("symbol", ""), "loss": gl})
    top_gainers.sort(key=lambda x: -x["gain"])
    top_losers.sort(key=lambda x: x["loss"])

    # Note text
    if len(p_ret) >= 252:
        note = (f"Metrics from {len(p_ret)}-day price-cache reconstruction "
                f"({start} → {end})")
    elif len(p_ret) >= 30:
        note = (f"Metrics from {len(p_ret)} days of data — "
                f"growing toward 2-year window")
    else:
        note = (f"Need 30+ daily returns for ratios — "
                f"currently {len(p_ret)} days. "
                "All-time gain and benchmark comparison available now.")

    result = {
        "has_data":        True,
        "benchmark":       BENCHMARK_WEIGHTS,
        "benchmark_label": "55% SPY / 20% ITA / 25% AGG",
        "benchmark_source": (
            "portfolio_performance_attribution blended policy "
            "(55% SPY / 20% ITA / 25% AGG); ITA is the 20% defense sleeve of the blend, "
            "not a standalone portfolio target"
        ),
        # Metrics
        "port_cagr":         port_cagr,
        "bench_cagr":        bench_cagr,
        "alpha_annualized":  alpha,
        "inception_return":  inception_return,
        "bench_3yr_return":  bench_inception,
        # Risk-adjusted
        "port_sharpe":   port_sharpe,
        "bench_sharpe":  bench_sharpe,
        "port_sortino":  port_sortino,
        "bench_sortino": bench_sortino,
        "port_maxdd":    port_maxdd,
        "bench_maxdd":   bench_maxdd,
        # Rolling
        "rolling_alpha":   rolling_alpha[-24:],
        # Attribution
        "top_gainers":     top_gainers[:5],
        "top_losers":      top_losers[:5],
        "snapshot_count":  snap_count,
        "note":            note,
        "last_updated":    datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    out = state_dir / "performance_attribution.json"
    out.write_text(json.dumps(result, indent=2, default=str))
    return result


def load_attribution(state_dir: Path) -> Dict:
    p = Path(state_dir) / "performance_attribution.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}
