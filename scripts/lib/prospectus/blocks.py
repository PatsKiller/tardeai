"""Institutional data blocks, computed here from house series (never model output).

relative_performance, peer_comparison, estimates, ownership_flows, risk_technicals and the scenario anchors. Every
input comes from a house store (ticker_prices via data_broker.daily_bars / ohlc_bars, the Finviz enrichment cache,
symbol_profiles, analyst targets, the sector/industry momentum runtime files). A value the house does not hold is
``None`` with the gap named, never estimated.
"""
from __future__ import annotations

from datetime import date, timedelta
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

#: The Finviz enrichment cache's ``market_cap_b`` is Finviz "Market Cap" in MILLIONS of dollars despite its name
#: (finviz_enrichment.py maps the column as-is; multi_strategy_classifier.py documents and converts the same field).
#: ``market_cap_usd`` (dollars) is preferred when present. Rule: convert ONLY from the raw cache record through
#: ``market_cap_billions``; never write the converted value back into a record, so nothing is normalised twice.
FINVIZ_MARKET_CAP_DIVISOR_TO_B = 1000.0

#: Price-series plausibility (operator 2026-10-26): one pre-listing quote row far below a new listing's first session
#: produced an impossible beta, volatility, 1Y low and YTD return in a live prospectus. A close more than
#: ``SERIES_LEVEL_FACTOR`` times away from the median of its next/previous ``SERIES_CONFIRM_SESSIONS`` closes, with
#: at most ``SERIES_MAX_ISOLATED`` such rows in a row, is an isolated bad bar (pre-listing / symbol reuse / bad
#: print) and is excluded. A persistent jump of the same size (unadjusted split, symbol reuse) is a series BREAK:
#: statistics use only the clean segment after the last break.
SERIES_LEVEL_FACTOR = 3.0
SERIES_CONFIRM_SESSIONS = 10
SERIES_MAX_ISOLATED = 2
#: Minimum clean sessions (closes) before a statistic is printed; below it the value is null with a reason.
MIN_SESSIONS = {"vol_annualized_pct": 61, "beta_1y": 61, "correlation_to_book": 61, "max_drawdown_1y_pct": 240,
                "rate_beta_10y": 61}


def market_cap_billions(rec: dict | None) -> Optional[float]:
    """Market cap in $B from a raw enrichment-cache record (see FINVIZ_MARKET_CAP_DIVISOR_TO_B)."""
    r = rec or {}
    usd = _f(r.get("market_cap_usd"))
    if usd is not None and usd > 0:
        return round(usd / 1e9, 2)
    raw = _f(r.get("market_cap_b"))
    return None if raw is None else round(raw / FINVIZ_MARKET_CAP_DIVISOR_TO_B, 2)


def _f(v: Any) -> Optional[float]:
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


_HOLIDAYS: dict[int, set] = {}


def _nyse_holidays(year: int) -> set:
    if year not in _HOLIDAYS:
        try:
            try:
                from lib.cio_market_session import nyse_holidays  # type: ignore
            except ImportError:
                from scripts.lib.cio_market_session import nyse_holidays  # type: ignore
            _HOLIDAYS[year] = set(nyse_holidays(year))
        except Exception:  # noqa: BLE001 - weekends are still excluded without the holiday table
            _HOLIDAYS[year] = set()
    return _HOLIDAYS[year]


def is_session(day: Any) -> bool:
    """True for an NYSE session date. ``ticker_prices`` also holds Saturday/Sunday and holiday rows (a quote copied
    forward by the Finviz and market-quote writers): they are not sessions, and counting them made "1W = 5 bars" and
    "1Y = 252 bars" span less than a week / a year and flattened volatility (accuracy audit 2026-10-26)."""
    try:
        d = day if isinstance(day, date) else date.fromisoformat(str(day)[:10])
    except (TypeError, ValueError):
        return False
    return d.weekday() < 5 and d not in _nyse_holidays(d.year)


def _series(bars: Iterable[Any]) -> list[tuple[str, float]]:
    """Sorted (date, close) for NYSE sessions only, one close per date (the last row for a date wins)."""
    by_day: dict[str, float] = {}
    for b in bars or []:
        d, c = (b.get("price_date"), b.get("close")) if isinstance(b, dict) else (b[0], b[1])
        c = _f(c)
        if d and c and c > 0 and is_session(d):
            by_day[str(d)[:10]] = c
    return sorted(by_day.items())


