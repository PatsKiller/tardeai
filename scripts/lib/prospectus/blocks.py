"""Institutional data blocks, computed here from house series (never model output).

relative_performance, peer_comparison, estimates, ownership_flows, risk_technicals and the scenario anchors. Every
input comes from a house store (ticker_prices via data_broker.daily_bars / ohlc_bars, the Finviz enrichment cache,
symbol_profiles, analyst targets, the sector/industry momentum runtime files). A value the house does not hold is
``None`` with the gap named, never estimated.
"""
from __future__ import annotations

from datetime import date
import math
import statistics
from typing import Any, Iterable, Optional

#: House sector -> SPDR sector ETF (same mapping as scripts/lib/sectors_monitor.py SECTOR_ETFS), plus Finviz names.
SECTOR_ETFS = {"technology": "XLK", "financials": "XLF", "financial": "XLF", "financial services": "XLF",
               "energy": "XLE", "healthcare": "XLV", "health care": "XLV", "consumer cyclical": "XLY",
               "consumer discretionary": "XLY", "industrials": "XLI", "consumer defensive": "XLP",
               "consumer staples": "XLP", "utilities": "XLU", "real estate": "XLRE", "basic materials": "XLB",
               "materials": "XLB", "communication services": "XLC"}
BENCHMARKS = ("SPY", "QQQ")
WINDOWS = {"1W": 5, "1M": 21, "3M": 63, "YTD": None, "1Y": 252, "3Y": 756}
CHART_WINDOWS = ("3M", "YTD", "1Y", "3Y")
PEER_FIELDS = (("market_cap_b", "Mkt cap ($B)"), ("forward_pe", "Fwd P/E"), ("ev_ebitda", "EV/EBITDA"),
               ("sales_growth_past_5y_pct", "Revenue growth 5y %"), ("oper_margin_pct", "Op margin %"),
               ("roe_pct", "ROE %"), ("div_yield_pct", "Div yield %"), ("total_debt_equity", "Debt/Equity"),
               ("perf_year_pct", "1Y return %"))


def _f(v: Any) -> Optional[float]:
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _series(bars: Iterable[Any]) -> list[tuple[str, float]]:
    out = []
    for b in bars or []:
        d, c = (b.get("price_date"), b.get("close")) if isinstance(b, dict) else (b[0], b[1])
        c = _f(c)
        if d and c and c > 0:
            out.append((str(d)[:10], c))
    out.sort()
    return out


def _start_index(s: list[tuple[str, float]], window: str) -> Optional[int]:
    if not s:
        return None
    if window == "YTD":
        year = s[-1][0][:4]
        idx = next((i for i, (d, _) in enumerate(s) if d[:4] == year), None)
        return max(0, idx - 1) if idx is not None else None
    n = WINDOWS[window]
    return len(s) - 1 - n if len(s) > n else None


def window_return(s: list[tuple[str, float]], window: str) -> Optional[float]:
    i = _start_index(s, window)
    return None if i is None else round((s[-1][1] / s[i][1] - 1) * 100, 2)


def _downsample(points: list, limit: int = 130) -> list:
    if len(points) <= limit:
        return points
    step = len(points) / limit
    out = [points[int(i * step)] for i in range(limit)]
    return out if out[-1] == points[-1] else out + [points[-1]]


