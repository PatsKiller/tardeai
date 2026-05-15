#!/usr/bin/env python3
"""sweep_stale_paper_proposals.py — Find and mark stale pending paper proposals.

Dry-run by default. Does not delete proposals, create trades, or submit orders.

Usage:
    .venv/bin/python scripts/sweep_stale_paper_proposals.py --dry-run --verbose
    .venv/bin/python scripts/sweep_stale_paper_proposals.py --apply --verbose
"""
import argparse, json, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from phase6_proposal_staleness_policy import classify_proposal_staleness, TERMINAL_STATUSES


def get_conn():
    import psycopg2, psycopg2.extras
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    conn = psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""),
                            cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def main():
    p = argparse.ArgumentParser(description="Sweep stale paper proposals")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()
    run_id = f"sweep_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)

    # Load pending proposals only
    terminal_list = ",".join(f"'{s}'" for s in TERMINAL_STATUSES)
    cur.execute(f"""
        SELECT id, symbol, strategy_id, status, action_state, created_at, expires_at,
               proposal_timeframe_class, lifecycle_status
        FROM paper_trade_proposals
        WHERE status NOT IN ({terminal_list})
        ORDER BY created_at
        LIMIT %s
    """, [args.limit])
    proposals = cur.fetchall()

    results = {"run_id": run_id, "timestamp": now.isoformat(), "dry_run": args.dry_run,
               "total_checked": len(proposals), "fresh": 0, "stale": 0, "expired": 0,
               "requires_refresh": 0, "updated": 0, "errors": 0, "details": []}

    for prop in proposals:
        classification = classify_proposal_staleness(dict(prop), now)

        detail = {
            "proposal_id": prop["id"], "symbol": prop["symbol"],
            "strategy": prop["strategy_id"], "status": prop["status"],
            "classification": classification["status"],
            "reason": classification["reason"],
            "age_minutes": classification["age_minutes"],
            "threshold_minutes": classification["threshold_minutes"],
        }

        if classification["fresh"]:
            results["fresh"] += 1
            detail["action"] = "none"
        elif classification["stale"] or classification["expired"]:
            bucket = "expired" if classification["expired"] else "stale"
            results[bucket] += 1
            detail["action"] = f"mark_{bucket}" if not args.dry_run else f"would_mark_{bucket}"

            if not args.dry_run:
                try:
                    new_status = "EXPIRED" if classification["expired"] else prop["status"]
                    new_action_state = "STALE"
                    new_action_label = classification["reason"][:500]
                    cur.execute("""
                        UPDATE paper_trade_proposals
                        SET action_state = %s, action_label = %s,
                            lifecycle_status = CASE WHEN %s THEN 'EXPIRED' ELSE lifecycle_status END,
                            status = CASE WHEN %s THEN 'EXPIRED' ELSE status END,
                            updated_at = NOW()
                        WHERE id = %s AND status NOT IN ('APPROVED_FOR_PAPER_TEST','REJECTED','EXPIRED','RISK_BLOCKED')
                    """, [new_action_state, new_action_label,
                          classification["expired"], classification["expired"],
                          prop["id"]])
                    changed = cur.rowcount > 0
                    detail["changed"] = changed
                    if changed:
                        results["updated"] += 1
                except Exception as e:
                    detail["error"] = str(e)
                    results["errors"] += 1
                    conn.rollback()

            # Write audit row
            try:
                cur.execute("""
                    INSERT INTO paper_proposal_stale_sweep_audit
                        (sweep_run_id, proposal_table, proposal_id, symbol,
                         previous_status, new_status, stale_reason,
                         age_minutes, age_hours, strategy_type,
                         created_at_source, threshold_minutes,
                         dry_run, changed)
                    VALUES (%s, 'paper_trade_proposals', %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s)
                """, [run_id, prop["id"], prop["symbol"],
                      prop["status"],
                      "EXPIRED" if classification["expired"] and not args.dry_run else prop["status"],
                      classification["reason"],
                      classification["age_minutes"],
                      round(classification["age_minutes"] / 60, 1) if classification["age_minutes"] else None,
                      prop["strategy_id"],
                      prop["created_at"], classification["threshold_minutes"],
                      args.dry_run, detail.get("changed", False)])
            except Exception as e:
                detail["audit_error"] = str(e)
                conn.rollback()

        elif classification["requires_refresh"]:
            results["requires_refresh"] += 1
            detail["action"] = "requires_refresh"

        results["details"].append(detail)

    conn.commit()
    conn.close()

    if args.verbose:
        mode = "DRY RUN" if args.dry_run else "APPLY"
        print(f"Stale Sweep [{mode}] — {run_id}")
        print(f"  Checked: {results['total_checked']}")
        print(f"  Fresh: {results['fresh']}")
        print(f"  Stale: {results['stale']}")
        print(f"  Expired: {results['expired']}")
        print(f"  Requires refresh: {results['requires_refresh']}")
        print(f"  Updated: {results['updated']}")
        print(f"  Errors: {results['errors']}")
        for d in results["details"]:
            print(f"    #{d['proposal_id']} {d['symbol']} [{d['classification']}] {d['reason'][:60]}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(results, indent=2, default=str))
    if args.output_md:
        md = [f"# Stale Sweep Report — {run_id}", f"\n**Mode:** {'DRY RUN' if args.dry_run else 'APPLY'}",
              f"**Time:** {now.strftime('%Y-%m-%d %H:%M')}", "",
              "| Metric | Count |", "|--------|-------|",
              f"| Checked | {results['total_checked']} |",
              f"| Fresh | {results['fresh']} |", f"| Stale | {results['stale']} |",
              f"| Expired | {results['expired']} |",
              f"| Requires refresh | {results['requires_refresh']} |",
              f"| Updated | {results['updated']} |", f"| Errors | {results['errors']} |"]
        if results["details"]:
            md.extend(["", "## Details", "", "| ID | Symbol | Strategy | Status | Reason |",
                        "|----|--------|----------|--------|--------|"])
            for d in results["details"]:
                md.append(f"| {d['proposal_id']} | {d['symbol']} | {d['strategy']} | {d['classification']} | {d['reason'][:60]} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
