#!/usr/bin/env python3
"""report_missed_opportunity_audit.py — Audit proposals for missed opportunities.

Read-only. No approvals. No trades. No orders.

Usage:
    .venv/bin/python scripts/report_missed_opportunity_audit.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn: return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "one":
            row = cur.fetchone()
            return dict(zip([d[0] for d in cur.description], row)) if row else None
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def _load_alert_log():
    """Load file-based alert log."""
    log_path = PROJ / "logs" / "proposal_alerts.log"
    alerts = {}
    if log_path.exists():
        for line in log_path.read_text().splitlines():
            try:
                entry = json.loads(line)
                pid = entry.get("proposal_id")
                if pid and pid not in alerts:
                    alerts[pid] = entry
            except Exception:
                pass
    return alerts


def main():
    p = argparse.ArgumentParser(description="Missed opportunity audit (read-only)")
    p.add_argument("--since-days", type=int, default=7)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)
    from missed_opportunity_policy import classify_missed_opportunity, calculate_alert_latency

    proposals = _db_query("""
        SELECT ptp.id, ptp.symbol, ptp.strategy_id, ptp.status,
               ptp.proposed_entry, ptp.proposed_stop, ptp.proposed_target1,
               ptp.proposed_rr, ptp.created_at,
               per.readiness_state, per.quote_price, per.spread_pct,
               per.created_at as check_at
        FROM paper_trade_proposals ptp
        LEFT JOIN LATERAL (
            SELECT * FROM proposal_execution_readiness
            WHERE proposal_id = ptp.id ORDER BY created_at DESC LIMIT 1
        ) per ON true
        WHERE ptp.created_at > %s
        ORDER BY ptp.created_at DESC
    """, [since]) or []

    alert_log = _load_alert_log()
    results = []
    rebuild_count = 0
    missed_count = 0
    sla_breaches = 0

    for pr in proposals:
        alert = alert_log.get(pr.get("id"))
        quote = {"quote_price": pr.get("quote_price"), "spread_pct": pr.get("spread_pct")}
        pr["check_execution_at"] = pr.get("check_at")

        mo = classify_missed_opportunity(pr, quote)
        al = calculate_alert_latency(pr, alert)

        if "rebuild" in mo["status"]: rebuild_count += 1
        if "missed" in mo["status"]: missed_count += 1
        if al.get("alert_sent") and not al.get("sla_met"): sla_breaches += 1

        results.append({
            "proposal_id": pr["id"], "symbol": pr["symbol"],
            "strategy_id": pr["strategy_id"], "status": pr["status"],
            "missed_status": mo["status"], "timing": mo["timing"],
            "price_move_pct": mo["decay"]["price_move_pct"],
            "original_rr": mo["decay"]["original_rr"],
            "current_rr": mo["decay"]["current_rr"],
            "alert_sent": al["alert_sent"],
            "alert_latency": al.get("latency_seconds"),
            "sla_met": al.get("sla_met"),
            "human_review_only": True,
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "proposals_reviewed": len(results),
        "rebuild_required": rebuild_count,
        "missed_opportunities": missed_count,
        "sla_breaches": sla_breaches,
        "alerts_sent": len([r for r in results if r["alert_sent"]]),
        "alerts_missing": len([r for r in results if not r["alert_sent"]]),
        "results": results[:50],
    }

    if args.verbose:
        print(f"Missed Opportunity Audit — {len(results)} proposals")
        print(f"  Rebuild required: {rebuild_count}")
        print(f"  Missed: {missed_count}")
        print(f"  SLA breaches: {sla_breaches}")
        print(f"  Alerts sent: {report['alerts_sent']}, missing: {report['alerts_missing']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Missed Opportunity Audit\n",
              f"Proposals: {len(results)} | Rebuild: {rebuild_count} | Missed: {missed_count} | SLA breaches: {sla_breaches}\n"]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
