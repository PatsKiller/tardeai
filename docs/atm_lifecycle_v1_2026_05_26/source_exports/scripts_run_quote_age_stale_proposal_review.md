# Source Export: scripts/run_quote_age_stale_proposal_review.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/run_quote_age_stale_proposal_review.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `e2b8cc349a3bac0b0e9f85e60c0cbb185238d642a2a6166f293bac4b6cb67cec` |
| **File Size** | 4737 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""run_quote_age_stale_proposal_review.py — Classify/act on proposals by quote age.

Default: dry-run. No trades. No orders. No approvals.
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
    p = argparse.ArgumentParser(description="Quote-age stale proposal review (default: dry-run)")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    if args.apply:
        args.dry_run = False

    conn = _get_conn()
    if not conn:
        print("ERROR: no DB"); sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "APPLY"
    cur = conn.cursor()
    cur.execute("""SELECT id, symbol, strategy_id, status, created_at, expires_at, last_price_checked_at
        FROM paper_trade_proposals WHERE status IN ('PENDING','pending')
        ORDER BY created_at DESC""")
    cols = [d[0] for d in cur.description]
    proposals = [dict(zip(cols, r)) for r in cur.fetchall()]

    actions = []
    for prop in proposals:
        sym = prop["symbol"]
        cur.execute("SELECT MAX(scanned_at) FROM trade_ai_scans WHERE symbol=%s", [sym])
        latest = cur.fetchone()[0]
        quote_age_h = None
        if latest:
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            quote_age_h = round((datetime.now(timezone.utc) - latest).total_seconds() / 3600, 1)

        staleness = classify_proposal_staleness(prop)

        action = "keep_pending"
        reason = "within thresholds"
        if quote_age_h and quote_age_h > 168:
            action = "expire"
            reason = f"quote {quote_age_h}h old (>168h hard expire)"
        elif quote_age_h and quote_age_h > 72:
            action = "rebuild_recommended"
            reason = f"quote {quote_age_h}h old (>72h rebuild threshold)"
        elif staleness.get("quote_status") == "never_checked":
            action = "needs_quote_refresh"
            reason = "quote never checked"
        elif staleness.get("quote_status") in ("stale", "extremely_stale"):
            action = "needs_quote_refresh"
            reason = f"quote stale ({quote_age_h}h)"

        if not args.dry_run and action == "expire":
            cur.execute("UPDATE paper_trade_proposals SET status='EXPIRED' WHERE id=%s AND status='PENDING'", [prop["id"]])

        actions.append({
            "proposal_id": prop["id"], "symbol": sym, "strategy_id": prop["strategy_id"],
            "quote_age_hours": quote_age_h, "quote_status": staleness.get("quote_status"),
            "action": action, "reason": reason, "applied": not args.dry_run and action == "expire",
        })

    if not args.dry_run:
        conn.commit()
    conn.close()

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "mode": mode,
              "total": len(actions), "actions": actions,
              "expire_count": sum(1 for a in actions if a["action"] == "expire"),
              "rebuild_count": sum(1 for a in actions if a["action"] == "rebuild_recommended"),
              "refresh_count": sum(1 for a in actions if a["action"] == "needs_quote_refresh")}

    if args.verbose:
        print(f"[{mode}] Quote-Age Stale Proposal Review")
        for a in actions:
            applied = " [APPLIED]" if a["applied"] else ""
            print(f"  #{a['proposal_id']} {a['symbol']:6s} quote={a['quote_age_hours']}h action={a['action']}{applied} — {a['reason']}")
        print(f"\nExpire: {report['expire_count']} | Rebuild: {report['rebuild_count']} | Refresh: {report['refresh_count']}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [f"# Quote-Age Stale Proposal Review ({mode})\n",
              "| # | Symbol | Quote Age | Action | Reason |", "|---|--------|-----------|--------|--------|"]
        for a in actions:
            md.append(f"| {a['proposal_id']} | {a['symbol']} | {a['quote_age_hours']}h | {a['action']} | {a['reason']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
```
