#!/usr/bin/env python3
"""backfill_ticker_prices.py — Backfill ticker_prices for watchlist, Hermes, and active proposals.

Watchlist cards, agent synthesis, and paper/broker proposals read close history from ticker_prices.
The daily repricer only syncs held symbols; watch-grade and proposal symbols often have live
market_quotes but zero DB history, which leaves support/resistance/stop/target empty.

Steps:
  1. Sync daily closes from market_quotes (last quote per symbol per day)
  2. yfinance 1y history for symbols still short on rows (< min_rows)
  3. Optional: materialize watchlist_strategy_cards + requeue agent jobs

  python3 scripts/backfill_ticker_prices.py --hermes-top 250 --apply
  python3 scripts/backfill_ticker_prices.py --rated --apply --materialize --requeue-agents
  python3 scripts/backfill_ticker_prices.py --proposals --apply
  python3 scripts/backfill_ticker_prices.py --symbols FATN,BDSX --apply
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))


def _resolve_symbols(args) -> list[str]:
    from db_adapter import _get_conn
    from watchlist_priority import DAILY_PRIORITY_RATED_RECS

    if args.symbols:
        return list(dict.fromkeys(s.strip().upper() for s in args.symbols.split(",") if s.strip()))

    if args.proposals:
        from price_db_sync import active_proposal_symbols
        return active_proposal_symbols()

    conn = _get_conn()
    cur = conn.cursor()
    if args.hermes_top:
        cur.execute(
            """SELECT DISTINCT symbol FROM watchlist_items
               WHERE status IN ('active','researched')
                 AND hermes_rank IS NOT NULL AND hermes_rank <= %s
                 AND symbol ~ '^[A-Z]{1,5}$'
               ORDER BY symbol""",
            (int(args.hermes_top),),
        )
    elif args.rated:
        rated = sorted(r.upper() for r in DAILY_PRIORITY_RATED_RECS)
        cur.execute(
            """SELECT DISTINCT wi.symbol
               FROM watchlist_items wi
               WHERE wi.status IN ('active','researched')
                 AND wi.symbol ~ '^[A-Z]{1,5}$'
                 AND (
                   EXISTS (SELECT 1 FROM watchlist_research_cards rc
                           WHERE rc.symbol = wi.symbol
                             AND UPPER(REPLACE(REPLACE(rc.latest_recommendation,' ','_'),'-','_')) = ANY(%s))
                   OR EXISTS (SELECT 1 FROM watchlist_final_synthesis fs
                               WHERE upper(fs.symbol)=upper(wi.symbol)
                                 AND UPPER(REPLACE(REPLACE(fs.recommendation,' ','_'),'-','_')) = ANY(%s))
                 )
               ORDER BY wi.symbol""",
            (rated, rated),
        )
    elif args.needs_iteration:
        cur.execute(
            """SELECT DISTINCT wi.symbol FROM watchlist_items wi
               JOIN watchlist_strategy_cards sc ON sc.symbol = wi.symbol
               WHERE wi.status IN ('active','researched')
                 AND (sc.needs_iteration IS TRUE OR sc.stop_loss IS NULL OR sc.latest_price IS NULL)
               ORDER BY wi.symbol"""
        )
    else:
        cur.execute(
            """SELECT DISTINCT symbol FROM watchlist_items
               WHERE status IN ('active','researched') AND symbol ~ '^[A-Z]{1,5}$'
               ORDER BY symbol"""
        )
    syms = [r[0] for r in cur.fetchall()]
    conn.close()
    return syms


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill ticker_prices for watchlist symbols")
    ap.add_argument("--symbols", help="Comma-separated tickers")
    ap.add_argument("--hermes-top", type=int, help="Hermes rank <= N (e.g. 250)")
    ap.add_argument("--rated", action="store_true", help="All CIO-rated watchlist symbols")
    ap.add_argument("--needs-iteration", action="store_true", help="Strategy cards flagged needs_iteration")
    ap.add_argument("--proposals", action="store_true", help="All active paper/broker proposal symbols")
    ap.add_argument("--min-rows", type=int, default=60, help="Min daily rows before skipping yfinance")
    ap.add_argument("--apply", action="store_true", help="Write to DB (default dry-run)")
    ap.add_argument("--materialize", action="store_true", help="Run materialize_watchlist_strategy_cards.py")
    ap.add_argument("--requeue-agents", action="store_true", help="Requeue watchlist agent jobs for scope")
    ap.add_argument("--yfinance-sleep", type=float, default=0.25, help="Pause between yfinance fetches")
    args = ap.parse_args()

    if not any([args.symbols, args.hermes_top, args.rated, args.needs_iteration, args.proposals]):
        args.hermes_top = 250

    symbols = _resolve_symbols(args)
    if not symbols:
        print(json.dumps({"ok": True, "symbols": 0, "note": "no symbols matched scope"}))
        return 0

    from price_db_sync import backfill_yfinance_history, count_price_rows, ensure_price_history

    report: dict = {"scope_symbols": len(symbols), "dry_run": not args.apply}

    if args.apply:
        _ph = ensure_price_history(symbols, min_rows=args.min_rows)
        report["quotes_synced"] = _ph.get("quotes_synced", 0)
        report["yfinance_candidates"] = _ph.get("short_candidates", 0)
        report["yfinance"] = _ph.get("yfinance", {})
    else:
        short_preview = []
        for s in symbols[:500]:
            n = count_price_rows(s)
            if n < args.min_rows:
                short_preview.append({"symbol": s, "rows": n})
        report["would_yfinance"] = len(short_preview)
        report["sample_short"] = short_preview[:15]

    print(json.dumps(report, indent=2))

    if not args.apply:
        print("DRY-RUN — pass --apply to write")
        return 0

    if args.materialize:
        py = sys.executable
        for i in range(0, len(symbols), 40):
            batch = ",".join(symbols[i:i + 40])
            subprocess.run(
                [py, str(PROJECT_ROOT / "scripts" / "materialize_watchlist_strategy_cards.py"),
                 "--symbols", *symbols[i:i + 40]],
                cwd=str(PROJECT_ROOT), timeout=600, check=False,
            )
        report["materialized"] = len(symbols)

    if args.requeue_agents:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        for sym in symbols:
            cur.execute(
                """UPDATE watchlist_agent_jobs
                   SET status='queued', priority=-3, started_at=NULL
                   WHERE symbol=%s AND status IN ('pending','queued','processing','completed')""",
                (sym,),
            )
        conn.commit()
        conn.close()
        subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "process_watchlist_agent_jobs.py"),
             "--limit", str(min(50, len(symbols)))],
            cwd=str(PROJECT_ROOT), timeout=1200, check=False,
        )
        report["requeued_agents"] = len(symbols)

    print(json.dumps({"done": True, **report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())