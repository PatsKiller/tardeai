#!/usr/bin/env python3
"""report_and_apply_incubator_falloff_lifecycle.py — Audit and apply incubator lifecycle.

Uses incubator_falloff_lifecycle_policy to classify candidates.
Default: dry-run. No trades. No orders. No deletions. No promotions.

Safe apply: marks source_missing, retained_by_ttl, reentered, needs_refresh.
Expire: requires --operator-approved-expire flag.
Archive: requires --operator-approved-archive flag.

Usage:
    .venv/bin/python scripts/report_and_apply_incubator_falloff_lifecycle.py --dry-run --verbose
    .venv/bin/python scripts/report_and_apply_incubator_falloff_lifecycle.py --apply --verbose
    .venv/bin/python scripts/report_and_apply_incubator_falloff_lifecycle.py --apply --operator-approved-expire --verbose
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

# States that are safe to apply without operator approval
SAFE_STATES = {"source_missing", "retained_by_ttl", "reentered", "needs_refresh", "needs_strategy_fit_recheck"}


def _q(conn, sql, params=None, fetch="all"):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    if fetch == "one":
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else {}
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def is_protected(conn, symbol):
    """Check if candidate has open trade, pending proposal, or active watchpool."""
    open_trade = _q(conn, "SELECT count(*) as c FROM paper_trades WHERE symbol=%s AND status='open'", [symbol], fetch="one")
    pending_prop = _q(conn, "SELECT count(*) as c FROM paper_trade_proposals WHERE symbol=%s AND status='pending'", [symbol], fetch="one")
    watchpool = _q(conn, "SELECT count(*) as c FROM strategy_watchpool WHERE symbol=%s AND current_status NOT IN ('expired','failed')", [symbol], fetch="one")
    reasons = []
    if int(open_trade.get("c", 0)) > 0: reasons.append("open_trade")
    if int(pending_prop.get("c", 0)) > 0: reasons.append("pending_proposal")
    if int(watchpool.get("c", 0)) > 0: reasons.append("active_watchpool")
    return reasons


def classify_lifecycle_state(action_name, mem_state_name):
    """Map falloff action to lifecycle state for DB."""
    if action_name == "keep_active":
        return "active"
    if action_name == "retain_by_ttl":
        return "source_missing"
    if action_name == "expire":
        return "expired_pending_operator_review"
    if action_name == "retain_no_data":
        return "needs_refresh"
    if mem_state_name == "active_in_sources":
        return "active"
    return "needs_refresh"


def main():
    p = argparse.ArgumentParser(description="Incubator falloff lifecycle (default: dry-run)")
    p.add_argument("--since-days", type=int, default=14)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--operator-approved-expire", action="store_true")
    p.add_argument("--operator-approved-archive", action="store_true")
    p.add_argument("--max-apply", type=int, default=10000)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    if args.apply:
        args.dry_run = False

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection"); sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "APPLY"
    cur = conn.cursor()

    # Get active incubator candidates
    cur.execute("""
        SELECT iu.symbol, iu.strategy_id, iu.status, iu.first_seen_at, iu.last_seen_at,
               iu.lifecycle_state,
               EXTRACT(DAY FROM NOW() - iu.first_seen_at)::int as days_active
        FROM incubator_universe iu
        WHERE iu.status = 'ACTIVE'
        ORDER BY iu.symbol
    """)
    cols = [d[0] for d in cur.description]
    candidates = [dict(zip(cols, r)) for r in cur.fetchall()]

    if args.verbose:
        print(f"[{mode}] Analyzing {len(candidates)} active incubator candidates")
        if args.operator_approved_expire:
            print(f"  --operator-approved-expire: ENABLED")
        if args.operator_approved_archive:
            print(f"  --operator-approved-archive: ENABLED")

    stats = {
        "candidates_analyzed": len(candidates),
        "active": 0, "source_missing": 0, "retained_by_ttl": 0,
        "expired_pending": 0, "reentered": 0, "needs_refresh": 0,
        "needs_strategy_fit_recheck": 0, "review": 0,
        "protected_open_trade": 0, "protected_pending_proposal": 0,
        "protected_watchpool": 0,
        "safe_applied": 0, "expire_applied": 0, "archive_applied": 0,
        "expire_blocked_no_flag": 0, "archive_blocked_no_flag": 0,
    }
    audit_events = []

    applied_count = 0

    for cand in candidates:
        sym = cand["symbol"]

        # Get membership records
        cur.execute("""
            SELECT symbol, screener_id, membership_status, present_this_run,
                   consecutive_missing_count, last_seen_in_screener_at
            FROM screener_symbol_membership WHERE symbol = %s
        """, [sym])
        mcols = [d[0] for d in cur.description]
        memberships = [dict(zip(mcols, r)) for r in cur.fetchall()]

        mem_state = classify_source_membership_state(cand, memberships)
        action = classify_falloff_action(cand, mem_state)
        lifecycle_state = classify_lifecycle_state(action["action"], mem_state["state"])
        protection = is_protected(conn, sym)

        # Count protections
        if "open_trade" in protection: stats["protected_open_trade"] += 1
        if "pending_proposal" in protection: stats["protected_pending_proposal"] += 1
        if "active_watchpool" in protection: stats["protected_watchpool"] += 1

        # Classify into stats
        if action["action"] == "keep_active":
            stats["active"] += 1
        elif action["action"] == "retain_by_ttl":
            stats["retained_by_ttl"] += 1
            stats["source_missing"] += 1
        elif action["action"] == "expire":
            stats["expired_pending"] += 1
        elif action["action"] == "retain_no_data":
            stats["needs_refresh"] += 1
        else:
            stats["review"] += 1

        evt = {
            "symbol": sym,
            "strategy_id": cand.get("strategy_id"),
            "days_active": cand.get("days_active"),
            "membership_state": mem_state["state"],
            "action": action["action"],
            "lifecycle_state": lifecycle_state,
            "protection": protection,
            "reason": action["reason"],
            "applied": False,
            "human_review_only": True,
        }

        # Apply logic
        if not args.dry_run and applied_count < args.max_apply:
            # Safe applies (no operator flag needed)
            if action["action"] in ("keep_active", "retain_by_ttl", "retain_no_data"):
                cur.execute("""
                    UPDATE incubator_universe SET lifecycle_state = %s
                    WHERE symbol = %s AND status = 'ACTIVE'
                """, [lifecycle_state, sym])
                stats["safe_applied"] += 1
                applied_count += 1
                evt["applied"] = True

            # Expire: requires flag + no protection
            elif action["action"] == "expire":
                if protection:
                    evt["applied"] = False
                    evt["reason"] += f" [PROTECTED: {','.join(protection)}]"
                elif args.operator_approved_expire:
                    cur.execute("""
                        UPDATE incubator_universe SET
                            lifecycle_state = 'expired_pending_operator_review',
                            status = 'EXPIRED'
                        WHERE symbol = %s AND status = 'ACTIVE'
                    """, [sym])
                    stats["expire_applied"] += 1
                    applied_count += 1
                    evt["applied"] = True
                else:
                    stats["expire_blocked_no_flag"] += 1
                    evt["reason"] += " [BLOCKED: --operator-approved-expire not set]"

        audit_events.append(evt)

        if args.verbose and action["action"] != "keep_active":
            prot_str = f" [PROTECTED: {','.join(protection)}]" if protection else ""
            applied_str = " [APPLIED]" if evt["applied"] else ""
            print(f"  {sym}: {lifecycle_state}{prot_str}{applied_str} — {action['reason'][:80]}")

    if not args.dry_run:
        conn.commit()

    conn.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else "apply",
        "operator_approved_expire": args.operator_approved_expire,
        "operator_approved_archive": args.operator_approved_archive,
        "since_days": args.since_days,
        **stats,
        "audit_events_sample": audit_events[:30],
    }

    if args.verbose:
        print(f"\n{'='*60}")
        print(f"[{mode}] Summary:")
        for k in ["candidates_analyzed", "active", "source_missing", "retained_by_ttl",
                   "expired_pending", "needs_refresh", "review",
                   "protected_open_trade", "protected_pending_proposal", "protected_watchpool",
                   "safe_applied", "expire_applied", "expire_blocked_no_flag"]:
            print(f"  {k}: {stats[k]}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [
            f"# Incubator Falloff Lifecycle {'DRY RUN' if args.dry_run else 'APPLIED'}\n",
            f"Generated: {report['generated_at']}\n",
            f"Operator expire approved: {args.operator_approved_expire}\n",
            "| Metric | Count |", "|--------|-------|",
        ]
        for k in ["candidates_analyzed", "active", "source_missing", "retained_by_ttl",
                   "expired_pending", "needs_refresh", "review",
                   "protected_open_trade", "protected_pending_proposal", "protected_watchpool",
                   "safe_applied", "expire_applied", "expire_blocked_no_flag"]:
            md.append(f"| {k} | {stats[k]} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
