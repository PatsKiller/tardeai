#!/usr/bin/env python3
"""audit_phase2h_bounded_approval.py — Confirm Phase 2H bounded approval is safe."""
import argparse, json, sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from phase2g_hybrid_canary_policy import load_policy, is_workflow_blocked, describe_policy

def main():
    p = argparse.ArgumentParser(description="Phase 2H bounded approval audit")
    p.add_argument("--config", default=str(PROJ / "config" / "phase2h_bounded_hybrid_rag_policy.yaml"))
    p.add_argument("--output-json", default=None)
    p.add_argument("--output-md", default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    policy = load_policy(args.config)
    desc = describe_policy(policy)

    # Blocked enforcement test
    blocked_tests = []
    for wf in ["telegram_realtime", "broker_execution", "risk_gate", "order_placement"]:
        blocked_tests.append({"workflow": wf, "blocked": is_workflow_blocked(wf, policy)})

    # Table counts
    table_counts = {}
    try:
        env = {}
        for line in (PROJ / ".env").read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
        import psycopg2
        conn = psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                                user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""))
        cur = conn.cursor()
        for t in ["content_embeddings", "content_embeddings_qwen3_shadow"]:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            table_counts[t] = cur.fetchone()[0]
        conn.close()
    except Exception as e:
        table_counts["error"] = str(e)

    result = {
        "phase": desc.get("phase"),
        "enabled": desc.get("enabled"),
        "global_promotion_approved": desc.get("global_promotion_approved"),
        "production_embedding": desc.get("production_embedding"),
        "shadow_embedding": desc.get("shadow_embedding"),
        "global_rag_default": desc.get("global_rag_default"),
        "approved_workflows": desc.get("allowed_workflows", []),
        "blocked_workflows": desc.get("blocked_workflows", []),
        "blocked_enforcement_tests": blocked_tests,
        "all_blocked_enforced": all(t["blocked"] for t in blocked_tests),
        "table_counts": table_counts,
        "rollback": "./scripts/rollback_phase2g_canary.sh --disable",
    }

    if args.verbose:
        print("=== Phase 2H Bounded Approval Audit ===")
        print(f"Phase: {result['phase']}")
        print(f"Enabled: {result['enabled']}")
        print(f"Global promotion: {result['global_promotion_approved']}")
        print(f"Production embedding: {result['production_embedding']}")
        print(f"Shadow embedding: {result['shadow_embedding']}")
        print(f"Approved workflows: {len(result['approved_workflows'])}")
        print(f"Blocked workflows: {len(result['blocked_workflows'])}")
        print(f"Blocked enforcement: {'ALL PASS' if result['all_blocked_enforced'] else 'FAIL'}")
        for t in blocked_tests:
            print(f"  {t['workflow']}: {'BLOCKED' if t['blocked'] else 'NOT BLOCKED!'}")
        print(f"Tables: {table_counts}")
        print(f"Rollback: {result['rollback']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(result, indent=2, default=str))
    if args.output_md:
        lines = ["# Phase 2H Bounded Approval Audit", "",
                 f"| Item | Value |", f"|------|-------|",
                 f"| Phase | {result['phase']} |",
                 f"| Enabled | {result['enabled']} |",
                 f"| Global promotion | {result['global_promotion_approved']} |",
                 f"| Production embedding | {result['production_embedding']} |",
                 f"| Shadow embedding | {result['shadow_embedding']} |",
                 f"| Approved workflows | {len(result['approved_workflows'])} |",
                 f"| Blocked workflows | {len(result['blocked_workflows'])} |",
                 f"| Blocked enforcement | {'ALL PASS' if result['all_blocked_enforced'] else 'FAIL'} |",
                 f"| Production rows | {table_counts.get('content_embeddings', '?')} |",
                 f"| Shadow rows | {table_counts.get('content_embeddings_qwen3_shadow', '?')} |",
                 f"| Rollback | `{result['rollback']}` |",
                 "", "## Blocked Workflow Tests", ""] + \
                [f"- {t['workflow']}: {'BLOCKED' if t['blocked'] else 'NOT BLOCKED!'}" for t in blocked_tests]
        Path(args.output_md).write_text("\n".join(lines))

if __name__ == "__main__":
    main()
