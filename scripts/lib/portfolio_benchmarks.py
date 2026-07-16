"""Index benchmark returns for Command Center v3 (SPY / QQQ / IWM / DIA).

ETF total-return proxies from enrichment/finviz/price_cache, with alpha =
displayed book % − index % for the same period label.

Important: book returns are household NAV (often transfer-adjusted). Index
returns are pure price total-return proxies — not a GIPS composite. Tooltips
and method notes make that explicit in the UI.
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

BENCHMARKS: list[dict[str, str]] = [
    {
        "symbol": "SPY",
        "label": "S&P 500",
        "short": "SPY",
        "description": "SPDR S&P 500 ETF — large-cap US equity (S&P 500 proxy)",
    },
    {
        "symbol": "QQQ",
        "label": "Nasdaq-100",
        "short": "QQQ",
        "description": "Invesco QQQ — Nasdaq-100 mega-cap / growth tech proxy",
    },
    {
        "symbol": "IWM",
        "label": "Russell 2000",
        "short": "IWM",
        "description": "iShares Russell 2000 ETF — US small-cap proxy",
    },
    {
        "symbol": "DIA",
        "label": "Dow 30",
        "short": "DIA",
        "description": "SPDR Dow Jones Industrial Average ETF — 30 blue chips",
    },
]

# Prefer full-session day change; change_from_open is last resort (misleading AH)
_PERIOD_FIELDS: dict[str, tuple[str, ...]] = {
    "1D": ("day_change_pct", "change_pct", "perf_day_pct"),
    "1W": ("perf_week_pct", "perf_week"),
    "1M": ("perf_month_pct", "perf_month"),
    "3M": ("perf_quarter_pct", "perf_quarter"),
    "6M": ("perf_halfyr_pct", "perf_halfyr"),
    "YTD": ("perf_ytd_pct", "perf_ytd"),
    "1Y": ("perf_year_pct", "perf_year"),
}

_PERIOD_HELP: dict[str, str] = {
    "1D": "Index: latest session price move (ETF). Book: market-day household P/L %.",
    "1W": "Index: ~1-week ETF total return (Finviz/enrichment). Book: household NAV over ~1 week.",
    "1M": "Index: ~1-month ETF return. Book: household NAV ~1 month (may be transfer-adjusted).",
    "3M": "Index: ~quarter ETF return (Finviz perf_quarter). Book: household ~3 months.",
    "6M": "Index: ~6-month ETF return. Book: household ~6 months.",
    "YTD": "Index: calendar YTD ETF return. Book: YTD ≈ market (ex-transfers) when amber ≈ is shown.",
    "1Y": "Index: trailing ~1Y ETF return. Book: household ~1 year (may be transfer-adjusted).",
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


def _return_between(sym: str, start_date: str, end_date: str | None = None) -> float | None:
    """Close-to-close % from price_cache between two dates (inclusive nearest)."""
    series = _price_cache().get(sym)
    if not isinstance(series, dict) or not series:
        return None
    dates = sorted(d for d in series.keys() if isinstance(d, str) and d[:1].isdigit())
    if len(dates) < 2:
        return None
    end_d = end_date or dates[-1]
    end_pick = None
    for d in reversed(dates):
        if d[:10] <= str(end_d)[:10]:
            end_pick = d
            break
    start_pick = None
    for d in reversed(dates):
        if d[:10] <= str(start_date)[:10]:
            start_pick = d
            break
    if not end_pick or not start_pick or start_pick == end_pick:
        return None
    sp, ep = _f(series.get(start_pick)), _f(series.get(end_pick))
    if sp is None or ep is None or sp <= 0:
        return None
    return round(100.0 * (ep - sp) / sp, 2)


def _period_return_from_prices(sym: str, period: str) -> float | None:
    from datetime import date, timedelta

    series = _price_cache().get(sym)
    if not isinstance(series, dict) or not series:
        return None
    dates = sorted(d for d in series.keys() if isinstance(d, str) and d[:1].isdigit())
    if len(dates) < 2:
        return None
    end_d = dates[-1]
    today = date.fromisoformat(end_d[:10])
    if period == "1D":
        # previous trading session close → last close
        return _return_between(sym, dates[-2][:10], end_d[:10])
    if period == "1W":
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
    return _return_between(sym, start_target.isoformat(), end_d[:10])


def benchmark_period_pct(
    symbol: str,
    period: str,
    *,
    portfolio_start_date: str | None = None,
) -> tuple[float | None, str, str]:
    """Return (change_pct, source, method_note)."""
    sym = symbol.upper()
    enr = _enrich().get(sym) or {}
    fin = _finviz().get(sym) or {}

    # Align multi-day to portfolio snapshot start when we have both dates
    if portfolio_start_date and period != "1D":
        aligned = _return_between(sym, portfolio_start_date)
        if aligned is not None:
            return (
                aligned,
                f"price_cache aligned to book start {portfolio_start_date[:10]}",
                f"Index close-to-close from book period start {portfolio_start_date[:10]} (price_cache).",
            )

    fields = _PERIOD_FIELDS.get(period) or ()
    for field in fields:
        if field in enr and enr.get(field) is not None:
            v = _f(enr.get(field))
            if v is not None:
                return (
                    v,
                    f"enrichment.{field}",
                    f"ETF {period} total-return proxy from enrichment ({field}). Not household NAV.",
                )
        if field in fin and fin.get(field) is not None:
            v = _f(fin.get(field))
            if v is not None:
                return (
                    v,
                    f"finviz.{field}",
                    f"ETF {period} from Finviz quote cache ({field}).",
                )

    # 1D last resort: change_from_open (label clearly — weak after hours)
    if period == "1D":
        v = _f(enr.get("change_from_open_pct"))
        if v is not None:
            return (
                v,
                "enrichment.change_from_open_pct",
                "⚠ Session open→last only (not full prior close→close). After-hours can look wrong vs book market-day.",
            )
        v = _f(fin.get("change_pct"))
        if v is not None:
            return v, "finviz.change_pct", "ETF session change % from Finviz."

    v = _period_return_from_prices(sym, period)
    if v is not None:
        return v, "price_cache", f"ETF close-to-close from local price_cache ({period})."

    return None, "missing", "No benchmark data for this period."


def _portfolio_display_pct(pp: dict[str, Any]) -> tuple[float | None, str]:
    """Match Home/Returns display logic for the All-accounts row."""
    if not isinstance(pp, dict):
        return None, "none"
    prefer_disp = bool(
        pp.get("nav_is_not_market_only")
        or pp.get("is_false_positive")
        or pp.get("display_change") is not None
        or pp.get("display_change_pct") is not None
    )
    if prefer_disp and pp.get("display_change_pct") is not None:
        return _f(pp.get("display_change_pct")), "display_change_pct (≈ market / transfer-adjusted when flagged)"
    if prefer_disp and pp.get("adjusted_change_pct") is not None:
        return _f(pp.get("adjusted_change_pct")), "adjusted_change_pct"
    if pp.get("change_pct") is not None:
        return _f(pp.get("change_pct")), "change_pct (NAV)"
    return None, "missing"


def build_benchmarks(
    portfolio_periods: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full benchmarks block for /api/v2/portfolio/performance."""
    portfolio_periods = portfolio_periods or {}
    out: dict[str, Any] = {
        "as_of_source": "ETF proxies via enrichment / finviz / price_cache",
        "methodology": (
            "α (alpha) = book period % − index period %. "
            "Book % matches the All-accounts row (transfer-adjusted when ≈ is shown). "
            "Index % is ETF price total-return proxy — not identical methodology to household NAV. "
            "Not risk-adjusted alpha; not a blended policy benchmark."
        ),
        "items": [],
        "by_symbol": {},
        "alpha": {},
    }

    for b in BENCHMARKS:
        sym = b["symbol"]
        periods: dict[str, Any] = {}
        alpha_periods: dict[str, Any] = {}
        for period in _PERIOD_FIELDS:
            pp = portfolio_periods.get(period) or {}
            if not isinstance(pp, dict):
                pp = {}
            start = pp.get("start_date")
            pct, src, method = benchmark_period_pct(
                sym, period, portfolio_start_date=str(start) if start else None,
            )
            port_pct, port_src = _portfolio_display_pct(pp)

            alpha = None
            if port_pct is not None and pct is not None:
                alpha = round(port_pct - pct, 2)

            tip = (
                f"{b['symbol']} · {b['label']}\n"
                f"{b.get('description')}\n"
                f"Period {period}: index {pct:+.2f}% ({src}) · book {port_pct:+.2f}% ({port_src})\n"
                f"α = book − index = "
                + (f"{alpha:+.2f}%" if alpha is not None else "n/a")
                + f"\n{_PERIOD_HELP.get(period, '')}\n"
                f"{method}"
            ) if pct is not None and port_pct is not None else (
                f"{b['symbol']} · {b['label']}\n"
                f"Period {period}: index={pct} ({src}) book={port_pct} ({port_src})\n"
                f"{method}"
            )

            periods[period] = {
                "change_pct": pct,
                "source": src,
                "method_note": method,
                "period_help": _PERIOD_HELP.get(period),
                "alpha_pct": alpha,
                "portfolio_pct": port_pct,
                "portfolio_pct_source": port_src,
                "tooltip": tip,
            }
            if alpha is not None:
                alpha_periods[period] = {
                    "alpha_pct": alpha,
                    "portfolio_pct": port_pct,
                    "benchmark_pct": pct,
                    "tooltip": tip,
                }

        item = {
            "symbol": sym,
            "label": b["label"],
            "short": b["short"],
            "description": b.get("description"),
            "display_name": f"{sym} · {b['label']}",
            "row_tooltip": (
                f"{sym} · {b['label']}: {b.get('description')}. "
                f"Shows ETF index return % and α (your book % minus this index). "
                f"{out['methodology']}"
            ),
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
    for b in BENCHMARKS[:3]:
        sym = b["symbol"]
        row: dict[str, Any] = {"label": b["label"]}
        if symbol_perf_week is not None:
            bp, _, _ = benchmark_period_pct(sym, "1W")
            if bp is not None:
                row["week_pct"] = round(symbol_perf_week - bp, 2)
        if symbol_perf_month is not None:
            bp, _, _ = benchmark_period_pct(sym, "1M")
            if bp is not None:
                row["month_pct"] = round(symbol_perf_month - bp, 2)
        if symbol_perf_quarter is not None:
            bp, _, _ = benchmark_period_pct(sym, "3M")
            if bp is not None:
                row["quarter_pct"] = round(symbol_perf_quarter - bp, 2)
        if len(row) > 1:
            out["vs"][sym] = row
    out["ok"] = bool(out["vs"])
    out["vs_spy_month_pct"] = (out["vs"].get("SPY") or {}).get("month_pct")
    out["vs_qqq_month_pct"] = (out["vs"].get("QQQ") or {}).get("month_pct")
    out["vs_schg_compat"] = None
    return out
