# Source Export: scripts/paper_outcome_analytics.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/paper_outcome_analytics.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `594f421c736260c9d92a5b574fdb3246890ff26caa44d4c97b76c05c42c8bc05` |
| **File Size** | 8685 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""paper_outcome_analytics.py — Paper trade outcome analytics and strategy performance.

Builds paper_trade_outcome_analytics for closed trades. Aggregates win rate,
profit factor, expectancy, R multiples by strategy/setup/signal grade.

PAPER ONLY. No live trading.

Usage:
    .venv/bin/python scripts/paper_outcome_analytics.py --rebuild --dry-run --json
    .venv/bin/python scripts/paper_outcome_analytics.py --since 30 --apply --json
"""
import argparse, json, logging, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from decimal import Decimal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn

log = logging.getLogger("paper_outcome_analytics")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def get_closed_trades(conn, since_days=None):
    cur = conn.cursor()
    sql = """SELECT id, symbol, strategy_id, entry_price, exit_price, shares,
                    stop_loss, target_1, pnl, pnl_pct, hold_time_min,
                    r_multiple, exit_reason, entry_time, exit_time, dollar_risk,
                    opened_via, setup_type, signal_grade
             FROM paper_trades WHERE status='closed'"""
    params = []
    if since_days:
        sql += " AND closed_at >= NOW() - INTERVAL '%s days'" % int(since_days)
    sql += " ORDER BY exit_time DESC"
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def build_outcomes(trades):
    outcomes = []
    for t in trades:
        entry = _f(t.get("entry_price")) or 0
        exit_p = _f(t.get("exit_price")) or 0
        stop = _f(t.get("stop_loss"))
        target = _f(t.get("target_1"))
        shares = _f(t.get("shares")) or 0
        risk = abs(entry - stop) if stop and entry else abs(entry * 0.02) if entry else 1

        pnl = _f(t.get("pnl")) or ((exit_p - entry) * shares)
        pnl_pct = _f(t.get("pnl_pct")) or ((exit_p - entry) / entry * 100 if entry else 0)
        r_mult = _f(t.get("r_multiple")) or ((exit_p - entry) / risk if risk else None)
        planned_r = abs(target - entry) / risk if target and risk else None

        outcomes.append({
            "paper_trade_id": t["id"], "symbol": t["symbol"],
            "strategy_id": t.get("strategy_id"),
            "opened_at": t.get("entry_time"),
            "closed_at": t.get("exit_time"),
            "hold_minutes": _f(t.get("hold_time_min")),
            "entry_price": entry, "exit_price": exit_p,
            "stop_price": float(stop) if stop else None,
            "target_price": float(target) if target else None,
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
            "r_multiple": round(r_mult, 2) if r_mult else None,
            "exit_reason": t.get("exit_reason"),
            "planned_r": round(planned_r, 2) if planned_r else None,
            "realized_r": round(r_mult, 2) if r_mult else None,
            "followed_plan": _check_followed_plan(t, exit_p, stop, target),
            "tca_grade": None,
            "outcome_verdict": "win" if pnl > 0 else ("loss" if pnl < 0 else "breakeven"),
        })
    return outcomes


def _check_followed_plan(trade, exit_p, stop, target):
    exit_reason = (trade.get("exit_reason") or "").lower()
    if "stop" in exit_reason and stop:
        return abs(exit_p - float(stop)) / max(float(stop), 0.01) < 0.02
    if "target" in exit_reason and target:
        return abs(exit_p - float(target)) / max(float(target), 0.01) < 0.02
    return None


def compute_aggregates(outcomes):
    if not outcomes:
        return {"sample_size": 0, "low_sample_warning": True}

    wins = [o for o in outcomes if o["pnl"] > 0]
    losses = [o for o in outcomes if o["pnl"] < 0]
    gross_profit = sum(o["pnl"] for o in wins)
    gross_loss = abs(sum(o["pnl"] for o in losses))

    r_values = [o["r_multiple"] for o in outcomes if o["r_multiple"] is not None]

    agg = {
        "sample_size": len(outcomes),
        "low_sample_warning": len(outcomes) < 30,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(outcomes), 3) if outcomes else 0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
        "total_pnl": round(sum(o["pnl"] for o in outcomes), 2),
        "avg_pnl": round(sum(o["pnl"] for o in outcomes) / len(outcomes), 2),
        "avg_r": round(sum(r_values) / len(r_values), 2) if r_values else None,
        "median_r": round(sorted(r_values)[len(r_values) // 2], 2) if r_values else None,
        "avg_hold_min": round(sum(_f(o.get("hold_minutes") or 0) for o in outcomes) / len(outcomes), 1),
        "stop_hit_rate": round(sum(1 for o in outcomes if "stop" in (o.get("exit_reason") or "").lower()) / len(outcomes), 3),
        "target_hit_rate": round(sum(1 for o in outcomes if "target" in (o.get("exit_reason") or "").lower()) / len(outcomes), 3),
        "manual_close_rate": round(sum(1 for o in outcomes if "manual" in (o.get("exit_reason") or "").lower()) / len(outcomes), 3),
    }

    # By strategy
    by_strategy = {}
    for o in outcomes:
        sid = o.get("strategy_id") or "unknown"
        by_strategy.setdefault(sid, []).append(o)
    agg["by_strategy"] = {}
    for sid, group in by_strategy.items():
        w = [o for o in group if o["pnl"] > 0]
        agg["by_strategy"][sid] = {
            "count": len(group), "wins": len(w),
            "win_rate": round(len(w) / len(group), 3) if group else 0,
            "total_pnl": round(sum(o["pnl"] for o in group), 2),
        }

    return agg


def save_outcomes(conn, outcomes):
    cur = conn.cursor()
    for o in outcomes:
        cur.execute("""
            INSERT INTO paper_trade_outcome_analytics
                (paper_trade_id, symbol, strategy_id, opened_at, closed_at,
                 hold_minutes, entry_price, exit_price, stop_price, target_price,
                 pnl, pnl_pct, r_multiple, exit_reason, planned_r, realized_r,
                 followed_plan, tca_grade, outcome_verdict)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (paper_trade_id) DO UPDATE SET
                pnl=EXCLUDED.pnl, pnl_pct=EXCLUDED.pnl_pct,
                r_multiple=EXCLUDED.r_multiple, outcome_verdict=EXCLUDED.outcome_verdict,
                updated_at=now()
        """, [o["paper_trade_id"], o["symbol"], o.get("strategy_id"),
              o.get("opened_at"), o.get("closed_at"), o.get("hold_minutes"),
              o.get("entry_price"), o.get("exit_price"), o.get("stop_price"),
              o.get("target_price"), o.get("pnl"), o.get("pnl_pct"),
              o.get("r_multiple"), o.get("exit_reason"),
              o.get("planned_r"), o.get("realized_r"),
              o.get("followed_plan"), o.get("tca_grade"), o.get("outcome_verdict")])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Paper trade outcome analytics")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild all closed trade analytics")
    parser.add_argument("--since", type=int, metavar="DAYS", help="Only trades closed within N days")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        args.dry_run = True

    conn = get_conn()
    try:
        trades = get_closed_trades(conn, since_days=args.since if not args.rebuild else None)
        outcomes = build_outcomes(trades)
        aggregates = compute_aggregates(outcomes)

        if args.apply:
            save_outcomes(conn, outcomes)
            log.info(f"Saved {len(outcomes)} outcome records")

        out = {
            "mode": "dry_run" if args.dry_run else "applied",
            "closed_trades": len(trades),
            "outcomes_built": len(outcomes),
            "aggregates": aggregates,
        }
        if args.json:
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"[analytics] {out['mode']}: {out['closed_trades']} trades, "
                  f"WR={aggregates.get('win_rate', 0)}, PF={aggregates.get('profit_factor')}, "
                  f"{'LOW SAMPLE' if aggregates.get('low_sample_warning') else 'ok'}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```
