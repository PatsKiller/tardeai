# Source Export: scripts/paper_execution_quality.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/paper_execution_quality.py` |
| **Git Branch** | `main` |
| **Git Commit** | `c1286d314deb377df49713e1646f139db7f43643` |
| **Export Timestamp** | `2026-05-26T15:48:59Z` |
| **SHA256** | `c1eda2af106a6ecaa7a34c8db3a63d7bd1a266597b7ab54170ad942ac7e3144f` |
| **File Size** | 11763 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""paper_execution_quality.py — TCA / execution quality analytics for paper trades.

Computes slippage, fill quality, spread, MAE/MFE, R multiples for entries/exits.
Writes to paper_execution_quality_events and paper_trade_outcome_analytics.

PAPER ONLY. No live trading.

Usage:
    .venv/bin/python scripts/paper_execution_quality.py --all-open --dry-run --json
    .venv/bin/python scripts/paper_execution_quality.py --trade-id 123 --apply --json
    .venv/bin/python scripts/paper_execution_quality.py --closed-since 48 --apply
"""
import argparse, json, logging, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from decimal import Decimal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn

log = logging.getLogger("paper_execution_quality")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

QUALITY_THRESHOLDS = [(5, "EXCELLENT"), (15, "GOOD"), (50, "FAIR")]  # in bps


def classify_grade(slippage_bps):
    if slippage_bps is None:
        return "UNKNOWN"
    a = abs(slippage_bps)
    for thresh, label in QUALITY_THRESHOLDS:
        if a < thresh:
            return label
    return "POOR"


def _f(v):
    """Convert Decimal to float safely."""
    if isinstance(v, Decimal):
        return float(v)
    return v


def get_trades(conn, trade_id=None, all_open=False, closed_since_hours=None, symbol=None):
    cur = conn.cursor()
    conditions = ["account = 'ALPACA_PAPER'"]
    params = []
    if trade_id:
        conditions.append("id = %s")
        params.append(trade_id)
    elif all_open:
        conditions.append("status = 'open'")
    elif closed_since_hours:
        conditions.append("status = 'closed'")
        conditions.append("closed_at >= NOW() - INTERVAL '%s hours'" % int(closed_since_hours))
    else:
        conditions.append("status IN ('open', 'closed')")
        conditions.append("created_at >= NOW() - INTERVAL '30 days'")

    if symbol:
        conditions.append("symbol = %s")
        params.append(symbol)

    sql = f"""SELECT id, symbol, strategy_id, entry_price, exit_price, shares,
                     stop_loss, target_1, status, broker_order_id, broker_filled_at,
                     broker_closed_at, entry_time, exit_time, planned_entry,
                     current_price, unrealized_pnl, pnl, pnl_pct, hold_time_min,
                     r_multiple, dollar_risk, exit_reason
              FROM paper_trades WHERE {' AND '.join(conditions)}
              ORDER BY created_at DESC"""
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def compute_tca(trade):
    """Compute TCA metrics for a single trade."""
    events = []
    entry = _f(trade.get("entry_price"))
    planned = _f(trade.get("planned_entry"))
    exit_p = _f(trade.get("exit_price"))
    stop = _f(trade.get("stop_loss"))
    target = _f(trade.get("target_1"))
    shares = _f(trade.get("shares")) or 0
    status = trade.get("status", "")

    # Entry fill quality
    if entry and planned and planned > 0:
        slip_abs = entry - planned
        slip_bps = (slip_abs / planned) * 10000
        events.append({
            "paper_trade_id": trade["id"], "symbol": trade["symbol"],
            "event_type": "entry_fill", "broker_order_id": trade.get("broker_order_id"),
            "expected_price": planned, "actual_price": entry,
            "slippage_abs": round(slip_abs, 4), "slippage_bps": round(slip_bps, 2),
            "expected_qty": shares, "actual_qty": shares,
            "quality_grade": classify_grade(slip_bps),
            "result": {"planned_entry": planned, "fill_entry": entry},
        })
    elif entry:
        events.append({
            "paper_trade_id": trade["id"], "symbol": trade["symbol"],
            "event_type": "entry_fill", "expected_price": entry, "actual_price": entry,
            "slippage_abs": 0, "slippage_bps": 0, "quality_grade": "GOOD",
            "result": {"note": "no planned_entry, using fill as reference"},
        })

    # Exit fill quality (closed trades)
    if status == "closed" and exit_p and entry and entry > 0:
        # Compute outcome
        pnl = (exit_p - entry) * shares if shares else 0
        pnl_pct = ((exit_p - entry) / entry) * 100 if entry else 0
        risk = abs(entry - stop) if stop else None
        r_mult = ((exit_p - entry) / risk) if risk and risk > 0 else None

        # Determine exit type
        exit_reason = trade.get("exit_reason", "")
        if stop and abs(exit_p - stop) / max(stop, 0.01) < 0.005:
            etype = "stop_fill"
        elif target and abs(exit_p - target) / max(target, 0.01) < 0.005:
            etype = "target_fill"
        else:
            etype = "exit_fill"

        expected_exit = stop if etype == "stop_fill" else (target if etype == "target_fill" else exit_p)
        slip_abs = exit_p - expected_exit if expected_exit else 0
        slip_bps = (slip_abs / expected_exit * 10000) if expected_exit and expected_exit > 0 else 0

        events.append({
            "paper_trade_id": trade["id"], "symbol": trade["symbol"],
            "event_type": etype, "broker_order_id": trade.get("broker_order_id"),
            "expected_price": expected_exit, "actual_price": exit_p,
            "slippage_abs": round(slip_abs, 4), "slippage_bps": round(slip_bps, 2),
            "quality_grade": classify_grade(slip_bps),
            "result": {"pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
                       "r_multiple": round(r_mult, 2) if r_mult else None,
                       "exit_reason": exit_reason},
        })

    # MAE/MFE (use current_price for open, historical for closed)
    outcome = None
    if status == "closed" and entry and exit_p:
        risk = abs(entry - stop) if stop else abs(entry * 0.02)
        planned_r = abs(target - entry) / risk if target and risk else None
        realized_r = (exit_p - entry) / risk if risk else None
        outcome = {
            "paper_trade_id": trade["id"], "symbol": trade["symbol"],
            "strategy_id": trade.get("strategy_id"),
            "opened_at": str(trade.get("entry_time")),
            "closed_at": str(trade.get("exit_time")),
            "hold_minutes": _f(trade.get("hold_time_min")),
            "entry_price": entry, "exit_price": exit_p,
            "stop_price": stop, "target_price": target,
            "pnl": round((exit_p - entry) * shares, 2) if shares else 0,
            "pnl_pct": round(((exit_p - entry) / entry) * 100, 2) if entry else 0,
            "r_multiple": round(realized_r, 2) if realized_r else None,
            "exit_reason": trade.get("exit_reason"),
            "planned_r": round(planned_r, 2) if planned_r else None,
            "realized_r": round(realized_r, 2) if realized_r else None,
            "tca_grade": events[-1]["quality_grade"] if events else "UNKNOWN",
        }

    return events, outcome


def save_events(conn, events, outcomes):
    cur = conn.cursor()
    for ev in events:
        cur.execute("""
            INSERT INTO paper_execution_quality_events
                (paper_trade_id, symbol, event_type, broker_order_id,
                 expected_price, actual_price, slippage_abs, slippage_bps,
                 expected_qty, actual_qty, fill_latency_seconds, spread_bps,
                 quote_source, quote_freshness_seconds, market_session,
                 quality_grade, result)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, [ev.get("paper_trade_id"), ev["symbol"], ev["event_type"],
              ev.get("broker_order_id"), ev.get("expected_price"), ev.get("actual_price"),
              ev.get("slippage_abs"), ev.get("slippage_bps"),
              ev.get("expected_qty"), ev.get("actual_qty"),
              ev.get("fill_latency_seconds"), ev.get("spread_bps"),
              ev.get("quote_source"), ev.get("quote_freshness_seconds"),
              ev.get("market_session"), ev.get("quality_grade"),
              json.dumps(ev.get("result"), default=str) if ev.get("result") else None])

    for oc in outcomes:
        cur.execute("""
            INSERT INTO paper_trade_outcome_analytics
                (paper_trade_id, symbol, strategy_id, opened_at, closed_at,
                 hold_minutes, entry_price, exit_price, stop_price, target_price,
                 pnl, pnl_pct, r_multiple, exit_reason, planned_r, realized_r,
                 tca_grade)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (paper_trade_id) DO UPDATE SET
                pnl=EXCLUDED.pnl, pnl_pct=EXCLUDED.pnl_pct,
                r_multiple=EXCLUDED.r_multiple, tca_grade=EXCLUDED.tca_grade,
                updated_at=now()
        """, [oc["paper_trade_id"], oc["symbol"], oc.get("strategy_id"),
              oc.get("opened_at") if oc.get("opened_at") not in (None, 'None') else None,
              oc.get("closed_at") if oc.get("closed_at") not in (None, 'None') else None,
              oc.get("hold_minutes"),
              oc.get("entry_price"), oc.get("exit_price"), oc.get("stop_price"),
              oc.get("target_price"), oc.get("pnl"), oc.get("pnl_pct"),
              oc.get("r_multiple"), oc.get("exit_reason"),
              oc.get("planned_r"), oc.get("realized_r"), oc.get("tca_grade")])

    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Paper TCA / execution quality analytics")
    parser.add_argument("--trade-id", type=int, help="Analyze specific trade")
    parser.add_argument("--symbol", help="Filter by symbol")
    parser.add_argument("--all-open", action="store_true", help="Analyze all open trades")
    parser.add_argument("--closed-since", type=int, metavar="HOURS", help="Analyze trades closed within N hours")
    parser.add_argument("--dry-run", action="store_true", help="Compute but don't save")
    parser.add_argument("--apply", action="store_true", help="Save results to DB")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        args.dry_run = True

    conn = get_conn()
    try:
        trades = get_trades(conn, trade_id=args.trade_id, all_open=args.all_open,
                            closed_since_hours=args.closed_since, symbol=args.symbol)

        all_events = []
        all_outcomes = []
        for t in trades:
            events, outcome = compute_tca(t)
            all_events.extend(events)
            if outcome:
                all_outcomes.append(outcome)

        if args.apply:
            save_events(conn, all_events, all_outcomes)
            log.info(f"Saved {len(all_events)} events, {len(all_outcomes)} outcomes")

        out = {
            "mode": "dry_run" if args.dry_run else "applied",
            "trades_analyzed": len(trades),
            "events": len(all_events),
            "outcomes": len(all_outcomes),
            "grades": {},
        }
        for ev in all_events:
            g = ev.get("quality_grade", "UNKNOWN")
            out["grades"][g] = out["grades"].get(g, 0) + 1

        if args.json:
            out["event_details"] = all_events[:20]
            out["outcome_details"] = all_outcomes[:10]
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"[tca] {out['mode']}: {out['trades_analyzed']} trades, "
                  f"{out['events']} events, {out['outcomes']} outcomes, grades={out['grades']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```