def _far(a: float, b: float, factor: float = SERIES_LEVEL_FACTOR) -> bool:
    return a > 0 and b > 0 and max(a, b) / min(a, b) > factor


def clean_series(s: list[tuple[str, float]]) -> tuple[list[tuple[str, float]], list[dict], Optional[dict]]:
    """(clean segment, excluded bad bars, last break) for a sorted (date, close) series.

    1. Isolated bars: a run of at most SERIES_MAX_ISOLATED closes that is more than SERIES_LEVEL_FACTOR away from the
       median of the SERIES_CONFIRM_SESSIONS closes on BOTH sides (or on the only side, at the start / end of the
       series) is excluded with a reason. The neighbours must agree with each other, so a genuine regime is never
       mistaken for an isolated bar.
    2. Breaks: a day-over-day jump larger than SERIES_LEVEL_FACTOR that persists (an unadjusted split or a reused
       symbol) splits the series; only the segment after the last break is returned.
    """
    n, k = len(s), SERIES_CONFIRM_SESSIONS
    excluded: list[dict] = []
    keep = [True] * n
    i = 0
    while i < n:
        for run in range(1, SERIES_MAX_ISOLATED + 1):
            j = i + run  # candidate run is s[i:j]
            if j > n:
                break
            before = [c for _, c in s[max(0, i - k):i]]
            after = [c for _, c in s[j:j + k]]
            sides = [statistics.median(x) for x in (before, after) if len(x) >= min(3, k)]
            if not sides or (len(sides) == 2 and _far(sides[0], sides[1])):
                continue
            if all(_far(c, m) for _, c in s[i:j] for m in sides):
                where = "first rows of the series (pre-listing or reused-symbol data)" if i == 0 else (
                    "last rows of the series" if j == n else "isolated bad print")
                for d, c in s[i:j]:
                    excluded.append({"date": d, "close": c, "reason": f"{where}: more than {SERIES_LEVEL_FACTOR:g}x "
                                                                       f"away from the neighbouring {k} sessions"})
                for x in range(i, j):
                    keep[x] = False
                i = j - 1
                break
        i += 1
    kept = [p for p, ok in zip(s, keep) if ok]
    brk = None
    for x in range(1, len(kept)):
        if _far(kept[x - 1][1], kept[x][1]):
            brk = {"date": kept[x][0], "from": kept[x - 1][1], "to": kept[x][1],
                   "reason": "series break (unadjusted split or reused symbol): statistics use the segment after it"}
    if brk:
        kept = [p for p in kept if p[0] >= brk["date"]]
    return kept, excluded, brk


def series_quality(bars: Any) -> dict:
    """Clean series plus a plain-language account of what was excluded (exposed in the blocks)."""
    raw = _series(bars)
    clean, excluded, brk = clean_series(raw)
    notes = []
    if excluded:
        notes.append(f"excluded {len(excluded)} bad bar(s): " + "; ".join(f"{e['date']} ({e['reason']})" for e in excluded[:3]))
    if brk:
        notes.append(f"series break on {brk['date']}: {brk['reason']}")
    return {"series": clean, "excluded": excluded, "break": brk, "raw_sessions": len(raw),
            "clean_sessions": len(clean), "clean_from": clean[0][0] if clean else None, "notes": notes}


def unreliable_reason(metric: str, q: dict) -> Optional[str]:
    """None when the clean series supports ``metric``; else the reason it is not printed."""
    need = MIN_SESSIONS.get(metric)
    have = min(int(q.get("clean_sessions") or 0), 253)
    if need is None or have >= need:
        return None
    why = f"only {have} clean sessions since {q.get('clean_from') or 'n/a'} (needs {need})"
    if q.get("notes"):
        why += "; " + "; ".join(q["notes"])
    return why


#: Calendar span of each window. A window starts at the last session on or before (last date − span); a series
#: that begins up to WINDOW_START_GRACE_DAYS after that point still covers the window (its first session is used).
WINDOW_DAYS = {"1W": 7, "1M": 30, "3M": 91, "1Y": 365, "3Y": 1095}
WINDOW_START_GRACE_DAYS = 4


