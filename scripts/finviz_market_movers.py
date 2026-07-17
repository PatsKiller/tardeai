#!/usr/bin/env python3
"""finviz_market_movers.py — Home v2 WS-A: the Finviz signal board ingestion.

Pulls the standard signal screens through the PROVEN Elite export path
(screener.ashx→/export CSV + Elite cookie, finviz_screener_runner pattern), one
throttled GET per signal via the GLOBAL finviz_throttle. Top ~15 rows per signal
into market_movers + a <50KB latest snapshot (data/runtime/market_movers_latest.json)
that /api/v2/market-movers serves with an ETag (Engine Room pattern).

Advisory/visibility only — never trades, never proposes. Cadence: cron ~12 min RTH.
"""
import csv
import io
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from finviz_throttle import acquire as _fv_acquire, cooldown as _fv_cooldown
except ImportError:
    def _fv_acquire(*a, **k): return 0.0
    def _fv_cooldown(*a, **k): pass

# signal key -> (finviz s= param, label). Every one is a standard screener signal on the
# SAME export endpoint — no scraping beyond authenticated exports (session contract).
SIGNALS = [
    ("top_gainers",    "ta_topgainers",    "Top Gainers"),
    ("top_losers",     "ta_toplosers",     "Top Losers"),
    ("new_high",       "ta_newhigh",       "New High"),
    ("new_low",        "ta_newlow",        "New Low"),
    ("unusual_volume", "ta_unusualvolume", "Unusual Volume"),
    ("most_volatile",  "ta_mostvolatile",  "Most Volatile"),
    ("most_active",    "ta_mostactive",    "Most Active"),
    ("earnings_before","n_earningsbefore", "Earnings Before"),
    ("earnings_after", "n_earningsafter",  "Earnings After"),
    ("insider_buying", "it_latestbuys",    "Insider Buying"),
]
TOP_N = 15
SNAP = ROOT / "data" / "runtime" / "market_movers_latest.json"


def _cookie() -> str:
    import os
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("FINVIZ_COOKIE="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return os.environ.get("FINVIZ_COOKIE", "").strip().strip('"\'')


def _fetch_signal(sig_param: str, cookie: str) -> list[dict]:
    url = f"https://elite.finviz.com/export.ashx?v=111&s={sig_param}&o=-change"
    _fv_acquire()
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Cookie": cookie,
        "Referer": "https://elite.finviz.com/screener.ashx"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            content = r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            _fv_cooldown()
        raise
    rows = []
    rd = csv.DictReader(io.StringIO(content))
    for rec in rd:
        t = (rec.get("Ticker") or "").strip()
        if not re.match(r"^[A-Z.\-]{1,6}$", t):
            continue
        try:
            chg = float(str(rec.get("Change", "")).replace("%", "") or 0)
        except ValueError:
            chg = None
        try:
            vol = int(str(rec.get("Volume", "")).replace(",", "") or 0)
        except ValueError:
            vol = None
        try:
            last = float(rec.get("Price") or 0) or None
        except ValueError:
            last = None
        rows.append({"symbol": t, "company": (rec.get("Company") or "")[:60],
                     "sector": rec.get("Sector") or None, "last": last,
                     "change_pct": chg, "volume": vol})
        if len(rows) >= TOP_N:
            break
    return rows


def main() -> int:
    from db_adapter import _get_conn
    cookie = _cookie()
    if not cookie:
        print("[movers] FATAL: no FINVIZ_COOKIE")
        return 1
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS market_movers (
        id BIGSERIAL PRIMARY KEY, signal TEXT NOT NULL, symbol TEXT NOT NULL,
        company TEXT, sector TEXT, last NUMERIC, change_pct NUMERIC, volume BIGINT,
        captured_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    cur.execute("CREATE INDEX IF NOT EXISTS market_movers_cap_idx ON market_movers (captured_at DESC, signal)")
    conn.commit()

    captured_at = datetime.now(timezone.utc).isoformat()
    snap = {"captured_at": captured_at, "signals": {}, "errors": {}}
    for key, param, label in SIGNALS:
        try:
            rows = _fetch_signal(param, cookie)
            snap["signals"][key] = {"label": label, "rows": rows}
            for r in rows:
                cur.execute(
                    """INSERT INTO market_movers (signal, symbol, company, sector, last, change_pct, volume, captured_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (key, r["symbol"], r["company"], r["sector"], r["last"], r["change_pct"], r["volume"], captured_at))
            conn.commit()
            print(f"[movers] {key}: {len(rows)} rows")
        except Exception as e:
            conn.rollback()
            # flag-back contract: a signal the export can't serve is REPORTED, never synthesized
            snap["errors"][key] = f"{type(e).__name__}: {str(e)[:120]}"
            print(f"[movers] {key} FAILED: {str(e)[:120]}")
    # retention: keep 7 days of captures
    try:
        cur.execute("DELETE FROM market_movers WHERE captured_at < now() - interval '7 days'")
        conn.commit()
    except Exception:
        conn.rollback()
    SNAP.parent.mkdir(parents=True, exist_ok=True)
    tmp = SNAP.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, default=str))
    tmp.replace(SNAP)
    ok = len(snap["signals"])
    print(f"[movers] snapshot: {ok}/{len(SIGNALS)} signals, {SNAP.stat().st_size//1024}KB")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
