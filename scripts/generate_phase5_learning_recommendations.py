#!/usr/bin/env python3
"""generate_phase5_learning_recommendations.py — Generate human-reviewable recommendations. Does NOT auto-apply."""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

def get_conn():
    import psycopg2
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""))

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [phase5-learn] {msg}", flush=True)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--min-observations", type=int, default=10)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--output-json", default=None)
    p.add_argument("--output-md", default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if not args.dry_run and not args.apply:
        args.dry_run = True

    conn = get_conn()
    cur = conn.cursor()

    # Aggregate observations by workflow
    cur.execute("""SELECT workflow, model_role, COUNT(*) as cnt,
                          COUNT(DISTINCT symbol) as symbols
                   FROM llm_feedback_observations
                   WHERE created_at > NOW() - INTERVAL '%s days'
                   GROUP BY workflow, model_role
                   ORDER BY cnt DESC""" % args.since_days)
    groups = cur.fetchall()

    recommendations = []
    for wf, role, cnt, syms in groups:
        if cnt < args.min_observations:
            continue

        # Generate workflow quality recommendation
        rec = {
            "recommendation_type": "workflow_quality",
            "workflow": wf, "model_role": role,
            "current_behavior": f"{cnt} observations, {syms} symbols",
            "proposed_change": f"Review {wf} output quality and add outcome labels",
            "evidence_summary": f"{cnt} observations collected, {syms} unique symbols",
            "risk_level": "low",
            "status": "pending_human_review",
        }
        recommendations.append(rec)

    # Check for high-fallback workflows (from observations with fallback_used)
    cur.execute("""SELECT workflow, COUNT(*) as total,
                          SUM(CASE WHEN fallback_used THEN 1 ELSE 0 END) as fallbacks
                   FROM llm_feedback_observations
                   WHERE created_at > NOW() - INTERVAL '%s days'
                   GROUP BY workflow HAVING COUNT(*) >= %s""" % (args.since_days, args.min_observations))
    for wf, total, fb in cur.fetchall():
        if fb and fb > 0 and total > 0:
            rate = round(100 * fb / total, 1)
            if rate > 5:
                recommendations.append({
                    "recommendation_type": "fallback_reduction",
                    "workflow": wf, "model_role": "mixed",
                    "current_behavior": f"{rate}% fallback rate ({fb}/{total})",
                    "proposed_change": "Investigate model availability or prompt issues",
                    "evidence_summary": f"Fallback rate {rate}% exceeds 5% threshold",
                    "risk_level": "medium",
                    "status": "pending_human_review",
                })

    log(f"Generated {len(recommendations)} recommendations")

    if args.apply and recommendations:
        inserted = 0
        for rec in recommendations:
            cur.execute("""INSERT INTO llm_learning_recommendations
                (recommendation_type, workflow, model_role, current_behavior,
                 proposed_change, evidence_summary, risk_level, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                [rec["recommendation_type"], rec["workflow"], rec["model_role"],
                 rec["current_behavior"], rec["proposed_change"],
                 rec["evidence_summary"], rec["risk_level"], rec["status"]])
            inserted += 1
        conn.commit()
        log(f"Inserted: {inserted}")

    report = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "mode": "dry_run" if args.dry_run else "applied",
              "recommendations": len(recommendations),
              "details": recommendations}

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        lines = [f"# Phase 5 Learning Recommendations\n\n**Count:** {len(recommendations)}\n"]
        for r in recommendations:
            lines.append(f"- [{r['risk_level']}] {r['recommendation_type']}: {r['workflow']} — {r['proposed_change']}")
        Path(args.output_md).write_text("\n".join(lines))

    conn.close()

if __name__ == "__main__":
    main()
