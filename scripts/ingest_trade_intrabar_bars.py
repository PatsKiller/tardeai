#!/usr/bin/env python3
"""Phase 206c — Ingest the actual intrabar OHLC path for closed measurable trades.

Read-only market data (yfinance). Persists the ordered bar path (entry->exit) per trade into
trade_intrabar_bars so the profit-protection rule backtest can REPLAY candidate stops/trails/locks
against the real path and price premature-exit cost honestly.

Safety: no broker writes, no order/stop/strategy/GO-WAIT mutation. Writes ONLY trade_intrabar_bars
and trade_intrabar_ingest_log, and ONLY with --apply. Never fabricates bars — when the fetch is
empty or out of range, status is recorded honestly and no path is written. Bounded (no retry loops).

Usage:
  python3 scripts/ingest_trade_intrabar_bars.py            # dry-run (fetch + report, no write)
  python3 scripts/ingest_trade_intrabar_bars.py --apply    # persist paths
  python3 scripts/ingest_trade_intrabar_bars.py --all-closed  # widen beyond measurable winners
"""
import os, sys, json, argparse, time, logging
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Silence yfinance's own "possibly delisted / Failed download" chatter: a failed 1m fetch for a long
# window is EXPECTED (we fall back to 5m) and is not an error worth logging.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

INTERVAL = "5m"          # 60-day lookback; default; sufficient to detect intra-hold pullbacks
FINE_INTERVAL = "1m"     # ~7-day lookback; tighter premature-exit detection for recent trades
FINE_DAYS = 30           # yfinance 1m lookback (~30d via date-range); attempt 1m within this window
FETCH_PAD_MIN = 10       # pad the window slightly so the entry/exit bars are included
SLEEP_BETWEEN = 0.4      # gentle pacing between symbol fetches


def load_env():
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ.get("DB_PORT", "5432"),
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def fetch_bars(symbol, start, end, interval=INTERVAL):
    """Fetch OHLC bars in [start,end] (UTC) at the given interval via yfinance. list or {error}."""
    try:
        import yfinance as yf
        import pandas as pd  # noqa
        s = (start - timedelta(minutes=FETCH_PAD_MIN))
        e = (end + timedelta(minutes=FETCH_PAD_MIN))
        df = yf.download(symbol, start=s.strftime("%Y-%m-%d"),
                         end=(e + timedelta(days=1)).strftime("%Y-%m-%d"),
                         interval=interval, progress=False, auto_adjust=False)
        if df is None or len(df) == 0:
            return []
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = [c[0] for c in df.columns]
        out = []
        for ts, row in df.iterrows():
            t = ts.to_pydatetime()
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            t = t.astimezone(timezone.utc)
            if not (start <= t <= end):
                continue
            try:
                out.append({"bar_time": t, "open": float(row["Open"]), "high": float(row["High"]),
                            "low": float(row["Low"]), "close": float(row["Close"]),
                            "volume": float(row["Volume"]) if row["Volume"] == row["Volume"] else 0.0})
            except (KeyError, ValueError, TypeError):
                continue
        out.sort(key=lambda b: b["bar_time"])
        return out
    except Exception as e:
        return {"error": str(e)[:200]}


def fetch_best(symbol, start, end, fine, fine_days):
    """Pick the finest interval that FULLY covers the window. Tries 1m for recent windows and only
    accepts it if its earliest bar reaches the entry (so we never trade full 5m coverage for a
    partial 1m one). Falls back to 5m. Returns (bars, interval) or ({error}, interval)."""
    now = datetime.now(timezone.utc)
    fine_eligible = fine and (now - end) <= timedelta(days=fine_days)
    if fine_eligible:
        b1 = fetch_bars(symbol, start, end, FINE_INTERVAL)
        # Accept 1m ONLY if it fetched cleanly AND covers the window start. yfinance caps 1m at 8
        # days per request, so long windows error or come back partial — in every such case we fall
        # through to 5m (which has a 60-day window) rather than dropping the trade's path.
        if isinstance(b1, list) and b1 and b1[0]["bar_time"] <= start + timedelta(minutes=FETCH_PAD_MIN):
            return b1, FINE_INTERVAL
    return fetch_bars(symbol, start, end, INTERVAL), INTERVAL


def sane_bars(bars, entry=None):
    """Drop corrupt OHLC before storing (2026-06-29). yfinance occasionally returns split-glitch /
    wrong-symbol bars — e.g. an entire ~$6 series for an NVDA $218 trade — which poisons the replay what-if.
    Reference = the TRADE ENTRY when known (catches whole-series scale mismatches), else the median close.
    Keep bars within 0.3x..3x of the reference with high>=low>0 and open/close in [low,high]."""
    import statistics
    closes = [float(b["close"]) for b in bars if b.get("close") not in (None, 0)]
    if not closes:
        return []
    try:
        ref = float(entry) if (entry and float(entry) > 0) else statistics.median(closes)
    except Exception:
        ref = statistics.median(closes)
    lo, hi = 0.3 * ref, 3.0 * ref
    out = []
    for b in bars:
        try:
            o, h, l, c = float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])
        except Exception:
            continue
        if l <= 0 or h < l or not (lo <= l and h <= hi) or not (l <= o <= h and l <= c <= h):
            continue
        out.append(b)
    return out


