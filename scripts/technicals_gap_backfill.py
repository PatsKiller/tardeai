#!/usr/bin/env python3
"""technicals_gap_backfill.py — fill + WATCH for missing technicals (operator 2026-06-12).

Finviz (the ticker_snapshot_daily source) carries no mutual-fund data, so held funds (FCNTX, AMANX,
401k-style NAV funds) sat with NULL RSI/SMA — which poisons position intelligence and would feed
garbage to the LLM protection advisor. This script:

  1. Finds HELD + watchlist symbols whose latest snapshot has rsi IS NULL
  2. Computes RSI14 / SMA20-50-200 distance / week-month perf from yfinance daily NAV/closes
     (funds have real NAVs; computed honestly, source='nav_computed')
  3. Upserts into ticker_snapshot_daily — same table, same downstream pipeline, no UI changes needed
  4. Symbols with NO price series anywhere (delisted, e.g. SRNE) are recorded as delisted_or_no_data
     — surfaced, never faked
  5. --alert: Telegram report when symbols REMAIN missing after backfill (the "agent that checks
     regularly" — wire via cron)

  python3 scripts/technicals_gap_backfill.py [--alert] [--symbols X,Y]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import datetime as dt
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _held_symbols() -> set:
    from holding_proxies import HOLDING_PROXY_MAP
    h = json.loads((PROJECT_ROOT / "data/portfolios/state/holdings.json").read_text())
    out = set()
    for x in h.get("holdings", []):
        sym = (x.get("symbol") or "").upper()
        if x.get("is_cash") or sym == "CASH":
            continue
        # public tickers AND proxy-mapped fund codes (401k pools, institutional funds) are in scope
        if re.fullmatch(r"[A-Z]{1,5}", sym) or sym in HOLDING_PROXY_MAP:
            out.add(sym)
    return out


def _missing(cur, universe):
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, rsi, data FROM ticker_snapshot_daily
                   WHERE symbol = ANY(%s) ORDER BY symbol, snapshot_date DESC""", (sorted(universe),))
    latest = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    out = []
    for s in universe:
        rsi, data = latest.get(s, (None, None))
        if rsi is not None:
            continue
        d = data if isinstance(data, dict) else {}
        if d.get("delisted_or_no_data"):
            continue        # operator 2026-06-12: IGNORE delisted assets — marked once, never re-nagged
        out.append(s)
    return sorted(out)


def _compute(closes):
    import statistics
    c = closes
    out = {}
    if len(c) >= 15:
        gains = losses = 0.0
        for i in range(-14, 0):
            d = c[i] - c[i - 1]
            gains += max(d, 0); losses += max(-d, 0)
        out["rsi"] = round(100 - 100 / (1 + gains / losses), 2) if losses else 100.0
    px = c[-1]
    for n, k in ((20, "sma20_pct"), (50, "sma50_pct"), (200, "sma200_pct")):
        if len(c) >= n:
            sma = sum(c[-n:]) / n
            out[k] = round((px - sma) / sma * 100, 2)
    if len(c) >= 6:
        out["perf_week_pct"] = round((px - c[-6]) / c[-6] * 100, 2)
    if len(c) >= 22:
        out["perf_month_pct"] = round((px - c[-22]) / c[-22] * 100, 2)
    return out


def run(symbols=None, alert=False):
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    universe = set(s.upper() for s in symbols) if symbols else _held_symbols()
    missing = _missing(cur, universe)
    if not missing:
        print(json.dumps({"status": "clean", "checked": len(universe), "missing": 0}))
        return
    import yfinance as yf
    from holding_proxies import HOLDING_PROXY_MAP
    filled, dead = [], []
    today = dt.date.today()
    def _closes(ticker):
        try:
            hist = yf.Ticker(ticker).history(period="1y")
            return [float(v) for v in hist["Close"].tolist()] if len(hist) else []
        except Exception:
            return []

    for sym in missing:
        # fund codes with no public ticker route through their asset-class proxy ETF
        # (operator-approved 2026-06-12); result is stored under the FUND code, source='proxy:<ETF>'
        proxy = HOLDING_PROXY_MAP.get(sym)
        is_public = bool(re.fullmatch(r"[A-Z]{1,5}", sym))
        fetch_sym, source, note = sym, "nav_computed", {}
        closes = _closes(sym) if is_public else []
        if len(closes) < 15 and proxy:        # fund code, or public symbol with no series but mapped
            fetch_sym = proxy[0]
            source = f"proxy:{proxy[0]}"
            note = {"proxy": proxy[0], "asset_class": proxy[1],
                    "caveat": "asset-class proxy — approximates the class, NOT the exact fund"}
            closes = _closes(fetch_sym)
        if len(closes) < 15:
            dead.append(sym)
            cur.execute("""INSERT INTO ticker_snapshot_daily (snapshot_date, symbol, source, data)
                           VALUES (%s,%s,'nav_computed',%s)
                           ON CONFLICT (snapshot_date, symbol) DO UPDATE SET data=EXCLUDED.data""",
                        (today, sym, json.dumps({"delisted_or_no_data": True, "checked_at": str(dt.datetime.now())})))
            continue
        t = _compute(closes)
        cur.execute("""INSERT INTO ticker_snapshot_daily
                         (snapshot_date, symbol, source, rsi, sma20_pct, sma50_pct, sma200_pct,
                          perf_week_pct, perf_month_pct, data)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (snapshot_date, symbol) DO UPDATE SET
                         rsi=EXCLUDED.rsi, sma20_pct=EXCLUDED.sma20_pct, sma50_pct=EXCLUDED.sma50_pct,
                         sma200_pct=EXCLUDED.sma200_pct, perf_week_pct=EXCLUDED.perf_week_pct,
                         perf_month_pct=EXCLUDED.perf_month_pct, source=EXCLUDED.source, data=EXCLUDED.data""",
                    (today, sym, source, t.get("rsi"), t.get("sma20_pct"), t.get("sma50_pct"), t.get("sma200_pct"),
                     t.get("perf_week_pct"), t.get("perf_month_pct"),
                     json.dumps({"computed_from": f"yfinance {fetch_sym}", "bars": len(closes), **note})))
        filled.append({sym: {**t, "via": fetch_sym if fetch_sym != sym else "direct"}})
    conn.commit()
    report = {"checked": len(universe), "was_missing": len(missing),
              "filled": filled, "no_data": dead}
    print(json.dumps(report, indent=1))
    if alert and dead:
        _alert(dead)
    return report


def _alert(dead):
    """Send via telegram_alert.send_telegram chokepoint (no raw Bot API)."""
    msg = (
        "⚠️ *TECHNICALS GAP* — no price series found for held symbols: "
        + ", ".join(dead)
        + "\n(delisted or unmapped — flagged, not faked)"
    )
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="technicals_gap_backfill",
                subject_key="ops:technicals_gap",
                retention_class="operational", severity="warning",
                sanitized_body=msg[:500], short_summary=msg[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert", action="store_true")
    ap.add_argument("--symbols")
    a = ap.parse_args()
    run(symbols=a.symbols.split(",") if a.symbols else None, alert=a.alert)
