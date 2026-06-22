#!/usr/bin/env python3
"""Fund technicals enrichment (operator 2026-06-21): RSI + week/month/YTD perf for MUTUAL FUNDS.

Finviz (the source of the card's RSI/W/M/YTD strip) does NOT cover mutual funds — FCNTX, AMANX, etc. come
back all-null, so their strip shows "—". Mutual funds DO have daily NAV history in yfinance, so this computes
RSI(14), perf_week, perf_month, perf_ytd, sma50 from that history and stores them in symbol_profiles. The
finviz-strip-map endpoint falls back to these when the Finviz value is null (survives Finviz rebuilds).

Targets held instrument_type='fund' symbols (or --symbols). Read-only to the broker.
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = Path(HERE).parent
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def ensure_columns():
    cur = _conn().cursor()
    cur.execute("""ALTER TABLE symbol_profiles
        ADD COLUMN IF NOT EXISTS rsi14 numeric,
        ADD COLUMN IF NOT EXISTS perf_week_pct numeric,
        ADD COLUMN IF NOT EXISTS perf_month_pct numeric,
        ADD COLUMN IF NOT EXISTS sma50_pct numeric,
        ADD COLUMN IF NOT EXISTS technicals_updated_at timestamptz""")
    cur.connection.commit()


def _held_fund_symbols():
    try:
        h = json.loads((PROJ / "data" / "portfolios" / "state" / "holdings.json").read_text())
        rows = h.get("holdings") if isinstance(h, dict) else h
        syms = {(r.get("symbol") or "").upper() for r in rows if isinstance(r, dict) and r.get("symbol")}
    except Exception:
        syms = set()
    syms.discard("CASH"); syms.discard("")
    cur = _conn().cursor()
    cur.execute("SELECT upper(symbol) FROM symbol_profiles WHERE instrument_type IN ('fund','mutual_fund') AND upper(symbol)=ANY(%s)",
                (sorted(syms),))
    return sorted({r[0] for r in cur.fetchall()})


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0)); losses.append(max(-ch, 0.0))
    # Wilder smoothing
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return round(100 - (100 / (1 + rs)), 2)


def run(symbols=None, apply=True):
    ensure_columns()
    syms = symbols or _held_fund_symbols()
    import yfinance as yf, datetime as _dt, time as _t
    conn = _conn(); cur = conn.cursor()
    done, out = 0, []
    for s in syms:
        try:
            h = yf.Ticker(s).history(period="1y", auto_adjust=False)
        except Exception as e:
            out.append({"symbol": s, "error": str(e)[:60]}); continue
        if h is None or len(h) < 30:
            out.append({"symbol": s, "error": "insufficient history"}); continue
        closes = [float(x) for x in h["Close"].tolist() if x == x]
        dates = list(h.index)
        last = closes[-1]
        def perf(n):
            return round((last - closes[-1 - n]) / closes[-1 - n] * 100, 2) if len(closes) > n and closes[-1 - n] else None
        pw = perf(5); pm = perf(21)
        # YTD from the first close of the current year
        yr = dates[-1].year
        ytd = None
        for i, dt in enumerate(dates):
            if dt.year == yr:
                if closes[i]:
                    ytd = round((last - closes[i]) / closes[i] * 100, 2)
                break
        sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
        sma50_pct = round((last - sma50) / sma50 * 100, 2) if sma50 else None
        rsi = _rsi(closes)
        rec = {"symbol": s, "rsi14": rsi, "perf_week_pct": pw, "perf_month_pct": pm,
               "perf_ytd_pct": ytd, "sma50_pct": sma50_pct}
        out.append(rec)
        if apply:
            cur.execute("""UPDATE symbol_profiles SET rsi14=%s, perf_week_pct=%s, perf_month_pct=%s,
                             ytd_return_pct=COALESCE(%s, ytd_return_pct), sma50_pct=%s, technicals_updated_at=NOW()
                           WHERE upper(symbol)=%s""", (rsi, pw, pm, ytd, sma50_pct, s))
            done += cur.rowcount
        _t.sleep(0.5)
    if apply:
        conn.commit()
    return {"ok": True, "symbols": len(syms), "updated": done, "results": out}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    syms = [x.strip().upper() for x in a.symbols.split(",")] if a.symbols else None
    print(json.dumps(run(symbols=syms, apply=not a.dry), indent=2, default=str))


if __name__ == "__main__":
    main()
