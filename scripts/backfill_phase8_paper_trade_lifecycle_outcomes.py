#!/usr/bin/env python3
"""backfill_phase8_paper_trade_lifecycle_outcomes.py — Populate outcome records from paper_trades.

Reads paper_trades + paper_trade_proposals. Writes ONLY to paper_trade_lifecycle_outcomes.
Does NOT mutate source tables, create trades, or submit orders.

Usage:
    .venv/bin/python scripts/backfill_phase8_paper_trade_lifecycle_outcomes.py --dry-run --verbose
    .venv/bin/python scripts/backfill_phase8_paper_trade_lifecycle_outcomes.py --apply --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent


def get_conn():
    import psycopg2, psycopg2.extras
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""),
                            cursor_factory=psycopg2.extras.RealDictCursor)


def determine_outcome_label(trade: dict) -> str:
    status = trade.get("status", "")
    exit_reason = (trade.get("exit_reason") or "").lower()
    pnl = float(trade.get("pnl") or 0)

    if status == "open":
        return "open"
    if status == "cancelled":
        return "cancelled"
    if "target" in exit_reason:
        return "target_hit"
    if "stop" in exit_reason:
        return "stopped"
    if pnl > 1:
        return "win"
    if pnl < -1:
        return "loss"
    return "breakeven"


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT t.*, p.id as prop_id
        FROM paper_trades t
        LEFT JOIN paper_trade_proposals p ON p.paper_trade_id = t.id
        WHERE t.created_at > NOW() - INTERVAL '%s days'
        ORDER BY t.id
        LIMIT %s
    """, [args.since_days, args.limit])
    trades = cur.fetchall()

    inserted, skipped, errors = 0, 0, 0
    results = []

    for t in trades:
        # Check if already exists
        cur.execute("SELECT id FROM paper_trade_lifecycle_outcomes WHERE paper_trade_id = %s", [t["id"]])
        if cur.fetchone():
            skipped += 1
            continue

        label = determine_outcome_label(t)
        pnl = float(t.get("pnl") or 0)
        entry = float(t.get("entry_price") or 0)
        stop = float(t.get("stop_loss") or 0)
        risk = abs(entry - stop) * float(t.get("shares") or 0) if entry and stop else None
        r_mult = float(t.get("r_multiple") or 0)
        holding_min = None
        if t.get("filled_at") and t.get("closed_at"):
            holding_min = int((t["closed_at"] - t["filled_at"]).total_seconds() / 60)

        confidence = "high" if (t.get("closed_at") and entry > 0 and stop > 0) else "medium" if t.get("pnl") is not None else "low"

        row = {
            "paper_trade_id": t["id"],
            "proposal_id": t.get("proposal_id") or (t.get("prop_id")),
            "symbol": t["symbol"],
            "strategy_name": t.get("strategy_id"),
            "entry_price": entry or None,
            "stop_price": stop or None,
            "target_price": float(t.get("target_1") or 0) or None,
            "fill_price": entry or None,
            "close_price": None,
            "quantity": t.get("shares"),
            "opened_at": t.get("created_at"),
            "filled_at": t.get("filled_at"),
            "closed_at": t.get("closed_at"),
            "holding_minutes": holding_min,
            "status": t.get("status", "unknown"),
            "close_reason": t.get("exit_reason"),
            "outcome_label": label,
            "pnl": pnl if pnl != 0 else None,
            "r_multiple": r_mult if r_mult != 0 else None,
            "planned_risk_amount": risk,
            "confidence": confidence,
            "outcome_source": "backfill_phase8b",
        }
        results.append(row)

        if not args.dry_run:
            try:
                cur.execute("""
                    INSERT INTO paper_trade_lifecycle_outcomes
                        (paper_trade_id, proposal_id, symbol, strategy_name, entry_price, stop_price,
                         target_price, fill_price, quantity, opened_at, filled_at, closed_at,
                         holding_minutes, status, close_reason, outcome_label, pnl, r_multiple,
                         planned_risk_amount, confidence, outcome_source)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, [row["paper_trade_id"], row["proposal_id"], row["symbol"], row["strategy_name"],
                      row["entry_price"], row["stop_price"], row["target_price"], row["fill_price"],
                      row["quantity"], row["opened_at"], row["filled_at"], row["closed_at"],
                      row["holding_minutes"], row["status"], row["close_reason"], row["outcome_label"],
                      row["pnl"], row["r_multiple"], row["planned_risk_amount"], row["confidence"],
                      row["outcome_source"]])
                inserted += 1
            except Exception as e:
                errors += 1
                if args.verbose:
                    print(f"  ERROR trade #{t['id']}: {e}")
                conn.rollback()
        else:
            inserted += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    summary = {"mode": "dry-run" if args.dry_run else "apply",
               "trades_seen": len(trades), "inserted": inserted, "skipped": skipped, "errors": errors}

    if args.verbose:
        mode = "DRY RUN" if args.dry_run else "APPLY"
        print(f"Phase 8B Outcome Backfill [{mode}]")
        print(f"  Trades seen: {len(trades)}, Inserted: {inserted}, Skipped: {skipped}, Errors: {errors}")
        for r in results[:5]:
            print(f"  #{r['paper_trade_id']} {r['symbol']} [{r['outcome_label']}] pnl={r['pnl']} R={r['r_multiple']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps({"summary": summary, "results": results}, indent=2, default=str))
    if args.output_md:
        md = [f"# Phase 8B Outcome Backfill — {mode}", "",
              f"Trades: {len(trades)} | Inserted: {inserted} | Skipped: {skipped}", "",
              "| Trade | Symbol | Label | PnL | R |", "|-------|--------|-------|-----|---|"]
        for r in results:
            md.append(f"| {r['paper_trade_id']} | {r['symbol']} | {r['outcome_label']} | {r['pnl']} | {r['r_multiple']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
