"""redeploy_price_history — shared return/risk math on the local price cache.

Sources (all local-first, provenance-tagged):
  - ticker_prices        daily closes (market_quotes sync + yfinance gap-fill)
  - ticker_dividends     distributions (yfinance backfill)
  - instrument_facts     expense ratio / yield / category (yfinance, refreshed monthly)

Honesty rules: every window metric reports the days of history it actually
used; metrics are None (never 0, never fabricated) when history is
insufficient; price return and total return are distinct fields.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATION_ANALYTICS = PROJECT_ROOT / "migrations" / "2026_07_20_redeploy_analytics.sql"

TRADING_DAYS = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252, "3Y": 756, "5Y": 1260}

# Historical stress windows (calendar bounds; each series uses what it has and
# reports coverage — a fund launched in 2021 gets no 2020 number, not a fake one).
STRESS_WINDOWS = [
    {"key": "covid_2020", "label": "COVID crash (2020-02-19 → 2020-03-23)",
     "start": date(2020, 2, 19), "end": date(2020, 3, 23)},
    {"key": "rate_shock_2022", "label": "2022 rate shock (2022-01-03 → 2022-10-12)",
     "start": date(2022, 1, 3), "end": date(2022, 10, 12)},
    {"key": "geopolitical_2022", "label": "Geopolitical escalation — Russia-Ukraine invasion shock (2022-02-18 → 2022-03-14)",
     "start": date(2022, 2, 18), "end": date(2022, 3, 14)},
    {"key": "recent_correction", "label": "Most recent 10%+ drawdown window (trailing 18M)",
     "start": None, "end": None},  # resolved per-series
]


def ensure_analytics_tables(cur) -> None:
    try:
        from lib.redeploy_schema import run_migrations_once
    except ImportError:
        from redeploy_schema import run_migrations_once
    run_migrations_once(cur, "analytics", (MIGRATION_ANALYTICS,))


# ── series loading ──────────────────────────────────────────────────────────

def load_closes(cur, symbol: str, *, days: int = 1900) -> list[tuple[date, float]]:
    cur.execute(
        """SELECT price_date, close_price FROM ticker_prices
           WHERE symbol=%s AND price_date >= %s AND close_price > 0
           ORDER BY price_date""",
        (symbol.upper(), (date.today() - timedelta(days=days)).isoformat()),
    )
    return [(r[0], float(r[1])) for r in cur.fetchall()]


def load_dividends(cur, symbol: str, *, days: int = 1900) -> list[tuple[date, float]]:
    ensure_analytics_tables(cur)
    cur.execute(
        """SELECT ex_date, amount FROM ticker_dividends
           WHERE symbol=%s AND ex_date >= %s ORDER BY ex_date""",
        (symbol.upper(), (date.today() - timedelta(days=days)).isoformat()),
    )
    return [(r[0], float(r[1])) for r in cur.fetchall()]


def get_instrument_facts(cur, symbols: list[str]) -> dict[str, dict[str, Any]]:
    ensure_analytics_tables(cur)
    if not symbols:
        return {}
    cur.execute(
        """SELECT symbol, instrument_name, quote_type, category, expense_ratio_pct,
                  distribution_yield_pct, beta_3y, sector_weights, top_holdings,
                  source, fetched_at
           FROM instrument_facts WHERE symbol = ANY(%s)""",
        ([s.upper() for s in symbols],),
    )
    cols = [d[0] for d in cur.description]
    out = {}
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        for k in ("expense_ratio_pct", "distribution_yield_pct", "beta_3y"):
            d[k] = float(d[k]) if d[k] is not None else None
        for k in ("sector_weights", "top_holdings"):
            if isinstance(d.get(k), str):
                try:
                    import json as _json
                    d[k] = _json.loads(d[k])
                except Exception:
                    d[k] = None
        out[d["symbol"]] = d
    return out


# ── series integrity ─────────────────────────────────────────────────────────
# ticker_prices mixes live market_quotes rows (recorded unadjusted at the time)
# with yfinance backfill rows (split-adjusted). A later split/spinoff makes the
# two bases disagree, producing fake >100% jumps (e.g. WDC's 2025 SanDisk
# spinoff). Windows that cross a detected break return None, never a fake number.
SERIES_BREAK_DAILY_MOVE = 0.45


def detect_series_breaks(series: list[tuple[date, float]]) -> list[date]:
    breaks = []
    for i in range(1, len(series)):
        prev = series[i - 1][1]
        if prev > 0 and abs(series[i][1] / prev - 1.0) > SERIES_BREAK_DAILY_MOVE:
            breaks.append(series[i][0])
    return breaks


def clean_after_breaks(series: list[tuple[date, float]]) -> tuple[list[tuple[date, float]], list[str]]:
    """Trim the series to the segment after the last basis break."""
    breaks = detect_series_breaks(series)
    if not breaks:
        return series, []
    last = breaks[-1]
    trimmed = [(d, v) for d, v in series if d >= last]
    notes = [f"price-basis break detected at {b} (mixed adjusted/unadjusted sources); "
             "windows before this date suppressed" for b in breaks]
    return trimmed, notes


def total_return_series(closes: list[tuple[date, float]],
                        dividends: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """Dividend-reinvested index from a close series + ex-date distributions."""
    if not closes:
        return []
    div_map: dict[date, float] = {}
    for d, amt in dividends:
        div_map[d] = div_map.get(d, 0.0) + amt
    out = []
    units = 1.0
    prev_price = closes[0][1]
    for d, px in closes:
        amt = div_map.get(d)
        if amt and prev_price > 0:
            units *= 1.0 + amt / px  # reinvest at the ex-date close
        out.append((d, units * px))
        prev_price = px
    return out


# ── metrics ──────────────────────────────────────────────────────────────────

def _window_slice(series: list[tuple[date, float]], n_days: int) -> list[tuple[date, float]]:
    return series[-n_days:] if len(series) >= 2 else []


def window_return_pct(series: list[tuple[date, float]], n_days: int,
                      *, min_coverage: float = 0.85) -> dict[str, Any] | None:
    """Return over the trailing n trading days; None if coverage is too thin."""
    if len(series) < 2:
        return None
    sl = _window_slice(series, n_days + 1)
    if len(sl) < max(2, int(n_days * min_coverage)) and len(series) < n_days:
        return None
    first, last = sl[0], sl[-1]
    if first[1] <= 0:
        return None
    return {
        "pct": round((last[1] / first[1] - 1.0) * 100.0, 2),
        "from": str(first[0]), "to": str(last[0]), "days_used": len(sl) - 1,
    }


def ytd_return_pct(series: list[tuple[date, float]]) -> dict[str, Any] | None:
    if len(series) < 2:
        return None
    year_start = date(series[-1][0].year, 1, 1)
    base = None
    for d, v in series:
        if d < year_start:
            base = (d, v)
        else:
            break
    if base is None:
        base = series[0]
        if base[0] > year_start + timedelta(days=21):
            return None
    if base[1] <= 0:
        return None
    return {"pct": round((series[-1][1] / base[1] - 1.0) * 100.0, 2),
            "from": str(base[0]), "to": str(series[-1][0])}


def standard_windows(series: list[tuple[date, float]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, nd in TRADING_DAYS.items():
        out[key] = window_return_pct(series, nd)
    out["YTD"] = ytd_return_pct(series)
    return out


def monthly_returns(series: list[tuple[date, float]], months: int = 12) -> list[dict[str, Any]]:
    if len(series) < 2:
        return []
    by_month: dict[str, tuple[date, float]] = {}
    for d, v in series:
        by_month[f"{d.year}-{d.month:02d}"] = (d, v)  # last close of month
    keys = sorted(by_month)
    rows = []
    for i in range(1, len(keys)):
        prev, curr = by_month[keys[i - 1]], by_month[keys[i]]
        if prev[1] > 0:
            rows.append({"month": keys[i], "pct": round((curr[1] / prev[1] - 1.0) * 100.0, 2)})
    return rows[-months:]


def annual_returns(series: list[tuple[date, float]]) -> list[dict[str, Any]]:
    if len(series) < 2:
        return []
    by_year: dict[int, tuple[date, float]] = {}
    for d, v in series:
        by_year[d.year] = (d, v)
    years = sorted(by_year)
    rows = []
    for i in range(1, len(years)):
        prev, curr = by_year[years[i - 1]], by_year[years[i]]
        if prev[1] > 0:
            rows.append({
                "year": years[i],
                "pct": round((curr[1] / prev[1] - 1.0) * 100.0, 2),
                "partial": (years[i] == date.today().year),
            })
    return rows


def daily_returns(series: list[tuple[date, float]]) -> list[float]:
    out = []
    for i in range(1, len(series)):
        if series[i - 1][1] > 0:
            out.append(series[i][1] / series[i - 1][1] - 1.0)
    return out


def annualized_vol_pct(series: list[tuple[date, float]], *, n_days: int = 252) -> float | None:
    rets = daily_returns(_window_slice(series, n_days + 1))
    if len(rets) < 40:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return round(math.sqrt(var) * math.sqrt(252) * 100.0, 2)


def max_drawdown_pct(series: list[tuple[date, float]]) -> dict[str, Any] | None:
    if len(series) < 10:
        return None
    peak, peak_d = series[0][1], series[0][0]
    worst, worst_from, worst_to = 0.0, None, None
    for d, v in series:
        if v > peak:
            peak, peak_d = v, d
        dd = (v / peak - 1.0) * 100.0 if peak > 0 else 0.0
        if dd < worst:
            worst, worst_from, worst_to = dd, peak_d, d
    return {"pct": round(worst, 2), "from": str(worst_from), "to": str(worst_to),
            "window_days": len(series)}


def _aligned_returns(a: list[tuple[date, float]], b: list[tuple[date, float]],
                     n_days: int = 252) -> tuple[list[float], list[float]]:
    bm = {d: v for d, v in b}
    pa, pb = [], []
    prev_a = prev_b = None
    for d, va in a[-(n_days + 1):]:
        vb = bm.get(d)
        if vb is None:
            continue
        if prev_a is not None and prev_a > 0 and prev_b > 0:
            pa.append(va / prev_a - 1.0)
            pb.append(vb / prev_b - 1.0)
        prev_a, prev_b = va, vb
    return pa, pb


def beta_vs(series: list[tuple[date, float]], bench: list[tuple[date, float]],
            *, n_days: int = 252) -> float | None:
    ra, rb = _aligned_returns(series, bench, n_days)
    if len(ra) < 40:
        return None
    mb = sum(rb) / len(rb)
    var_b = sum((r - mb) ** 2 for r in rb) / (len(rb) - 1)
    if var_b == 0:
        return None
    ma = sum(ra) / len(ra)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (len(ra) - 1)
    return round(cov / var_b, 2)


def correlation(series: list[tuple[date, float]], other: list[tuple[date, float]],
                *, n_days: int = 252) -> float | None:
    ra, rb = _aligned_returns(series, other, n_days)
    if len(ra) < 40:
        return None
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    sa = math.sqrt(sum((r - ma) ** 2 for r in ra))
    sb = math.sqrt(sum((r - mb) ** 2 for r in rb))
    if sa == 0 or sb == 0:
        return None
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    return round(cov / (sa * sb), 2)


def stress_returns(series: list[tuple[date, float]]) -> list[dict[str, Any]]:
    out = []
    for w in STRESS_WINDOWS:
        if w["key"] == "recent_correction":
            sl = _window_slice(series, 378)  # ~18 months
            dd = max_drawdown_pct(sl)
            out.append({
                "key": w["key"], "label": w["label"],
                "pct": dd["pct"] if dd else None,
                "from": dd["from"] if dd else None, "to": dd["to"] if dd else None,
                "history_available": bool(dd),
            })
            continue
        pts = [(d, v) for d, v in series if w["start"] <= d <= w["end"]]
        if len(pts) >= 2 and series[0][0] <= w["start"] + timedelta(days=10):
            out.append({
                "key": w["key"], "label": w["label"],
                "pct": round((pts[-1][1] / pts[0][1] - 1.0) * 100.0, 2),
                "from": str(pts[0][0]), "to": str(pts[-1][0]),
                "history_available": True,
            })
        else:
            out.append({"key": w["key"], "label": w["label"], "pct": None,
                        "history_available": False,
                        "note": "series does not cover this window — not fabricated"})
    return out


def series_profile(cur, symbol: str, *, bench_symbol: str = "SPY") -> dict[str, Any]:
    """Full per-symbol profile: price + total returns, vol, maxDD, beta, stress."""
    raw = load_closes(cur, symbol)
    closes, integrity_notes = clean_after_breaks(raw)
    divs = load_dividends(cur, symbol)
    tr = total_return_series(closes, divs)
    bench_raw = load_closes(cur, bench_symbol) if symbol.upper() != bench_symbol else raw
    bench, _ = clean_after_breaks(bench_raw)
    return {
        "symbol": symbol.upper(),
        "as_of": str(closes[-1][0]) if closes else None,
        "history_days": len(closes),
        "history_start": str(closes[0][0]) if closes else None,
        "series_integrity_notes": integrity_notes or None,
        "price_return": standard_windows(closes),
        "total_return": standard_windows(tr) if divs else None,
        "total_return_basis": ("dividends_reinvested" if divs
                               else "no distribution history cached — price return only"),
        "monthly_returns_12m": monthly_returns(tr or closes, 12),
        "annual_returns": annual_returns(tr or closes),
        "volatility_1y_pct": annualized_vol_pct(closes),
        "max_drawdown": max_drawdown_pct(closes),
        "beta_1y_vs_spy": beta_vs(closes, bench),
        "stress": stress_returns(closes),
        "return_kind_note": "price_return excludes distributions; total_return reinvests them",
    }


# ── backfill (extends the existing price cache; provenance tagged) ───────────

def backfill_symbol_history(symbols: list[str], *, period: str = "5y",
                            sleep_sec: float = 0.35) -> dict[str, Any]:
    """5y closes + dividends + facts via yfinance into the local cache.

    Requires the repo venv (yfinance). Never fabricates: symbols that fail are
    reported failed and their metrics stay None downstream.
    """
    import time

    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance not installed (run under .venv)", "filled": []}

    from db_adapter import _get_conn

    conn = _get_conn()
    cur = conn.cursor()
    ensure_analytics_tables(cur)
    conn.commit()
    filled, failed = [], []
    for sym in [str(s).upper().strip() for s in symbols if s]:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period=period, interval="1d", auto_adjust=False)
            if hist is None or len(hist) == 0:
                failed.append(sym)
                continue
            n_px = 0
            for idx, row in hist.iterrows():
                px = float(row.get("Close") or 0)
                if px <= 0:
                    continue
                cur.execute(
                    """INSERT INTO ticker_prices (symbol, price_date, close_price, source)
                       VALUES (%s,%s,%s,'yfinance')
                       ON CONFLICT (symbol, price_date) DO NOTHING""",
                    (sym, idx.date(), round(px, 4)),
                )
                n_px += cur.rowcount
            n_dv = 0
            try:
                for idx, amt in t.dividends.items():
                    if float(amt) <= 0:
                        continue
                    cur.execute(
                        """INSERT INTO ticker_dividends (symbol, ex_date, amount, source)
                           VALUES (%s,%s,%s,'yfinance')
                           ON CONFLICT (symbol, ex_date) DO NOTHING""",
                        (sym, idx.date(), round(float(amt), 6)),
                    )
                    n_dv += cur.rowcount
            except Exception:
                pass
            sector_weights = None
            top_holdings = None
            try:
                fd = t.funds_data
                sw = fd.sector_weightings or {}
                if sw:
                    # yfinance keys like 'realestate'; values are fractions
                    label = {
                        "realestate": "Real Estate", "consumer_cyclical": "Consumer Cyclical",
                        "basic_materials": "Basic Materials", "consumer_defensive": "Consumer Defensive",
                        "technology": "Technology", "communication_services": "Communication Services",
                        "financial_services": "Financial Services", "utilities": "Utilities",
                        "industrials": "Industrials", "energy": "Energy", "healthcare": "Healthcare",
                    }
                    sector_weights = {label.get(k, k.replace("_", " ").title()): round(float(v) * 100.0, 2)
                                      for k, v in sw.items() if float(v) > 0}
                th = fd.top_holdings
                if th is not None and len(th):
                    top_holdings = [
                        {"ticker": str(ix), "name": str(row.get("Name") or "")[:60],
                         "weight": round(float(row.get("Holding Percent") or 0) * 100.0, 2)}
                        for ix, row in th.iterrows()
                    ][:15]
            except Exception:
                pass
            try:
                info = t.info or {}
                er = info.get("netExpenseRatio") or info.get("annualReportExpenseRatio")
                # yfinance mixes percent and fraction units across versions/fields.
                # ERs run 0.03–1.5 (%): anything below 0.02 must be a fraction.
                if er is not None:
                    er = float(er)
                    if er < 0.02:
                        er *= 100.0
                dy = info.get("dividendYield")
                if dy is not None:
                    dy = float(dy)
                    if dy < 0.25:  # fraction form (0.03 = 3%); percent form is 0.25+
                        dy *= 100.0
                import json as _json
                cur.execute(
                    """INSERT INTO instrument_facts
                       (symbol, instrument_name, quote_type, category, expense_ratio_pct,
                        distribution_yield_pct, beta_3y, sector_weights, top_holdings,
                        source, fetched_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,'yfinance',NOW())
                       ON CONFLICT (symbol) DO UPDATE SET
                         instrument_name=EXCLUDED.instrument_name,
                         quote_type=EXCLUDED.quote_type,
                         category=EXCLUDED.category,
                         expense_ratio_pct=EXCLUDED.expense_ratio_pct,
                         distribution_yield_pct=EXCLUDED.distribution_yield_pct,
                         beta_3y=EXCLUDED.beta_3y,
                         sector_weights=COALESCE(EXCLUDED.sector_weights, instrument_facts.sector_weights),
                         top_holdings=COALESCE(EXCLUDED.top_holdings, instrument_facts.top_holdings),
                         fetched_at=NOW()""",
                    (sym, (info.get("longName") or info.get("shortName") or "")[:120] or None,
                     info.get("quoteType"), info.get("category"),
                     er, dy,
                     float(info["beta"]) if info.get("beta") is not None else None,
                     _json.dumps(sector_weights) if sector_weights else None,
                     _json.dumps(top_holdings) if top_holdings else None),
                )
            except Exception:
                pass
            conn.commit()
            filled.append({"symbol": sym, "prices_added": n_px, "dividends_added": n_dv})
        except Exception:
            conn.rollback()
            failed.append(sym)
        if sleep_sec:
            time.sleep(sleep_sec)
    return {"filled": filled, "failed": failed,
            "as_of": datetime.now(timezone.utc).isoformat()}