def _start_index(s: list[tuple[str, float]], window: str) -> Optional[int]:
    if not s:
        return None
    if window == "YTD":
        year = s[-1][0][:4]
        idx = next((i for i, (d, _) in enumerate(s) if d[:4] == year), None)
        # YTD needs the prior year's last close; a series that starts this year has no YTD figure.
        return idx - 1 if idx else None
    end = date.fromisoformat(s[-1][0])
    target = end - timedelta(days=WINDOW_DAYS[window])
    idx = None
    for i, (d, _) in enumerate(s):
        if d <= target.isoformat():
            idx = i
        else:
            break
    if idx is None and date.fromisoformat(s[0][0]) <= target + timedelta(days=WINDOW_START_GRACE_DAYS):
        idx = 0
    return idx if idx is not None and idx < len(s) - 1 else None


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
    quality = series_quality(bars)
    s = quality["series"]
    named = {sym: s, **{k: clean_series(_series(v))[0] for k, v in bench.items()}}
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
    gaps += [f"{sym} price history: {n}" for n in quality["notes"]]
    return {"series": series, "series_quality": {k: quality[k] for k in ("excluded", "break", "raw_sessions",
                                                                           "clean_sessions", "clean_from", "notes")}, "returns": returns, "excess_vs_spy": excess, "rank_in_industry": rank,
            "rs_rating_12m": rs, "rs_basis": "percentile of 1Y return across the Finviz enrichment universe",
            "sector_trend": _trend(sector_row), "industry_trend": _trend(industry_row),
            "benchmarks": list(bench), "missing_benchmarks": [m for m in missing if m != sym], "gaps": gaps}


def _trend(row: Optional[dict]) -> Optional[dict]:
    if not isinstance(row, dict):
        return None
    keep = {k: row.get(k) for k in ("sector", "industry", "trend", "momentum", "score", "rank", "perf_1m_pct",
                                    "perf_3m_pct", "return_1m", "return_3m", "label") if row.get(k) is not None}
    return keep or None


#: Finviz files every ETF under one industry, "Exchange Traded Fund"; that cohort is meaningless as peers (it sorts
#: alphabetically: AAA, AAAA, AAAC …). ETF peers come only from ``config/prospectus.json`` ``etf_peer_groups``.
ETF_INDUSTRY = "exchange traded fund"


def etf_peer_group(sym: str, groups: dict | None) -> tuple[Optional[str], list[str]]:
    for name, spec in (groups or {}).items():
        if str(name).startswith("_") or not isinstance(spec, (list, dict)):
            continue  # "_note" and other commentary keys
        members = [str(m).upper() for m in ((spec.get("members") if isinstance(spec, dict) else spec) or [])]
        if sym in members:
            return name, [m for m in members if m != sym]
    return None, []


#: A peer must be within this size multiple of the subject (either way); a company 1/1000th the size is not a peer.
PEER_SIZE_BAND = 20.0
#: ... and must carry at least this share of the peer fields (EV/EBITDA, never in the house, is not counted).
PEER_MIN_FILLED = 0.4


def _filled(r: dict) -> float:
    keys = [k for k, _ in PEER_FIELDS if k not in ("ev_ebitda", "market_cap_b")]
    return sum(1 for k in keys if _f(r.get(k)) is not None) / len(keys)


def size_matched_peers(sym: str, mine: dict, cache: dict, *, n: int = 5) -> tuple[list, Optional[str]]:
    """Peers by industry AND size: same industry within PEER_SIZE_BAND of the subject's market cap, closest size first;
    when fewer than 3 qualify, the same sector fills in (still within the band) and the gap says so. Rows that are
    mostly n/a never make the table (operator 2026-10-27: a mega-cap's "peers" were micro-caps with empty rows)."""
    cap = market_cap_billions(mine) or 0.0

    def ok(k: str, r: dict) -> bool:
        if k == sym or not isinstance(r, dict) or _filled(r) < PEER_MIN_FILLED:
            return False
        c = market_cap_billions(r)
        return cap <= 0 or (c is not None and c > 0 and 1 / PEER_SIZE_BAND <= c / cap <= PEER_SIZE_BAND)

    def dist(kr: tuple) -> tuple:
        return (abs(math.log((market_cap_billions(kr[1]) or 1e-3) / max(cap, 1e-3))), kr[0])

    ind = sorted([(k, r) for k, r in cache.items() if ok(k, r) and r.get("industry") == mine.get("industry")], key=dist)
    if len(ind) >= 3:
        return ind, None
    taken = {k for k, _ in ind}
    sec = sorted([(k, r) for k, r in cache.items() if mine.get("sector") and k not in taken and ok(k, r)
                  and r.get("sector") == mine.get("sector")], key=dist)
    out = ind + sec[: max(0, n - len(ind))]
    if len(out) >= 3:
        return out, (f"peers widened to the {mine.get('sector')} sector by size: only {len(ind)} {mine.get('industry')} "
                     f"companies are within {PEER_SIZE_BAND:g}x of its market cap" if sec else None)
    # Too thin a cache for the size / fill rules: the industry cohort by size closeness, as before, and say so.
    rest = sorted([(k, r) for k, r in cache.items() if k != sym and isinstance(r, dict)
                   and r.get("industry") == mine.get("industry") and k not in {x for x, _ in out}], key=dist)
    out = out + rest[: max(0, n - len(out))]
    return out, (f"peers: fewer than 3 {mine.get('industry')} companies within {PEER_SIZE_BAND:g}x of its size with "
                 f"enough data; the closest-size industry members are shown" if rest else None)


