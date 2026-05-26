# Source Export: scripts/report_agent_learning_evidence_gate.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/report_agent_learning_evidence_gate.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `892c914e60269873a63f69132a9b4e085e439b39dc64b47476e1ac90f8dcd769` |
| **File Size** | 3670 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""report_agent_learning_evidence_gate.py — Prevent agent learning from weak evidence.

Read-only. No prompt/routing changes. No auto-apply.

Usage:
    .venv/bin/python scripts/report_agent_learning_evidence_gate.py --verbose
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


def main():
    p = argparse.ArgumentParser(description="Agent learning evidence gate (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    # Feedback observations
    cur.execute("SELECT COUNT(*) as c FROM llm_feedback_observations WHERE created_at > NOW() - INTERVAL '%s days'", [args.since_days])
    obs = cur.fetchone()["c"]

    # Learning recommendations
    cur.execute("SELECT status, applied, COUNT(*) as c FROM llm_learning_recommendations GROUP BY status, applied")
    recs = cur.fetchall()

    # Outcomes with evidence
    cur.execute("SELECT COUNT(*) as c FROM paper_trade_lifecycle_outcomes WHERE status='closed'")
    closed_outcomes = cur.fetchone()["c"]

    conn.close()

    total_recs = sum(r["c"] for r in recs)
    pending = sum(r["c"] for r in recs if r["status"] == "pending_human_review")
    applied = sum(r["c"] for r in recs if r.get("applied"))

    evidence_quality = "none" if closed_outcomes == 0 else "weak" if closed_outcomes < 10 else "preliminary" if closed_outcomes < 30 else "usable"
    allowed_action = "observe_only" if evidence_quality in ("none", "weak") else "human_review_only"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "observations": obs, "total_recommendations": total_recs,
        "pending_human_review": pending, "applied": applied,
        "closed_trade_outcomes": closed_outcomes,
        "evidence_quality": evidence_quality, "allowed_action": allowed_action,
        "auto_learning_blocked": True,
        "reason": f"Evidence quality is '{evidence_quality}' with {closed_outcomes} closed outcomes",
    }

    if args.verbose:
        print(f"Agent Learning Evidence Gate")
        print(f"  Observations: {obs}, Recommendations: {total_recs} (pending: {pending}, applied: {applied})")
        print(f"  Closed outcomes: {closed_outcomes}, Evidence: {evidence_quality}")
        print(f"  Allowed action: {allowed_action}, Auto-learning: BLOCKED")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Agent Learning Evidence Gate", f"\nEvidence: {evidence_quality} | Action: {allowed_action} | Auto-learning: BLOCKED",
              f"\n- Observations: {obs}", f"- Recommendations: {total_recs} (pending: {pending})",
              f"- Closed outcomes: {closed_outcomes}", f"- Applied: {applied}"]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
```
