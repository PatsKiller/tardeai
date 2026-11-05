#!/usr/bin/env python3
"""Daily bars for the Market Risk Engine's reference ETFs (config/market_reference_symbols.json).

Why (2026-10-31, builder H's audit, PR #2341): ``market_ohlcv_bars`` daily rows exist only as a side effect of an
on-demand technical lookup (``technical_intelligence.load_bars`` fetches when a page or the shadow decision service
asks for a symbol). Nothing refreshes a symbol nobody opens, so SPY's daily bars stopped on 2026-10-09 and QQQ and
SMH never had any. The engine's technical, volatility and correlation categories need 200+ sessions of closes.

This lane refreshes exactly the reference list, through the existing writer path
(``market_data_snapshot_loader.fetch_yfinance_bars`` + ``store_bars``: source ``yfinance``, upsert on
(symbol, timeframe, bar_time)). Default is a dry run that fetches and prints and writes nothing.

    python3 scripts/market_reference_bars_refresh.py                          # dry run, incremental
    python3 scripts/market_reference_bars_refresh.py --backfill-sessions 400  # dry run, 400-session backfill
    python3 scripts/market_reference_bars_refresh.py --apply [--backfill-sessions 400]

``--apply`` writes bars and the lane receipt ``data/runtime/market-reference-bars_last.json`` (LaneRunReceipt@v2).
Exit 0 = every symbol has bars through the fetch window; 1 = at least one symbol fetched nothing (named); 2 = usage.
Public market data only. No broker, no sender, no model. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

LANE_ID = "market-reference-bars"
SYMBOLS_PATH = ROOT / "config" / "market_reference_symbols.json"
INCREMENTAL_MIN_DAYS = 10  # covers a long weekend plus a holiday on the incremental path
DEFAULT_BACKFILL_SESSIONS = 400  # the engine's longest lookback (200-DMA, 1-year z-scores) plus margin


def reference_symbols(path: Path = SYMBOLS_PATH) -> list[str]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema") != "MarketReferenceSymbols@v1":
        raise ValueError(f"{path}: schema {doc.get('schema')!r}")
    return [str(s).strip().upper() for s in doc.get("symbols") or [] if str(s).strip()]


def fetch_days(last_bar: date | None, today: date, backfill_sessions: int | None) -> int:
    """Calendar days to request. A backfill converts sessions to calendar days (about 252 NYSE sessions per 365
    days, plus slack); incremental asks from the last stored bar, never fewer than INCREMENTAL_MIN_DAYS. A symbol
    with no bars at all gets the default backfill."""
    sessions = backfill_sessions or (DEFAULT_BACKFILL_SESSIONS if last_bar is None else None)
    if sessions:
        return math.ceil(sessions * 365 / 252) + 10
    return max(INCREMENTAL_MIN_DAYS, (today - last_bar).days + 3)


def last_daily_bars(cur, symbols: list[str]) -> dict[str, date]:
    cur.execute(
        "SELECT symbol, max(bar_time)::date FROM market_ohlcv_bars WHERE timeframe='daily' AND symbol = ANY(%s) "
        "GROUP BY symbol",
        (symbols,),
    )
    return {str(s): d for s, d in cur.fetchall()}


def run(*, apply: bool, backfill_sessions: int | None, conn, fetch, store, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    symbols = reference_symbols()
    cur = conn.cursor()
    last = last_daily_bars(cur, symbols)
    rows, empty, stored_total, fetched_total = [], [], 0, 0
    for sym in symbols:
        days = fetch_days(last.get(sym), today, backfill_sessions)
        bars = fetch(sym, "daily", days) or []
        fetched_total += len(bars)
        stored = store(conn, bars) if (apply and bars) else 0
        stored_total += stored
        if not bars:
            empty.append(sym)
        times = sorted(b["bar_time"] for b in bars)
        rows.append(
            {
                "symbol": sym,
                "last_stored": last.get(sym).isoformat() if last.get(sym) else None,
                "requested_days": days,
                "fetched": len(bars),
                "first": times[0].date().isoformat() if times else None,
                "last": times[-1].date().isoformat() if times else None,
                "stored": stored,
            }
        )
    return {
        "schema": "MarketReferenceBarsRun@v1",
        "lane_id": LANE_ID,
        "mode": "apply" if apply else "dry_run",
        "symbols": len(symbols),
        "fetched_bars": fetched_total,
        "stored_bars": stored_total,
        "empty": empty,
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write bars and the lane receipt")
    ap.add_argument("--dry-run", action="store_true", help="default; overrides --apply")
    ap.add_argument("--backfill-sessions", type=int, default=None, help="fetch this many sessions of history")
    a = ap.parse_args(argv)
    if a.backfill_sessions is not None and not (1 <= a.backfill_sessions <= 2000):
        print("--backfill-sessions must be 1..2000", file=sys.stderr)
        return 2
    apply = a.apply and not a.dry_run
    started = datetime.now(timezone.utc)

    import market_data_snapshot_loader as mdl  # existing writer path (fetch_yfinance_bars, store_bars)

    conn = mdl.get_conn()
    if not apply:
        conn.set_session(readonly=True)
    try:
        out = run(
            apply=apply,
            backfill_sessions=a.backfill_sessions,
            conn=conn,
            fetch=mdl.fetch_yfinance_bars,
            store=mdl.store_bars,
        )
    finally:
        conn.close()
    for r in out["rows"]:
        print(
            f"[ref-bars] {r['symbol']:<5} stored-through {r['last_stored'] or '—':<10} "
            f"req {r['requested_days']:>3}d fetched {r['fetched']:>3} ({r['first'] or '—'}..{r['last'] or '—'}) "
            f"{'stored ' + str(r['stored']) if apply else 'not written (dry run)'}"
        )
    print(
        f"[ref-bars] {out['mode']}: {out['symbols']} symbols, {out['fetched_bars']} bars fetched, "
        f"{out['stored_bars']} stored; empty: {', '.join(out['empty']) or 'none'}"
    )
    rc = 1 if out["empty"] else 0
    if apply:
        from lib.lane_last_receipt import write_lane_receipt

        write_lane_receipt(
            LANE_ID,
            ok=rc == 0,
            exit_code=rc,
            started_at=started,
            script="scripts/market_reference_bars_refresh.py",
            summary={k: out[k] for k in ("symbols", "fetched_bars", "stored_bars", "empty")},
            error=f"no bars for {', '.join(out['empty'])}" if out["empty"] else None,
            produced_count=out["stored_bars"],
            attempted_count=out["symbols"],
            empty_reason="provider returned no bars" if out["empty"] else None,
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
