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
import os
import argparse
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
SNAP = Path(os.environ.get("TRADEAI_STATE_ROOT") or ROOT) / "data" / "runtime" / "market_movers_latest.json"
LANE_ID = "finviz-market-movers"
_LAST_COUNTS = {}


def _cookie() -> str:
    # Selected logical name only; never copy a secret render into the process environment.
    from finviz_auth import finviz_secret
    return finviz_secret("FINVIZ_COOKIE")

def _get_csv(url: str, headers: dict) -> str:
    _fv_acquire()
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            _fv_cooldown()
        raise


def _fetch_signal(sig_param: str, cookie: str, token: str = "") -> list[dict]:
    """Cookie export first; on an empty or failed cookie export, the Elite API token."""
    from finviz_auth import with_auth_token
    # losers/new-low sort MOST NEGATIVE first (o=change asc); everything else biggest first
    order = "change" if sig_param in ("ta_toplosers", "ta_newlow") else "-change"
    url = f"https://elite.finviz.com/export.ashx?v=111&s={sig_param}&o={order}"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://elite.finviz.com/screener.ashx"}
    rows: list[dict] = []
    if cookie:
        try:
            rows = _parse_rows(_get_csv(url, {**headers, "Cookie": cookie}))
        except urllib.error.HTTPError as e:
            if e.code == 429 or not token:
                raise
    if not rows and token:
        token_url = with_auth_token(f"https://elite.finviz.com/export?v=111&s={sig_param}&o={order}", token)
        rows = _parse_rows(_get_csv(token_url, headers))
    return rows


def _parse_rows(content: str) -> list[dict]:
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


def _execute() -> int:
    from db_adapter import _get_conn
    from finviz_auth import finviz_secret, redact
    cookie = _cookie()
    token = finviz_secret("FINVIZ_API_TOKEN")
    if not cookie and not token:
        print("[movers] FATAL: no FINVIZ_COOKIE or FINVIZ_API_TOKEN")
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
            rows = _fetch_signal(param, cookie, token)
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
            msg = redact(e, cookie, token)[:120]
            snap["errors"][key] = f"{type(e).__name__}: {msg}"
            print(f"[movers] {key} FAILED: {msg}")
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
    _LAST_COUNTS.update(signals=ok, rows=sum(len(s["rows"]) for s in snap["signals"].values()),
                        errors=len(snap["errors"]))
    return 0 if ok else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Finviz signal board ingestion", allow_abbrev=False)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run:
        print(f"DRY-RUN {LANE_ID}: would fetch {len(SIGNALS)} Finviz screens, upsert market_movers, "
              "apply existing retention and write market_movers_latest.json; no auth, DB, network or writes")
        return 0
    from scripts.lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    _LAST_COUNTS.clear()
    try:
        rc = _execute()
    except Exception as exc:
        write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                           script="finviz_market_movers.py", error=type(exc).__name__)
        raise
    write_lane_receipt(LANE_ID, ok=rc == 0, exit_code=rc, started_at=started,
                       script="finviz_market_movers.py", summary=_LAST_COUNTS)
    return rc


if __name__ == "__main__":
    sys.exit(main())
