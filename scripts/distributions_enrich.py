#!/usr/bin/env python3
"""Fund/ETF distribution enrichment (operator 2026-06-21): the fund analog of the earnings line.

Funds/ETFs don't have EPS earnings — they have DISTRIBUTIONS (dividend / cap-gains payouts). yfinance's
forward ex-date is unreliable, but its distribution HISTORY is solid, so we show the real LAST distribution,
infer the cadence (JEPI monthly, SCHD quarterly, FCNTX annual…), estimate the NEXT date from that cadence
(clearly marked est), and total the trailing-12-month payout. Stored in symbol_profiles, surfaced on cards.

Held funds/ETFs (or --symbols). Read-only to the broker.
"""
from __future__ import annotations

import os
import sys
import json
import datetime as dt
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
        ADD COLUMN IF NOT EXISTS last_distribution_date date,
        ADD COLUMN IF NOT EXISTS last_distribution_amount numeric,
        ADD COLUMN IF NOT EXISTS distribution_cadence text,
        ADD COLUMN IF NOT EXISTS next_distribution_est date,
        ADD COLUMN IF NOT EXISTS ttm_distribution_amount numeric,
        ADD COLUMN IF NOT EXISTS distributions_updated_at timestamptz""")
    cur.connection.commit()


def _held_fund_etf_symbols():
    try:
        h = json.loads((PROJ / "data" / "portfolios" / "state" / "holdings.json").read_text())
        rows = h.get("holdings") if isinstance(h, dict) else h
        syms = {(r.get("symbol") or "").upper() for r in rows if isinstance(r, dict) and r.get("symbol")}
    except Exception:
        syms = set()
    syms.discard("CASH"); syms.discard("")
    cur = _conn().cursor()
    cur.execute("SELECT upper(symbol) FROM symbol_profiles WHERE instrument_type IN ('fund','etf','mutual_fund','inverse_etf') AND upper(symbol)=ANY(%s)",
                (sorted(syms),))
    return sorted({r[0] for r in cur.fetchall()})


def _cadence(days):
    """Map a median inter-distribution gap (days) to a label + canonical interval days."""
    if days <= 0:
        return None, None
    if days <= 45:
        return "monthly", 30
    if days <= 135:
        return "quarterly", 91
    if days <= 270:
        return "semi-annual", 182
    return "annual", 365


def run(symbols=None, apply=True):
    ensure_columns()
    syms = symbols or _held_fund_etf_symbols()
    import yfinance as yf, time as _t
    conn = _conn(); cur = conn.cursor()
    today = dt.date.today()
    done, out = 0, []
    for s in syms:
        try:
            div = yf.Ticker(s).dividends
            items = [(idx.date(), round(float(v), 4)) for idx, v in div.items()] if div is not None else []
        except Exception as e:
            out.append({"symbol": s, "error": str(e)[:60]}); continue
        if not items:
            out.append({"symbol": s, "note": "no distributions on record"}); continue
        items.sort(key=lambda x: x[0])
        last_date, last_amt = items[-1]
        # cadence from median gap of the last ~6 distributions
        recent = items[-7:]
        gaps = [(recent[i][0] - recent[i - 1][0]).days for i in range(1, len(recent))]
        med = sorted(gaps)[len(gaps) // 2] if gaps else 0
        cad, interval = _cadence(med)
        ttm = round(sum(a for d, a in items if (today - d).days <= 366), 4)
        # Stale schedule guard: if the last payout is older than ~400 days the fund has effectively stopped
        # distributing (e.g. ARKG/ARKX last paid 2021) — don't project a misleading "next" date.
        stale = (today - last_date).days > 400
        next_est = None
        if interval and not stale:
            next_est = last_date + dt.timedelta(days=interval)
            while next_est < today:
                next_est = next_est + dt.timedelta(days=interval)
        if stale:
            cad = "none recently"
        rec = {"symbol": s, "last_distribution_date": str(last_date), "last_distribution_amount": last_amt,
               "distribution_cadence": cad, "next_distribution_est": (str(next_est) if next_est else None),
               "ttm_distribution_amount": ttm}
        out.append(rec)
        if apply:
            cur.execute("""UPDATE symbol_profiles SET last_distribution_date=%s, last_distribution_amount=%s,
                             distribution_cadence=%s, next_distribution_est=%s, ttm_distribution_amount=%s,
                             distributions_updated_at=NOW() WHERE upper(symbol)=%s""",
                        (last_date, last_amt, cad, next_est, ttm, s))
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
