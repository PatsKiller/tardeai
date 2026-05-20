#!/usr/bin/env python3
"""report_quote_age_stale_sweeper_gap.py — Compare proposal-age vs quote-age staleness.

Read-only. No trades. No orders.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJ / ".env")

from db_adapter import _get_conn
from phase6_proposal_staleness_policy import classify_proposal_staleness


def main():
    p = argparse.ArgumentParser(description="Quote-age stale sweeper gap (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = _get_conn()
    if not conn:
        print("ERROR: no DB"); sys.exit(1)

    cur = conn.cursor()
    cur.execute("""SELECT id, symbol, strategy_id, status, created_at, expires_at,
        last_price_checked_at, proposed_entry, proposed_stop
        FROM paper_trade_proposals WHERE status IN ('PENDING','pending','APPROVED','approved')
        ORDER BY created_at DESC""")
    cols = [d[0] for d in cur.description]
    proposals = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Get quote ages from trade_ai_scans
    results = []
    for prop in proposals:
        sym = prop["symbol"]
        cur.execute("SELECT MAX(scanned_at) FROM trade_ai_scans WHERE symbol=%s", [sym])
        latest_scan = cur.fetchone()[0]
        quote_age_h = None
        if latest_scan:
            if latest_scan.tzinfo is None:
                from datetime import timezone as tz
                latest_scan = latest_scan.replace(tzinfo=tz.utc)
            quote_age_h = round((datetime.now(timezone.utc) - latest_scan).total_seconds() / 3600, 1)

        staleness = classify_proposal_staleness(prop)

        # Determine recommendation
        rec = "keep_pending"
        if quote_age_h and quote_age_h > 168:
            rec = "expire"
        elif quote_age_h and quote_age_h > 72:
            rec = "rebuild"
        elif staleness.get("quote_status") == "never_checked":
            rec = "refresh_quote"
        elif staleness.get("quote_status") in ("stale", "extremely_stale"):
            rec = "refresh_quote"
        elif staleness.get("fresh"):
            rec = "keep_pending"

        mismatch = staleness.get("fresh", False) and quote_age_h and quote_age_h > 24

        results.append({
            "proposal_id": prop["id"],
            "symbol": sym,
            "strategy_id": prop["strategy_id"],
            "proposal_age_hours": round(staleness.get("age_minutes", 0) / 60, 1),
            "quote_age_hours": quote_age_h,
            "proposal_staleness": staleness["status"],
            "quote_status": staleness.get("quote_status", "unknown"),
            "mismatch": mismatch,
            "recommendation": rec,
        })

    conn.close()

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "proposals": results,
              "mismatches": sum(1 for r in results if r["mismatch"])}

    if args.verbose:
        print("Quote-Age Stale Sweeper Gap Report")
        for r in results:
            mm = " MISMATCH" if r["mismatch"] else ""
            print(f"  #{r['proposal_id']} {r['symbol']:6s} proposal={r['proposal_staleness']:8s} quote={r['quote_status']:15s} quote_age={r['quote_age_hours']}h rec={r['recommendation']}{mm}")
        print(f"\nMismatches: {report['mismatches']}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = ["# Quote-Age Stale Sweeper Gap\n", "| # | Symbol | Proposal | Quote | Quote Age | Rec |",
              "|---|--------|----------|-------|-----------|-----|"]
        for r in results:
            md.append(f"| {r['proposal_id']} | {r['symbol']} | {r['proposal_staleness']} | {r['quote_status']} | {r['quote_age_hours']}h | {r['recommendation']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