def peer_comparison(sym: str, cache: dict, *, consensus: dict[str, str] | None = None, n: int = 5,
                    etf_groups: dict | None = None) -> dict:
    mine = cache.get(sym) if isinstance(cache.get(sym), dict) else None
    if (not mine or not mine.get("industry")) and etf_peer_group(sym, etf_groups)[0]:
        # a fund the Finviz cache does not carry, but with a configured category peer group: compare the peers anyway
        # (the subject row shows what the house holds for it, usually nothing) instead of an empty table
        mine = {"industry": "Exchange Traded Fund", **(mine or {})}
    if not mine or not mine.get("industry"):
        return {"rows": [], "median": None, "gaps": ["peers: no industry for this symbol in the enrichment cache"]}
    consensus = consensus or {}

    def row(k: str, r: dict) -> dict:
        out = {"symbol": k, "is_subject": k == sym}
        for key, _ in PEER_FIELDS:
            out[key] = market_cap_billions(r) if key == "market_cap_b" else _f(r.get(key))
        out["consensus"] = consensus.get(k)
        return out

    group, widened = None, None
    if str(mine.get("industry")).strip().lower() == ETF_INDUSTRY:
        group, members = etf_peer_group(sym, etf_groups)
        cands = [(k, cache[k]) for k in members if isinstance(cache.get(k), dict)]
        if not cands:
            why = (f"peers not available: no member of the '{group}' ETF peer group is in the enrichment cache" if group
                   else "peers not available: this ETF has no category peer group in config/prospectus.json "
                        "etf_peer_groups (the Finviz ETF cohort is alphabetical, not a peer set)")
            return {"industry": mine.get("industry"), "peer_group": group, "rows": [row(sym, mine)], "median": None,
                    "fields": [k for k, _ in PEER_FIELDS], "labels": dict(PEER_FIELDS), "gaps": [why]}
    else:
        cands, widened = size_matched_peers(sym, mine, cache, n=n)

    rows = [row(sym, mine)] + [row(k, r) for k, r in cands[:n]]
    med = {}
    for key, _ in PEER_FIELDS:
        vals = [r[key] for r in rows[1:] if r[key] is not None]
        med[key] = round(statistics.median(vals), 2) if vals else None
    gaps = ["EV/EBITDA and net debt/EBITDA are not in the house fundamentals (Debt/Equity shown)"]
    if group is None and widened:
        gaps.append(widened)
    if len(rows) - 1 < n:
        gaps.append(f"only {len(rows) - 1} industry peers in the enrichment cache")
    return {"industry": mine.get("industry"), "peer_group": group, "rows": rows, "median": med, "fields": [k for k, _ in PEER_FIELDS],
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
                    rec: dict | None = None, subject: str | None = None) -> dict:
    """Risk statistics over the CLEAN series (``clean_series``). A statistic the clean series cannot support is
    ``None`` with its reason in ``unreliable`` — never a number computed over bad bars. Correlation to the book uses
    the book WITHOUT ``subject`` (leave-one-out), so a large holding is not correlated with itself."""
    quality = series_quality(bars)
    s = quality["series"][-253:]
    out: dict[str, Any] = {"gaps": [], "unreliable": {},
                           "series_quality": {k: quality[k] for k in ("excluded", "break", "raw_sessions",
                                                                      "clean_sessions", "clean_from", "notes")}}
    if len(s) < 30:
        return {**out, "gaps": ["price history too short for risk statistics"] + quality["notes"]}

    def gate(metric: str) -> bool:
        why = unreliable_reason(metric, quality)
        if why:
            out[metric] = None
            out["unreliable"][metric] = why
        return why is None

    rets = _returns(s)
    vals = list(rets.values())
    if gate("vol_annualized_pct"):
        out["vol_annualized_pct"] = round(statistics.pstdev(vals) * math.sqrt(252) * 100, 2)
    if gate("max_drawdown_1y_pct"):
        peak, mdd = s[0][1], 0.0
        for _, c in s:
            peak = max(peak, c)
            mdd = min(mdd, c / peak - 1)
        out["max_drawdown_1y_pct"] = round(mdd * 100, 2)
    if gate("beta_1y"):
        spy_r = _returns(clean_series(_series(spy))[0][-253:]) if spy else {}
        common = [d for d in rets if d in spy_r]
        if len(common) >= 30:
            x, y = [spy_r[d] for d in common], [rets[d] for d in common]
            var = statistics.pvariance(x)
            out["beta_1y"] = round(sum((a - statistics.fmean(x)) * (b - statistics.fmean(y)) for a, b in zip(x, y))
                                   / len(x) / var, 2) if var else None
        else:
            out["beta_1y"] = _f((rec or {}).get("beta"))
            out["gaps"].append("beta from house fundamentals (SPY series unavailable)")
    if book and gate("correlation_to_book"):
        series, why = book_without(book, subject)
        if series is None:
            out["unreliable"]["correlation_to_book"] = why
        else:
            common = [d for d in rets if d in series]
            if len(common) >= 30:
                out["correlation_to_book"] = round(statistics.correlation([rets[d] for d in common],
                                                                         [series[d] for d in common]), 2)
                out["correlation_basis"] = why
    if out.get("correlation_to_book") is None and "correlation_to_book" not in out["unreliable"]:
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
    first = s[0][0]
    rows = [r for r in (ohlc or []) if isinstance(r, dict) and all(_f(r.get(k)) for k in ("high", "low", "close"))
            and str(r.get("price_date") or r.get("date") or first)[:10] >= first]
    if len(rows) >= 21:
        trs = []
        for prev, cur in zip(rows[-21:-1], rows[-20:]):
            h, low, pc = _f(cur["high"]), _f(cur["low"]), _f(prev["close"])
            trs.append(max(h - low, abs(h - pc), abs(low - pc)))
        out["atr20"] = round(statistics.fmean(trs), 2)
    else:
        out["atr20"] = None
        out["gaps"].append("ATR20: OHLC history unavailable")
    out["gaps"] += [f"{m}: not reliable ({why})" for m, why in out["unreliable"].items()]
    out["basis"] = (f"computed from house daily closes (ticker_prices), last {len(s)} clean sessions"
                    + (f" ({len(quality['excluded'])} bad bar(s) excluded)" if quality["excluded"] else ""))
    return out