def relative_performance(sym: str, bars: Any, bench: dict[str, Any], *, cache: dict, industry: Optional[str],
                         sector_row: Optional[dict] = None, industry_row: Optional[dict] = None) -> dict:
    s = _series(bars)
    named = {sym: s, **{k: _series(v) for k, v in bench.items()}}
    missing = [k for k, v in named.items() if len(v) < 2]
    series = {}
    for w in CHART_WINDOWS:
        i0 = _start_index(s, w)
        if i0 is None:
            continue
        start = s[i0][0]
        lines = []
        for name, ser in named.items():
            pts = [(d, c) for d, c in ser if d >= start]
            if len(pts) >= 2:
                lines.append({"name": name, "points": [[d, round(c / pts[0][1] * 100, 2)] for d, c in _downsample(pts)]})
        series[w] = lines
    returns = []
    for name, ser in named.items():
        returns.append({"name": name, **{w: window_return(ser, w) for w in WINDOWS}})
    spx = next((r for r in returns if r["name"] == "SPY"), None)
    excess = {w: (round(returns[0][w] - spx[w], 2) if spx and returns[0][w] is not None and spx[w] is not None else None)
              for w in WINDOWS}
    rank = None
    mine = _f((cache.get(sym) or {}).get("perf_year_pct"))
    if industry and mine is not None:
        peers = [v for v in (_f(r.get("perf_year_pct")) for r in cache.values()
                             if isinstance(r, dict) and r.get("industry") == industry) if v is not None]
        if len(peers) >= 3:
            better = sum(1 for v in peers if v > mine)
            rank = {"rank": better + 1, "of": len(peers),
                    "percentile": round(100 * sum(1 for v in peers if v <= mine) / len(peers))}
    universe = [v for v in (_f(r.get("perf_year_pct")) for r in cache.values() if isinstance(r, dict)) if v is not None]
    rs = None
    if mine is not None and len(universe) >= 50:
        rs = min(99, max(1, round(99 * sum(1 for v in universe if v < mine) / len(universe))))
    gaps = [f"benchmark series missing: {m}" for m in missing if m != sym]
    if industry_row is None:
        gaps.append("industry-group series: no rebased series in the house (momentum snapshot only)")
    return {"series": series, "returns": returns, "excess_vs_spy": excess, "rank_in_industry": rank,
            "rs_rating_12m": rs, "rs_basis": "percentile of 1Y return across the Finviz enrichment universe",
            "sector_trend": _trend(sector_row), "industry_trend": _trend(industry_row),
            "benchmarks": list(bench), "missing_benchmarks": [m for m in missing if m != sym], "gaps": gaps}


def _trend(row: Optional[dict]) -> Optional[dict]:
    if not isinstance(row, dict):
        return None
    keep = {k: row.get(k) for k in ("sector", "industry", "trend", "momentum", "score", "rank", "perf_1m_pct",
                                    "perf_3m_pct", "return_1m", "return_3m", "label") if row.get(k) is not None}
    return keep or None


def peer_comparison(sym: str, cache: dict, *, consensus: dict[str, str] | None = None, n: int = 5) -> dict:
    mine = cache.get(sym) if isinstance(cache.get(sym), dict) else None
    if not mine or not mine.get("industry"):
        return {"rows": [], "median": None, "gaps": ["peers: no industry for this symbol in the enrichment cache"]}
    cap = _f(mine.get("market_cap_b")) or 0.0
    cands = [(k, r) for k, r in cache.items() if k != sym and isinstance(r, dict)
             and r.get("industry") == mine.get("industry")]
    cands.sort(key=lambda kr: (abs(math.log((_f(kr[1].get("market_cap_b")) or 1e-3) / max(cap, 1e-3))), kr[0]))
    consensus = consensus or {}

    def row(k: str, r: dict) -> dict:
        out = {"symbol": k, "is_subject": k == sym}
        for key, _ in PEER_FIELDS:
            out[key] = _f(r.get(key))
        out["consensus"] = consensus.get(k)
        return out

    rows = [row(sym, mine)] + [row(k, r) for k, r in cands[:n]]
    med = {}
    for key, _ in PEER_FIELDS:
        vals = [r[key] for r in rows[1:] if r[key] is not None]
        med[key] = round(statistics.median(vals), 2) if vals else None
    gaps = ["EV/EBITDA and net debt/EBITDA are not in the house fundamentals (Debt/Equity shown)"]
    if len(rows) - 1 < n:
        gaps.append(f"only {len(rows) - 1} industry peers in the enrichment cache")
    return {"industry": mine.get("industry"), "rows": rows, "median": med, "fields": [k for k, _ in PEER_FIELDS],
            "labels": dict(PEER_FIELDS), "gaps": gaps}


def estimates(profile: dict | None) -> dict:
    p = profile or {}
    surprises = []
    if _f(p.get("last_eps_actual")) is not None:
        surprises.append({"date": str(p.get("last_earnings_date") or "")[:10] or None,
                          "actual": _f(p.get("last_eps_actual")), "estimate": _f(p.get("last_eps_estimate")),
                          "surprise_pct": _f(p.get("last_eps_surprise_pct"))})
    gaps = []
    if len(surprises) < 4:
        gaps.append(f"EPS surprise history: the house keeps the latest quarter only ({len(surprises)} of 4)")
    gaps.append("90-day estimate revisions: not in the house")
    return {"eps_surprises": surprises, "revisions_90d": {"up": None, "down": None},
            "next_report": str(p.get("next_earnings_date") or "")[:10] or None, "gaps": gaps}


