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
import os, sys, json, argparse, time
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INTERVAL = "5m"          # 60-day lookback; sufficient to detect intra-hold pullbacks
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


def fetch_bars(symbol, start, end):
    """Fetch 5m OHLC bars in [start,end] (UTC) via yfinance. Returns list of dicts or []."""
    try:
        import yfinance as yf
        import pandas as pd  # noqa
        s = (start - timedelta(minutes=FETCH_PAD_MIN))
        e = (end + timedelta(minutes=FETCH_PAD_MIN))
        df = yf.download(symbol, start=s.strftime("%Y-%m-%d"),
                         end=(e + timedelta(days=1)).strftime("%Y-%m-%d"),
                         interval=INTERVAL, progress=False, auto_adjust=False)
        if df is None or len(df) == 0:
            return []
        # flatten possible multiindex columns
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


def run(apply, all_closed):
    load_env()
    import psycopg2.extras
    conn = db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    where = "c.measurable" if all_closed else "c.measurable AND c.winner"
    cur.execute(f"""
        SELECT c.trade_instance_id, c.symbol, c.entry_time, c.exit_time, ti.side, c.winner
        FROM trade_profit_capture_analysis c JOIN trade_instances ti ON ti.id = c.trade_instance_id
        WHERE {where} AND c.entry_time IS NOT NULL AND c.exit_time IS NOT NULL
        ORDER BY c.entry_time
    """)
    trades = [dict(r) for r in cur.fetchall()]

    results = []
    counts = {"ok": 0, "no_bars": 0, "fetch_error": 0, "not_long": 0, "total": len(trades),
              "total_bars": 0}
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

        bars = fetch_bars(sym, start, end)
        if isinstance(bars, dict) and bars.get("error"):
            rec["status"] = "fetch_error"; rec["note"] = bars["error"]
            counts["fetch_error"] += 1; results.append(rec); log_status(rec)
            time.sleep(SLEEP_BETWEEN); continue
        if not bars:
            rec["status"] = "no_bars"; rec["note"] = "yfinance returned no bars in window"
            counts["no_bars"] += 1; results.append(rec); log_status(rec)
            time.sleep(SLEEP_BETWEEN); continue

        rec["bars_ingested"] = len(bars); rec["status"] = "ok"
        counts["ok"] += 1; counts["total_bars"] += len(bars)
        results.append(rec)

        if apply:
            wc.execute("DELETE FROM trade_intrabar_bars WHERE trade_instance_id=%s", (tid,))
            for seq, b in enumerate(bars):
                wc.execute("""INSERT INTO trade_intrabar_bars
                    (trade_instance_id,symbol,bar_seq,bar_time,open,high,low,close,volume,timeframe,source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'yfinance')""",
                    (tid, sym, seq, b["bar_time"], b["open"], b["high"], b["low"], b["close"], b["volume"], INTERVAL))
            log_status(rec)
        time.sleep(SLEEP_BETWEEN)

    conn.close()
    report = {"run_at": datetime.now(timezone.utc).isoformat(), "applied": apply,
              "scope": ("measurable" if all_closed else "measurable_winners"),
              "interval": INTERVAL, "counts": counts,
              "coverage_pct": round(100 * counts["ok"] / counts["total"], 1) if counts["total"] else 0.0,
              "results": results}
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--all-closed", action="store_true", help="ingest all measurable (not just winners)")
    a = ap.parse_args()
    run(a.apply, a.all_closed)
