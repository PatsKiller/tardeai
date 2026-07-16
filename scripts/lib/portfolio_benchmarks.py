"""Index benchmark returns for Command Center v3 (SPY / QQQ / IWM / DIA).

Uses ticker_enrichment_cache (+ finviz/price_cache fallbacks) so Home and
Portfolio Returns can show portfolio vs S&P 500, Nasdaq-100, etc.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE = PROJECT_ROOT / "data" / "portfolios" / "state"
ENRICH_PATH = STATE / "ticker_enrichment_cache.json"
FINVIZ_PATH = STATE / "finviz_quote_cache.json"
PRICE_CACHE_PATH = STATE / "price_cache.json"

# Canonical public benchmarks (ETFs as proxies)
BENCHMARKS: list[dict[str, str]] = [
    {"symbol": "SPY", "label": "S&P 500", "short": "SPY", "proxy": "SPY"},
    {"symbol": "QQQ", "label": "Nasdaq-100", "short": "QQQ", "proxy": "QQQ"},
    {"symbol": "IWM", "label": "Russell 2000", "short": "IWM", "proxy": "IWM"},
    {"symbol": "DIA", "label": "Dow 30", "short": "DIA", "proxy": "DIA"},
]

# Map portfolio period keys → enrichment / finviz fields
_PERIOD_FIELDS: dict[str, tuple[str, ...]] = {
    "1D": ("change_from_open_pct", "change_pct", "day_change_pct"),
    "1W": ("perf_week_pct", "perf_week"),
    "1M": ("perf_month_pct", "perf_month"),
    "3M": ("perf_quarter_pct", "perf_quarter"),
    "6M": ("perf_halfyr_pct", "perf_halfyr"),
    "YTD": ("perf_ytd_pct", "perf_ytd"),
    "1Y": ("perf_year_pct", "perf_year"),
}


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        x = float(v)
        if x != x:
            return None
        return x
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def _enrich() -> dict[str, Any]:
    if not ENRICH_PATH.exists():
        return {}
    try:
        d = json.loads(ENRICH_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _finviz() -> dict[str, Any]:
    if not FINVIZ_PATH.exists():
        return {}
    try:
        d = json.loads(FINVIZ_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _price_cache() -> dict[str, Any]:
    if not PRICE_CACHE_PATH.exists():
        return {}
    try:
        d = json.loads(PRICE_CACHE_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def clear_benchmark_cache() -> None:
    _enrich.cache_clear()
    _finviz.cache_clear()
    _price_cache.cache_clear()


def _period_return_from_prices(sym: str, period: str) -> float | None:
    """Fallback: simple close-to-close % from price_cache for major periods."""
    from datetime import date, timedelta

    series = _price_cache().get(sym)
    if not isinstance(series, dict) or not series:
        return None
    dates = sorted(d for d in series.keys() if isinstance(d, str) and d[:1].isdigit())
    if len(dates) < 2:
        return None
    end_d = dates[-1]
    end_px = _f(series.get(end_d))
    if end_px is None or end_px <= 0:
        return None

    today = date.fromisoformat(end_d[:10])
    if period == "1D":
        start_target = today - timedelta(days=1)
    elif period == "1W":
        start_target = today - timedelta(days=7)
    elif period == "1M":
        start_target = today - timedelta(days=30)
    elif period == "3M":
        start_target = today - timedelta(days=91)
    elif period == "6M":
        start_target = today - timedelta(days=182)
    elif period == "YTD":
        start_target = date(today.year, 1, 1)
    elif period == "1Y":
        start_target = today - timedelta(days=365)
    else:
        return None

    start_s = start_target.isoformat()
    # nearest prior date
    start_d = None
    for d in reversed(dates):
        if d[:10] <= start_s:
            start_d = d
            break
    if not start_d:
        return None
    start_px = _f(series.get(start_d))
    if start_px is None or start_px <= 0:
        return None
    return round(100.0 * (end_px - start_px) / start_px, 2)


def benchmark_period_pct(symbol: str, period: str) -> tuple[float | None, str]:
    """Return (change_pct, source) for one benchmark period."""
    sym = symbol.upper()
    enr = _enrich().get(sym) or {}
    fin = _finviz().get(sym) or {}
    fields = _PERIOD_FIELDS.get(period) or ()
    for field in fields:
        if field in enr and enr.get(field) is not None:
            v = _f(enr.get(field))
            if v is not None:
                return v, f"enrichment.{field}"
        if field in fin and fin.get(field) is not None:
            v = _f(fin.get(field))
            if v is not None:
                return v, f"finviz.{field}"
    # price cache fallback for SPY etc.
    v = _period_return_from_prices(sym, period)
    if v is not None:
        return v, "price_cache"
    return None, "missing"


def build_benchmarks(
    portfolio_periods: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full benchmarks block for /api/v2/portfolio/performance.

    Includes per-period change_pct and alpha vs portfolio (portfolio − bench).
    """
    portfolio_periods = portfolio_periods or {}
    out: dict[str, Any] = {
        "as_of_source": "ticker_enrichment_cache (+ finviz / price_cache fallback)",
        "items": [],
        "by_symbol": {},
        "alpha": {},  # portfolio excess return vs each bench
    }

    for b in BENCHMARKS:
        sym = b["symbol"]
        periods: dict[str, Any] = {}
        alpha_periods: dict[str, Any] = {}
        for period in _PERIOD_FIELDS:
            pct, src = benchmark_period_pct(sym, period)
            periods[period] = {
                "change_pct": pct,
                "source": src,
            }
            # Portfolio display pct (prefer transfer-adjusted)
            pp = portfolio_periods.get(period) or {}
            if not isinstance(pp, dict):
                pp = {}
            port_pct = pp.get("display_change_pct")
            if port_pct is None:
                port_pct = pp.get("change_pct")
            port_pct = _f(port_pct)
            if port_pct is not None and pct is not None:
                alpha = round(port_pct - pct, 2)
                periods[period]["alpha_pct"] = alpha
                alpha_periods[period] = {
                    "alpha_pct": alpha,
                    "portfolio_pct": port_pct,
                    "benchmark_pct": pct,
                }
            else:
                periods[period]["alpha_pct"] = None

        item = {
            "symbol": sym,
            "label": b["label"],
            "short": b["short"],
            "periods": periods,
        }
        out["items"].append(item)
        out["by_symbol"][sym] = item
        out["alpha"][sym] = alpha_periods

    return out


