#!/usr/bin/env python3
"""report_promoter_quote_age_gate_gap.py — Find proposals promoted with stale quotes.

Read-only. No trades. No orders.
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJ / ".env")
from db_adapter import _get_conn


def main():
    p = argparse.ArgumentParser(description="Promoter quote-age gap (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = _get_conn()
    if not conn:
        print("ERROR: no DB"); sys.exit(1)

    cur = conn.cursor()
    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)
    cur.execute("""SELECT id, symbol, strategy_id, status, created_at, proposed_entry, proposed_stop
        FROM paper_trade_proposals WHERE created_at > %s ORDER BY created_at DESC""", [since])
    cols = [d[0] for d in cur.description]
    proposals = [dict(zip(cols, r)) for r in cur.fetchall()]

    results = []
    for prop in proposals:
        sym = prop["symbol"]
        cur.execute("SELECT MAX(scanned_at) FROM trade_ai_scans WHERE symbol=%s", [sym])
        latest = cur.fetchone()[0]
        quote_age_h = None
        if latest:
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            quote_age_h = round((datetime.now(timezone.utc) - latest).total_seconds() / 3600, 1)

        would_block = False
        reason = "allow"
        if quote_age_h is None:
            would_block = True
            reason = "quote_never_checked"
        elif quote_age_h > 168:
            would_block = True
            reason = f"quote_{quote_age_h:.0f}h_hard_expire"
        elif quote_age_h > 24:
            would_block = True
            reason = f"quote_{quote_age_h:.0f}h_stale"

        results.append({
            "proposal_id": prop["id"], "symbol": sym, "strategy_id": prop["strategy_id"],
            "status": prop["status"], "quote_age_hours": quote_age_h,
            "would_gate_block": would_block, "reason": reason,
        })

    conn.close()

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "total": len(results),
              "would_block": sum(1 for r in results if r["would_gate_block"]),
              "proposals": results}

    if args.verbose:
        print("Promoter Quote-Age Gate Gap")
        for r in results:
            flag = " BLOCK" if r["would_gate_block"] else ""
            print(f"  #{r['proposal_id']} {r['symbol']:6s} status={r['status']:8s} quote={r['quote_age_hours']}h{flag} — {r['reason']}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = ["# Promoter Quote-Age Gate Gap\n", "| # | Symbol | Status | Quote Age | Block | Reason |",
              "|---|--------|--------|-----------|-------|--------|"]
        for r in results:
            md.append(f"| {r['proposal_id']} | {r['symbol']} | {r['status']} | {r['quote_age_hours']}h | {r['would_gate_block']} | {r['reason']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
