#!/usr/bin/env python3
"""report_phase5_human_review_queue.py — Report pending learning recommendations for operator review."""
import argparse, json, sys
from datetime import datetime
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

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--status", default="pending_human_review")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--output-json", default=None)
    p.add_argument("--output-md", default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT id, recommendation_type, workflow, model_role,
                          current_behavior, proposed_change, evidence_summary,
                          risk_level, status, created_at
                   FROM llm_learning_recommendations
                   WHERE status = %s ORDER BY created_at DESC LIMIT %s""",
                [args.status, args.limit])
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    if args.verbose:
        print(f"Pending recommendations: {len(rows)}")
        for r in rows:
            print(f"  #{r['id']} [{r['risk_level']}] {r['recommendation_type']}: {r['workflow']} — {r['proposed_change'][:60]}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps({"count": len(rows), "items": rows}, indent=2, default=str))
    if args.output_md:
        lines = [f"# Phase 5 Human Review Queue\n\n**Pending:** {len(rows)}\n"]
        for r in rows:
            lines.append(f"- #{r['id']} [{r['risk_level']}] {r['recommendation_type']}: {r['workflow']} — {r['proposed_change'][:80]}")
        if not rows:
            lines.append("No pending recommendations.\n")
        Path(args.output_md).write_text("\n".join(lines))

    conn.close()

if __name__ == "__main__":
    main()
