"""portfolio_var.py — Parametric Value-at-Risk & Beta Contribution Engine

Computes institutional-grade risk metrics from price_cache.json:
  - Portfolio daily volatility (252-day rolling)
  - Parametric VaR at 95% and 99% confidence
  - Position-level beta contribution (weight × beta)
  - Concentration heat map data (top-5 positions)

Formula:
  VaR_95 = portfolio_value × 1.645 × daily_vol
  VaR_99 = portfolio_value × 2.326 × daily_vol
  daily_vol = std(daily_portfolio_returns) over last 252 trading days

Daily portfolio returns are computed by repricing current holdings at each
historical date using price_cache.json — the same method used for period returns.
This avoids any external API calls.

BETAS reference table (SPY-relative, annualised estimates as of April 2026):
Update quarterly or when new positions are added.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Beta reference table ──────────────────────────────────────────────────────
# SPY-relative 5-year beta estimates. Source: Finviz Elite / manual reference.
# 0.0 = uncorrelated (cash, BDCs with low correlation), 1.0 = market-neutral
BETA_TABLE: Dict[str, float] = {
    # Large-cap / payment
    "V":      0.96, "MA":     0.98,
    # Defense / government
    "LMT":    0.55, "NOC":    0.52, "RTX":    0.72, "LHX":    0.68,
    "LDOS":   0.78, "BAH":    0.74, "CACI":   0.88, "DRS":    0.82,
    "KBR":    0.85, "KTOS":   1.42, "AVAV":   1.35, "RKLB":   1.90,
    # Pharma
    "PFE":    0.55,
    # ETFs (passive sector)
    "XLI":    1.10, "XLB":    1.05, "SCHD":   0.78, "SCHG":   1.15,
    "ARKG":   1.30, "ARKQ":   1.40, "DIV":    0.72,
    # BDCs
    "CSWC":   0.82, "PFLT":   0.78,
    # Fixed income
    "BND":    0.05, "AMANX":  0.45,
    # Mutual funds (proxy betas)
    "FCNTX":  1.05, "AMANX":  0.45,
    # Utilities
    "NEE":    0.62,
    # Space/tech
    "IRDM":   1.15,
    # Default for unknowns
    "_default": 1.0,
}

LOOKBACK_DAYS   = 252   # 1 trading year
Z_95            = 1.645
Z_99            = 2.326
MIN_DAYS        = 30    # minimum data points for valid VaR


def _load_price_cache(state_dir: Path) -> Dict:
    path = state_dir / "price_cache.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _trading_dates(cache: Dict, lookback: int = LOOKBACK_DAYS) -> List[str]:
    """Return the last `lookback` trading dates that appear in the cache."""
    # Use SPY or any liquid symbol as the date spine
    anchor = cache.get("SPY") or cache.get("V") or {}
    if isinstance(anchor, dict) and "prices" in anchor:
        anchor = anchor["prices"]
    dates = sorted(d for d in anchor if isinstance(anchor.get(d), (int, float)))
    return dates[-lookback:]


def _price_on_date(cache: Dict, symbol: str, date: str) -> Optional[float]:
    """Get closing price for a symbol on a given date. Returns None if unavailable."""
    sym_data = cache.get(symbol)
    if not sym_data:
        return None
    # Handle both flat {date: price} and nested {prices: {date: price}} formats
    if isinstance(sym_data, dict):
        prices = sym_data.get("prices", sym_data)
        val = prices.get(date)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None
    return None


def _portfolio_value_on_date(
    holdings: List[Dict],
    cache: Dict,
    date: str,
    current_prices: Dict[str, float],
) -> Optional[float]:
    """
    Reprice the current portfolio at a historical date.
    Uses current shares but historical prices — same method as period returns.
    Falls back to current price if no historical price available (conservative).
    """
    total = 0.0
    priced = 0
    for h in holdings:
        sym    = h.get("symbol", "")
        shares = h.get("shares", 0) or 0
        if shares <= 0:
            continue
        # Skip loans, cash equivalents, revoked positions
        if h.get("is_loan") or h.get("is_cash"):
            mv = h.get("market_value", 0) or 0
            total += mv
            priced += 1
            continue
        hist_px = _price_on_date(cache, sym, date)
        if hist_px and hist_px > 0:
            total += shares * hist_px
            priced += 1
        else:
            # Fall back to current price (no historical data — treat as flat)
            cur_px = current_prices.get(sym, 0)
            if cur_px > 0:
                total += shares * cur_px
                priced += 1
    return total if priced > 0 else None


def compute_var(
    portfolio: Dict,
    state_dir: Path,
) -> Dict:
    """
    Main entry point. Returns VaR and risk metrics dict.

    Args:
        portfolio: The loaded portfolio dict (from portfolio_loader)
        state_dir: Path to data/portfolios/state/

    Returns dict with keys:
        var_95, var_99, var_95_pct, var_99_pct,
        daily_vol_pct, annual_vol_pct,
        beta_contributions, top_concentration,
        days_used, status, error (if any)
    """
    result: Dict = {
        "var_95": 0.0, "var_99": 0.0,
        "var_95_pct": 0.0, "var_99_pct": 0.0,
        "daily_vol_pct": 0.0, "annual_vol_pct": 0.0,
        "beta_contributions": [],
        "top_concentration": [],
        "days_used": 0,
        "status": "pending",
        "error": None,
        "as_of": datetime.now().strftime("%Y-%m-%d"),
    }

    try:
        holdings = [
            h for h in portfolio.get("holdings", [])
            if not h.get("is_loan") and (h.get("market_value") or 0) > 0
        ]
        totals   = portfolio.get("portfolio_totals", {})
        total_mv = totals.get("total_value", 0) or 0

        if total_mv <= 0 or not holdings:
            result["status"] = "no_data"
            result["error"]  = "No holdings or zero portfolio value"
            return result

        # Current prices for fallback
        current_prices = {
            h["symbol"]: float(h.get("price") or 0)
            for h in holdings if h.get("symbol")
        }

        # Load price cache
        cache = _load_price_cache(state_dir)
        if not cache:
            result["status"] = "no_cache"
            result["error"]  = "price_cache.json not found or empty"
            return result

        # Get trading date spine
        dates = _trading_dates(cache, LOOKBACK_DAYS)
        if len(dates) < MIN_DAYS:
            result["status"] = "insufficient_history"
            result["error"]  = f"Only {len(dates)} trading days in cache (need {MIN_DAYS})"
            return result

        # ── Compute portfolio value series ────────────────────────────────────
        values: List[float] = []
        for d in dates:
            v = _portfolio_value_on_date(holdings, cache, d, current_prices)
            if v and v > 0:
                values.append(v)

        if len(values) < MIN_DAYS:
            result["status"] = "insufficient_priced_days"
            result["error"]  = f"Only {len(values)} days with full pricing"
            return result

        # ── Daily returns ─────────────────────────────────────────────────────
        daily_returns: List[float] = []
        for i in range(1, len(values)):
            if values[i - 1] > 0:
                ret = (values[i] - values[i - 1]) / values[i - 1]
                daily_returns.append(ret)

        if len(daily_returns) < MIN_DAYS:
            result["status"] = "insufficient_returns"
            return result

        # ── Parametric VaR ────────────────────────────────────────────────────
        daily_vol = statistics.stdev(daily_returns)
        annual_vol = daily_vol * math.sqrt(252)

        var_95 = total_mv * Z_95 * daily_vol
        var_99 = total_mv * Z_99 * daily_vol

        result["var_95"]        = round(var_95, 0)
        result["var_99"]        = round(var_99, 0)
        result["var_95_pct"]    = round(Z_95 * daily_vol * 100, 2)
        result["var_99_pct"]    = round(Z_99 * daily_vol * 100, 2)
        result["daily_vol_pct"] = round(daily_vol * 100, 2)
        result["annual_vol_pct"]= round(annual_vol * 100, 1)
        result["days_used"]     = len(daily_returns)

        # ── Beta contribution ─────────────────────────────────────────────────
        beta_contributions: List[Dict] = []
        for h in sorted(holdings, key=lambda x: x.get("market_value", 0) or 0, reverse=True)[:15]:
            sym    = h.get("symbol", "")
            mv     = float(h.get("market_value", 0) or 0)
            weight = mv / total_mv if total_mv > 0 else 0
            beta   = BETA_TABLE.get(sym.upper(), BETA_TABLE["_default"])
            contrib = weight * beta
            beta_contributions.append({
                "symbol":      sym,
                "weight_pct":  round(weight * 100, 1),
                "beta":        beta,
                "contribution": round(contrib, 4),
            })

        # Weighted portfolio beta
        port_beta = sum(b["contribution"] for b in beta_contributions)
        result["portfolio_beta"]     = round(port_beta, 3)
        result["beta_contributions"] = beta_contributions

        # ── Top concentration ─────────────────────────────────────────────────
        top5 = sorted(holdings, key=lambda x: x.get("market_value", 0) or 0, reverse=True)[:5]
        result["top_concentration"] = [
            {
                "symbol": h.get("symbol", ""),
                "weight_pct": round((h.get("market_value", 0) or 0) / total_mv * 100, 1),
                "market_value": round(h.get("market_value", 0) or 0, 0),
                "is_v": h.get("symbol", "").upper() == "V",
            }
            for h in top5
        ]

        result["status"] = "ok"

    except Exception as exc:
        result["status"] = "error"
        result["error"]  = str(exc)

    return result


if __name__ == "__main__":
    # Quick standalone test
    import sys
    root = Path(__file__).parent.parent
    state_dir = root / "data" / "portfolios" / "state"
    sys.path.insert(0, str(root / "scripts"))
    from portfolio_loader import load_all_portfolios
    portfolio = load_all_portfolios(root)
    result = compute_var(portfolio, state_dir)
    print(json.dumps(result, indent=2, default=str))