def run(apply, all_closed, fine=False, fine_days=FINE_DAYS):
    load_env()
    import psycopg2.extras
    conn = db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    where = "c.measurable" if all_closed else "c.measurable AND c.winner"
    cur.execute(f"""
        SELECT c.trade_instance_id, c.symbol, c.entry_time, c.exit_time, ti.side, c.winner, ti.entry_price
        FROM trade_profit_capture_analysis c JOIN trade_instances ti ON ti.id = c.trade_instance_id
        WHERE {where} AND c.entry_time IS NOT NULL AND c.exit_time IS NOT NULL
        ORDER BY c.entry_time
    """)
    trades = [dict(r) for r in cur.fetchall()]

    results = []
    counts = {"ok": 0, "no_bars": 0, "fetch_error": 0, "not_long": 0, "total": len(trades),
              "total_bars": 0, "by_interval": {}}
    wc = conn.cursor()

    def log_status(rec):
        if not apply:
            return
        wc.execute("""INSERT INTO trade_intrabar_ingest_log
            (trade_instance_id,symbol,window_start,window_end,timeframe,bars_ingested,status,note,ingested_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now())
            ON CONFLICT (trade_instance_id) DO UPDATE SET
              window_start=excluded.window_start, window_end=excluded.window_end,
              timeframe=excluded.timeframe, bars_ingested=excluded.bars_ingested,
              status=excluded.status, note=excluded.note, ingested_at=now()""",
            (rec["trade_instance_id"], rec["symbol"], rec["window_start"], rec["window_end"],
             rec["timeframe"], rec["bars_ingested"], rec["status"], rec["note"]))
        conn.commit()

    for t in trades:
        tid = t["trade_instance_id"]; sym = t["symbol"]
        start = t["entry_time"].astimezone(timezone.utc)
        end = t["exit_time"].astimezone(timezone.utc)
        rec = {"trade_instance_id": tid, "symbol": sym, "window_start": start, "window_end": end,
               "timeframe": INTERVAL, "bars_ingested": 0, "status": None, "note": None}

        if (t["side"] or "long").lower() != "long":
            rec["status"] = "not_long"; rec["note"] = "pricer supports long only"
            counts["not_long"] += 1; results.append(rec); log_status(rec)
            continue

        bars, used_interval = fetch_best(sym, start, end, fine, fine_days)
        rec["timeframe"] = used_interval
        if isinstance(bars, dict) and bars.get("error"):
            rec["status"] = "fetch_error"; rec["note"] = bars["error"]
            counts["fetch_error"] += 1; results.append(rec); log_status(rec)
            time.sleep(SLEEP_BETWEEN); continue
        if not bars:
            rec["status"] = "no_bars"; rec["note"] = "yfinance returned no bars in window"
            counts["no_bars"] += 1; results.append(rec); log_status(rec)
            time.sleep(SLEEP_BETWEEN); continue

        _n0 = len(bars); bars = sane_bars(bars, t.get("entry_price")); _drop = _n0 - len(bars)   # drop corrupt OHLC
        if _drop:
            rec["bars_dropped_corrupt"] = _drop
            counts["bars_dropped_corrupt"] = counts.get("bars_dropped_corrupt", 0) + _drop
        if not bars:
            rec["status"] = "no_bars"; rec["note"] = f"all {_n0} bars failed OHLC sanity (corrupt)"
            counts["no_bars"] += 1; results.append(rec); log_status(rec)
            time.sleep(SLEEP_BETWEEN); continue

        rec["bars_ingested"] = len(bars); rec["status"] = "ok"
        counts["ok"] += 1; counts["total_bars"] += len(bars)
        counts["by_interval"][used_interval] = counts["by_interval"].get(used_interval, 0) + 1
        results.append(rec)

        if apply:
            wc.execute("DELETE FROM trade_intrabar_bars WHERE trade_instance_id=%s", (tid,))
            for seq, b in enumerate(bars):
                wc.execute("""INSERT INTO trade_intrabar_bars
                    (trade_instance_id,symbol,bar_seq,bar_time,open,high,low,close,volume,timeframe,source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'yfinance')""",
                    (tid, sym, seq, b["bar_time"], b["open"], b["high"], b["low"], b["close"], b["volume"], used_interval))
            log_status(rec)
        time.sleep(SLEEP_BETWEEN)

    conn.close()
    report = {"run_at": datetime.now(timezone.utc).isoformat(), "applied": apply,
              "scope": ("measurable" if all_closed else "measurable_winners"),
              "default_interval": INTERVAL, "fine": fine, "fine_interval": FINE_INTERVAL,
              "fine_days": fine_days, "counts": counts,
              "coverage_pct": round(100 * counts["ok"] / counts["total"], 1) if counts["total"] else 0.0,
              "results": results}
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--all-closed", action="store_true", help="ingest all measurable (not just winners)")
    ap.add_argument("--fine", action="store_true",
                    help="use 1m bars for trades within --fine-days when they fully cover the window")
    ap.add_argument("--fine-days", type=int, default=FINE_DAYS)
    a = ap.parse_args()
    run(a.apply, a.all_closed, a.fine, a.fine_days)
