#!/usr/bin/env python3
"""Earnings enrichment (operator 2026-06-21): next earnings date + last-quarter beat/miss for held stocks.

Adds to symbol_profiles: next_earnings_date, last_earnings_date, last_eps_estimate, last_eps_actual,
last_eps_surprise_pct (and earnings_updated_at). Source: yfinance get_earnings_dates() — the most recent
PAST row with a reported EPS is last quarter (beat = surprise >= 0); the nearest FUTURE row is the next
report. Stocks only (ETFs/funds have no per-issuer earnings). Read-only to the broker.

  python3 scripts/earnings_enrich.py            # held stocks
  python3 scripts/earnings_enrich.py --symbols NOC,LMT
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
        ADD COLUMN IF NOT EXISTS next_earnings_date date,
        ADD COLUMN IF NOT EXISTS last_earnings_date date,
        ADD COLUMN IF NOT EXISTS last_eps_estimate numeric,
        ADD COLUMN IF NOT EXISTS last_eps_actual numeric,
        ADD COLUMN IF NOT EXISTS last_eps_surprise_pct numeric,
        ADD COLUMN IF NOT EXISTS earnings_updated_at timestamptz""")
    cur.connection.commit()


def _held_stock_symbols():
    try:
        h = json.loads((PROJ / "data" / "portfolios" / "state" / "holdings.json").read_text())
        rows = h.get("holdings") if isinstance(h, dict) else h
        syms = {(r.get("symbol") or "").upper() for r in rows if isinstance(r, dict) and r.get("symbol")}
    except Exception:
        syms = set()
    syms.discard("CASH"); syms.discard("")
    cur = _conn().cursor()
    cur.execute("""SELECT upper(symbol) FROM symbol_profiles
                   WHERE (instrument_type='stock' OR instrument_type IS NULL) AND upper(symbol) = ANY(%s)
                     AND symbol ~ '^[A-Z]{1,5}$'""", (sorted(syms),))
    return sorted({r[0] for r in cur.fetchall()})


def _fnum(v):
    try:
        f = float(v)
        return None if f != f else round(f, 4)   # NaN guard
    except Exception:
        return None


def _extract(ed):
    """From a yfinance earnings_dates DataFrame (index=Timestamp, cols: 'EPS Estimate','Reported EPS',
    'Surprise(%)'), return (next_date, last_date, est, actual, surprise_pct)."""
    import datetime as _dt
    next_d = last = est = act = sur = None
    try:
        rows = []
        for idx, row in ed.iterrows():
            d = idx.date() if hasattr(idx, "date") else None
            rows.append((d, _fnum(row.get("EPS Estimate")), _fnum(row.get("Reported EPS")), _fnum(row.get("Surprise(%)"))))
        today = _dt.date.today()
        # next = earliest future date with no reported EPS
        futures = sorted([r for r in rows if r[0] and r[0] >= today], key=lambda r: r[0])
        for r in futures:
            if r[2] is None:
                next_d = r[0]; break
        # last = most recent past date that HAS a reported EPS
        pasts = sorted([r for r in rows if r[0] and r[0] < today and r[2] is not None], key=lambda r: r[0], reverse=True)
        if pasts:
            last, est, act, sur = pasts[0]
    except Exception:
        pass
    return next_d, last, est, act, sur


def run(symbols=None, apply=True):
    ensure_columns()
    syms = symbols or _held_stock_symbols()
    import yfinance as yf, time as _t
    conn = _conn(); cur = conn.cursor()
    done, out = 0, []
    for s in syms:
        try:
            ed = yf.Ticker(s).get_earnings_dates(limit=12)
        except Exception as e:
            out.append({"symbol": s, "error": str(e)[:60]}); continue
        if ed is None or len(ed) == 0:
            out.append({"symbol": s, "error": "no earnings_dates"}); continue
        nd, ld, est, act, sur = _extract(ed)
        rec = {"symbol": s, "next_earnings_date": str(nd) if nd else None,
               "last_earnings_date": str(ld) if ld else None, "last_eps_estimate": est,
               "last_eps_actual": act, "last_eps_surprise_pct": sur,
               "beat": (None if sur is None else sur >= 0)}
        out.append(rec)
        if apply:
            cur.execute("""UPDATE symbol_profiles SET next_earnings_date=%s, last_earnings_date=%s,
                             last_eps_estimate=%s, last_eps_actual=%s, last_eps_surprise_pct=%s,
                             earnings_updated_at=NOW() WHERE upper(symbol)=%s""",
                        (nd, ld, est, act, sur, s))
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
