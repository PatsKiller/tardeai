#!/usr/bin/env python3
"""backtest_fill_reconciliation.py — reconcile REAL broker fills against the backtest data backbone.

Credibility check the backtesting stack was missing: do the bars the simulator/replay run on actually
contain the prices real money transacted at? For recent Schwab round trips:
  1. entry/exit fills must fall within that day's [low, high] from the SAME bar source the sim uses
     (Alpaca daily -> Schwab fallback) — catches bad bars, splits, bad symbol mapping;
  2. recomputed P&L from fills must match the recorded round-trip P&L within tolerance (default 5%)
     — catches basis/fee drift between the journal and raw fills.

Read-only. Exit non-zero if reconciliation fails (CI-able).

  .venv/bin/python scripts/backtest_fill_reconciliation.py [--limit 20] [--tolerance 0.05]
"""
import argparse
import json
import sys
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def run(limit=20, tolerance=0.05):
    from db_adapter import _get_conn
    from strategy_signal_simulator import _daily_bars
    cur = _get_conn().cursor()
    cur.execute("""SELECT symbol, entry_time::date, exit_time::date, entry_price, exit_price,
                          qty, net_pnl
                   FROM schwab_round_trips
                   WHERE entry_price > 0 AND exit_price > 0 AND qty > 0 AND basis_status IS NULL
                   ORDER BY exit_time DESC LIMIT %s""", (limit,))
    rows = cur.fetchall()
    results, fails = [], 0
    for sym, ed, xd, ep, xp, sh, pnl in rows:
        ep, xp, sh = float(ep), float(xp), float(sh)
        rec = {"symbol": sym, "entry_date": str(ed), "exit_date": str(xd)}
        start = (ed - dt.timedelta(days=5)).isoformat()
        end = (xd + dt.timedelta(days=2)).isoformat()
        bars = _daily_bars(sym, start, end)
        bmap = {b["d"]: b for b in bars}
        eb, xb = bmap.get(str(ed)), bmap.get(str(xd))
        # 1) fills inside the day's range (0.5% slack for SIP vs venue prints)
        def _inside(b, px):
            return b and (b["l"] * 0.995 <= px <= b["h"] * 1.005)
        rec["entry_in_bar"] = _inside(eb, ep)
        rec["exit_in_bar"] = _inside(xb, xp)
        # 2) recomputed P&L vs recorded
        calc = (xp - ep) * sh
        denom = max(abs(float(pnl or 0)), abs(calc), 1e-9)
        rec["pnl_recorded"] = float(pnl or 0)
        rec["pnl_from_fills"] = round(calc, 2)
        rec["pnl_dev"] = round(abs(calc - float(pnl or 0)) / denom, 4)
        rec["pnl_ok"] = rec["pnl_dev"] <= tolerance
        rec["bars_found"] = bool(eb and xb)
        ok = rec["bars_found"] and rec["entry_in_bar"] and rec["exit_in_bar"] and rec["pnl_ok"]
        rec["ok"] = ok
        if not ok:
            fails += 1
        results.append(rec)
    n = len(results)
    summary = {"checked": n, "passed": n - fails, "failed": fails,
               "pass_rate": round((n - fails) / n, 3) if n else None,
               "tolerance": tolerance,
               "verdict": ("RECONCILED" if n and fails / n <= 0.1 else
                           "DEVIATIONS" if n else "no_data"),
               "failures": [r for r in results if not r["ok"]][:8]}
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["verdict"] == "RECONCILED" else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--tolerance", type=float, default=0.05)
    a = ap.parse_args()
    raise SystemExit(run(a.limit, a.tolerance))
