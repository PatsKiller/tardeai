#!/usr/bin/env python3
"""report_and_apply_incubator_falloff_lifecycle.py — Audit incubator candidates against membership lifecycle.

Uses incubator_falloff_lifecycle_policy to classify candidates.
Default: dry-run. No trades. No orders. No deletions. No promotions.

Usage:
    .venv/bin/python scripts/report_and_apply_incubator_falloff_lifecycle.py --dry-run --verbose
    .venv/bin/python scripts/report_and_apply_incubator_falloff_lifecycle.py --apply --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from incubator_falloff_lifecycle_policy import (
    classify_source_membership_state,
    classify_falloff_action,
    build_falloff_audit_event,
)


def main():
    p = argparse.ArgumentParser(description="Incubator falloff lifecycle (default: dry-run)")
    p.add_argument("--since-days", type=int, default=14)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    if args.apply:
        args.dry_run = False

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection")
        sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "APPLY"
    cur = conn.cursor()

    # Get active incubator candidates
    cur.execute("""
        SELECT iu.symbol, iu.strategy_id, iu.status, iu.first_seen_at, iu.last_seen_at,
               EXTRACT(DAY FROM NOW() - iu.first_seen_at)::int as days_active
        FROM incubator_universe iu
        WHERE iu.status = 'ACTIVE'
        ORDER BY iu.symbol
    """)
    cols = [d[0] for d in cur.description]
    candidates = [dict(zip(cols, r)) for r in cur.fetchall()]

    if args.verbose:
        print(f"[{mode}] Analyzing {len(candidates)} active incubator candidates")

    stats = {
        "candidates_analyzed": len(candidates),
        "keep_active": 0,
        "retain_by_ttl": 0,
        "expire": 0,
        "retain_no_data": 0,
        "review": 0,
        "source_missing_candidates": 0,
    }
    audit_events = []

    for cand in candidates:
        sym = cand["symbol"]

        # Get membership records for this symbol
        cur.execute("""
            SELECT symbol, screener_id, membership_status, present_this_run,
                   consecutive_missing_count, last_seen_in_screener_at
            FROM screener_symbol_membership
            WHERE symbol = %s
        """, [sym])
        mcols = [d[0] for d in cur.description]
        memberships = [dict(zip(mcols, r)) for r in cur.fetchall()]

        mem_state = classify_source_membership_state(cand, memberships)
        action = classify_falloff_action(cand, mem_state)
        event = build_falloff_audit_event(cand, action)

        stats[action["action"]] = stats.get(action["action"], 0) + 1
        if mem_state["state"] in ("dropped_from_all", "stale_all_sources", "no_membership_data"):
            stats["source_missing_candidates"] += 1

        audit_events.append({
            "symbol": sym,
            "strategy_id": cand.get("strategy_id"),
            "days_active": cand.get("days_active"),
            "membership_state": mem_state["state"],
            "present_count": mem_state["present_count"],
            "dropped_count": mem_state["dropped_count"],
            "action": action["action"],
            "reason": action["reason"],
        })

        if args.verbose and action["action"] != "keep_active":
            print(f"  {sym}: {action['action']} — {action['reason']}")

    # Apply: update incubator lifecycle_state if not dry-run
    applied_updates = 0
    if not args.dry_run:
        for evt in audit_events:
            if evt["action"] == "expire":
                cur.execute("""
                    UPDATE incubator_universe SET
                        lifecycle_state = 'expired',
                        status = 'EXPIRED'
                    WHERE symbol = %s AND status = 'ACTIVE'
                """, [evt["symbol"]])
                applied_updates += cur.rowcount
        conn.commit()

    conn.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else "apply",
        "since_days": args.since_days,
        **stats,
        "applied_updates": applied_updates if not args.dry_run else 0,
        "audit_events_sample": audit_events[:20],
    }

    if args.verbose:
        print(f"\n{'='*60}")
        print(f"[{mode}] Summary:")
        print(f"  Candidates: {stats['candidates_analyzed']}")
        print(f"  Keep active: {stats['keep_active']}")
        print(f"  Retain by TTL: {stats['retain_by_ttl']}")
        print(f"  Expire: {stats['expire']}")
        print(f"  Retain no data: {stats['retain_no_data']}")
        print(f"  Review: {stats['review']}")
        print(f"  Source-missing: {stats['source_missing_candidates']}")
        if not args.dry_run:
            print(f"  Applied updates: {applied_updates}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [
            f"# Incubator Falloff Lifecycle {'DRY RUN' if args.dry_run else 'APPLIED'}\n",
            f"Generated: {report['generated_at']}\n",
            "| Metric | Count |",
            "|--------|-------|",
            f"| Candidates analyzed | {stats['candidates_analyzed']} |",
            f"| Keep active | {stats['keep_active']} |",
            f"| Retain by TTL | {stats['retain_by_ttl']} |",
            f"| Expire | {stats['expire']} |",
            f"| Retain no data | {stats['retain_no_data']} |",
            f"| Review | {stats['review']} |",
            f"| Source-missing | {stats['source_missing_candidates']} |",
        ]
        if not args.dry_run:
            md.append(f"| Applied updates | {applied_updates} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
