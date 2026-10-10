#!/usr/bin/env python3
"""backtest_results_aggregator.py — Aggregate per-trade data into per-run summaries.

Computes win_rate, total_pnl, profit_factor, equity curve, max drawdown.
Run after every backtest to populate strategy_backtest_results.

--dry-run computes the same summaries on a READ ONLY session and returns before any INSERT
(AGENTS.md §6). A real run writes data/runtime/backtest-results-aggregator_last.json. The log line
now separates runs aggregated from runs skipped for having no trades (those stay "pending" forever,
which is what "aggregated 647 runs" every morning was counting).
"""
import json, logging, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [aggregator] %(message)s")
log = logging.getLogger(__name__)


def aggregate_all(dry_run=False):
    from db_adapter import _get_conn
    import psycopg2.extras
    conn = _get_conn()
    if dry_run:
        from lib.lane_last_receipt import enforce_readonly
        enforce_readonly(conn)  # the server refuses any write (AGENTS.md §6)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Find runs with trades but no aggregated result
    cur.execute("""SELECT DISTINCT r.run_id, r.strategy_id, r.run_type
        FROM strategy_backtest_runs r
        WHERE r.status = 'completed'
        AND NOT EXISTS (SELECT 1 FROM strategy_backtest_results res WHERE res.run_id = r.run_id)""")
    pending = [dict(r) for r in cur.fetchall()]
    log.info(f"Aggregating {len(pending)} runs" + (" (dry run)" if dry_run else ""))
    aggregated = skipped_no_trades = 0

    for run in pending:
        run_id = run["run_id"]
        cur.execute("""SELECT pnl, pnl_pct, r_multiple, signal_time::date as entry_date, exit_reason
            FROM strategy_backtest_trades WHERE run_id = %s ORDER BY signal_time""", [run_id])
        trades = [dict(r) for r in cur.fetchall()]

        if not trades:
            skipped_no_trades += 1
            continue

        pnls = [float(t.get("pnl") or 0) for t in trades]
        r_mults = [float(t["r_multiple"]) for t in trades if t.get("r_multiple") is not None]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p <= 0)
        n = len(pnls)
        win_rate = round(wins / n * 100, 2) if n else 0
        total_pnl = round(sum(pnls), 4)
        avg_pnl = round(total_pnl / n, 4) if n else 0
        gp = sum(p for p in pnls if p > 0)
        gl = abs(sum(p for p in pnls if p < 0))
        pf = round(gp / gl, 4) if gl > 0 else None
        avg_r = round(sum(r_mults) / len(r_mults), 4) if r_mults else None

        # Equity curve
        cum = 0.0
        curve = []
        for t in trades:
            cum += float(t.get("pnl") or 0)
            curve.append({"date": str(t.get("entry_date", "")), "value": round(cum, 4)})

        # Max drawdown
        peak = 0.0
        max_dd = 0.0
        for pt in curve:
            v = pt["value"]
            if v > peak:
                peak = v
            dd = (peak - v) / abs(peak) * 100 if peak != 0 else 0
            max_dd = max(max_dd, dd)

        if dry_run:
            aggregated += 1
            log.info(f"  [dry-run] would insert {run_id}: {n} trades, {win_rate}% WR, ${total_pnl:.2f} PnL")
            continue
        cur2 = conn.cursor()
        cur2.execute("""INSERT INTO strategy_backtest_results
            (run_id, strategy_id, run_type, total_trades, wins, losses, win_rate,
             total_pnl, avg_pnl, profit_factor, avg_r_multiple, max_drawdown_pct,
             equity_curve_json, sample_size, expectancy_r, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())""",
            [run_id, run["strategy_id"], run["run_type"],
             n, wins, losses, win_rate, total_pnl, avg_pnl, pf, avg_r,
             round(max_dd, 2), json.dumps(curve), n, avg_r])
        conn.commit()
        aggregated += 1
        log.info(f"  {run_id}: {n} trades, {win_rate}% WR, ${total_pnl:.2f} PnL")

    conn.close()
    log.info(f"Done — aggregated {len(pending)} runs "
             f"({'would insert' if dry_run else 'inserted'} {aggregated}, "
             f"skipped {skipped_no_trades} with no trades)")
    return {"pending": len(pending), "aggregated": aggregated, "skipped_no_trades": skipped_no_trades}


def main(argv=None):
    import argparse
    from datetime import datetime, timezone

    ap = argparse.ArgumentParser(description="Aggregate backtest runs into strategy_backtest_results")
    ap.add_argument("--dry-run", action="store_true", help="compute only; no INSERT, no receipt")
    args = ap.parse_args(argv)
    if args.dry_run:
        aggregate_all(dry_run=True)
        return 0
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        summary = aggregate_all()
    except Exception as exc:  # failed real run: failed receipt (ok_at kept), then exit non-zero
        _receipt(ok=False, started_at=started_at, error=f"{type(exc).__name__}: {exc}")
        raise
    _receipt(ok=True, started_at=started_at, summary=summary)
    return 0


def _receipt(**kw):
    """Real-run receipt (data/runtime/backtest-results-aggregator_last.json, ok_at on success only)."""
    from lib.lane_last_receipt import write_lane_receipt

    kw.setdefault("exit_code", 0 if kw.get("ok") else 1)
    write_lane_receipt("backtest-results-aggregator", script="backtest_results_aggregator.py", **kw)


if __name__ == "__main__":
    sys.exit(main())