class BookSeries(dict):
    """Weighted book daily returns {date: return}, plus each holding's weighted contribution so one holding can be
    left out (``book_without``)."""

    def __init__(self, *args: Any, **kw: Any):
        super().__init__(*args, **kw)
        self.components: dict[str, dict[str, float]] = {}
        self.weights: dict[str, float] = {}


def book_returns(holdings: dict[str, dict], bars_fn) -> BookSeries:
    """Current-weight book proxy: Σ weight × daily return over the last year (house closes, clean series only)."""
    acc = BookSeries()
    total = sum(float(r.get("market_value") or 0) for r in holdings.values())
    if total <= 0:
        return acc
    for sym, row in holdings.items():
        w = float(row.get("market_value") or 0) / total
        try:
            rets = _returns(clean_series(_series(bars_fn(sym)))[0][-253:])
        except Exception:  # noqa: BLE001
            continue
        acc.weights[sym] = w
        acc.components[sym] = {d: w * r for d, r in rets.items()}
        for d, r in rets.items():
            acc[d] = acc.get(d, 0.0) + w * r
    return acc


def book_without(book: dict[str, float], subject: str | None) -> tuple[Optional[dict[str, float]], str]:
    """(book series excluding ``subject``, basis). Leave-one-out, renormalised to the remaining weight."""
    comps = getattr(book, "components", None)
    weights = getattr(book, "weights", None)
    if comps is None:
        return dict(book), "current-weight book (per-holding components unavailable; not leave-one-out)"
    if not subject or subject not in comps:
        return dict(book), "current-weight book (this symbol is not in it)"
    rest = 1.0 - float(weights.get(subject) or 0.0)
    if rest < 0.02:
        return None, "the book is (almost) only this holding; a correlation with itself is meaningless"
    mine = comps[subject]
    return ({d: (v - mine.get(d, 0.0)) / rest for d, v in book.items()},
            "current-weight book excluding this holding (leave-one-out)")


def today() -> date:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).date()