def multi_relative_strength(
    symbol_perf_month: float | None,
    symbol_perf_week: float | None = None,
    symbol_perf_quarter: float | None = None,
) -> dict[str, Any]:
    """Relative strength of a name vs SPY / QQQ / IWM (for RI security layer)."""
    out: dict[str, Any] = {"ok": False, "vs": {}}
    if symbol_perf_month is None and symbol_perf_week is None:
        return out
    for b in BENCHMARKS[:3]:  # SPY, QQQ, IWM
        sym = b["symbol"]
        row: dict[str, Any] = {"label": b["label"]}
        if symbol_perf_week is not None:
            bp, _ = benchmark_period_pct(sym, "1W")
            if bp is not None:
                row["week_pct"] = round(symbol_perf_week - bp, 2)
        if symbol_perf_month is not None:
            bp, _ = benchmark_period_pct(sym, "1M")
            if bp is not None:
                row["month_pct"] = round(symbol_perf_month - bp, 2)
        if symbol_perf_quarter is not None:
            bp, _ = benchmark_period_pct(sym, "3M")
            if bp is not None:
                row["quarter_pct"] = round(symbol_perf_quarter - bp, 2)
        if len(row) > 1:
            out["vs"][sym] = row
    out["ok"] = bool(out["vs"])
    # Primary RS for scoring: vs SPY month
    spy_m = (out["vs"].get("SPY") or {}).get("month_pct")
    qqq_m = (out["vs"].get("QQQ") or {}).get("month_pct")
    out["vs_spy_month_pct"] = spy_m
    out["vs_qqq_month_pct"] = qqq_m
    out["vs_schg_compat"] = None  # filled by caller if needed
    return out