def ownership_flows(rec: dict | None) -> dict:
    r = rec or {}
    out = {"institutional_pct": _f(r.get("inst_own_pct")), "institutional_change_pct": _f(r.get("inst_trans_pct")),
           "insider_own_pct": _f(r.get("insider_own_pct")), "insider_change_pct": _f(r.get("insider_trans_pct")),
           "short_float_pct": _f(r.get("short_float_pct")), "days_to_cover": _f(r.get("short_ratio")),
           "insider_buys_90d": None, "insider_sells_90d": None, "etf_flows_30d": None, "top_holders": None}
    out["gaps"] = ["insider transactions (count, 90d), ETF flows (30d) and top holders: not in the house"]
    return out


def _returns(s: list[tuple[str, float]]) -> dict[str, float]:
    return {s[i][0]: s[i][1] / s[i - 1][1] - 1 for i in range(1, len(s))}


def risk_technicals(bars: Any, *, ohlc: Any = None, spy: Any = None, book: dict[str, float] | None = None,
                    rec: dict | None = None) -> dict:
    s = _series(bars)[-253:]
    out: dict[str, Any] = {"gaps": []}
    if len(s) < 30:
        return {"gaps": ["price history too short for risk statistics"]}
    rets = _returns(s)
    vals = list(rets.values())
    out["vol_annualized_pct"] = round(statistics.pstdev(vals) * math.sqrt(252) * 100, 2)
    peak, mdd = s[0][1], 0.0
    for _, c in s:
        peak = max(peak, c)
        mdd = min(mdd, c / peak - 1)
    out["max_drawdown_1y_pct"] = round(mdd * 100, 2)
    spy_r = _returns(_series(spy)[-253:]) if spy else {}
    common = [d for d in rets if d in spy_r]
    if len(common) >= 30:
        x, y = [spy_r[d] for d in common], [rets[d] for d in common]
        var = statistics.pvariance(x)
        out["beta_1y"] = round(sum((a - statistics.fmean(x)) * (b - statistics.fmean(y)) for a, b in zip(x, y))
                               / len(x) / var, 2) if var else None
    else:
        out["beta_1y"] = _f((rec or {}).get("beta"))
        out["gaps"].append("beta from house fundamentals (SPY series unavailable)")
    if book:
        common = [d for d in rets if d in book]
        if len(common) >= 30:
            out["correlation_to_book"] = round(statistics.correlation([rets[d] for d in common],
                                                                     [book[d] for d in common]), 2)
    if out.get("correlation_to_book") is None:
        out["gaps"].append("correlation to book: book return series unavailable")
    closes = [c for _, c in s]
    for n in (50, 200):
        if len(closes) >= n:
            out[f"px_vs_sma{n}_pct"] = round((closes[-1] / statistics.fmean(closes[-n:]) - 1) * 100, 2)
    if len(closes) >= 15:
        gains = [max(0.0, closes[i] - closes[i - 1]) for i in range(len(closes) - 14, len(closes))]
        losses = [max(0.0, closes[i - 1] - closes[i]) for i in range(len(closes) - 14, len(closes))]
        avg_g, avg_l = sum(gains) / 14, sum(losses) / 14
        out["rsi14"] = round(100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l), 1)
    rows = [r for r in (ohlc or []) if isinstance(r, dict) and all(_f(r.get(k)) for k in ("high", "low", "close"))]
    if len(rows) >= 21:
        trs = []
        for prev, cur in zip(rows[-21:-1], rows[-20:]):
            h, low, pc = _f(cur["high"]), _f(cur["low"]), _f(prev["close"])
            trs.append(max(h - low, abs(h - pc), abs(low - pc)))
        out["atr20"] = round(statistics.fmean(trs), 2)
    else:
        out["atr20"] = None
        out["gaps"].append("ATR20: OHLC history unavailable")
    out["basis"] = "computed from house daily closes (ticker_prices), last 252 sessions"
    return out


def book_returns(holdings: dict[str, dict], bars_fn) -> dict[str, float]:
    """Current-weight book proxy: Σ weight × daily return over the last year (house closes)."""
    total = sum(float(r.get("market_value") or 0) for r in holdings.values())
    if total <= 0:
        return {}
    acc: dict[str, float] = {}
    for sym, row in holdings.items():
        w = float(row.get("market_value") or 0) / total
        try:
            rets = _returns(_series(bars_fn(sym))[-253:])
        except Exception:  # noqa: BLE001
            continue
        for d, r in rets.items():
            acc[d] = acc.get(d, 0.0) + w * r
    return acc


def today() -> date:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).date()
