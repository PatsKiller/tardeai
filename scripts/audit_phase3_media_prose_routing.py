#!/usr/bin/env python3
"""audit_phase3_media_prose_routing.py — Report Phase 3C routing status."""
import argparse, json, sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from phase3_media_prose_routing_policy import load_policy, describe_policy, is_workflow_blocked

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-json", default=None)
    p.add_argument("--output-md", default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    desc = describe_policy()
    blocked_tests = [{"wf": w, "blocked": is_workflow_blocked(w)} for w in
                     ["broker_execution", "risk_gate", "telegram_realtime_trading"]]
    result = {**desc, "blocked_tests": blocked_tests,
              "all_blocked_pass": all(t["blocked"] for t in blocked_tests),
              "rollback": "./scripts/rollback_phase3_media_prose_routing.sh --disable"}

    if args.verbose:
        print("=== Phase 3C Routing Audit ===")
        print(f"Phase: {desc['phase']}")
        print(f"Enabled: {desc['enabled']}")
        print(f"Candidate: {desc['candidate']}")
        print(f"Fallback: {desc['fallback']}")
        print(f"Standard: {desc['standard']}")
        print(f"Embedding: {desc['embedding']}")
        print(f"Approved: {len(desc['approved'])}")
        print(f"Blocked: {len(desc['blocked'])}")
        for t in blocked_tests:
            print(f"  {t['wf']}: {'BLOCKED' if t['blocked'] else 'NOT BLOCKED!'}")
        print(f"Rollback: {result['rollback']}")

    if args.output_json: Path(args.output_json).write_text(json.dumps(result, indent=2))
    if args.output_md:
        Path(args.output_md).write_text(
            f"# Phase 3C Routing Audit\n\nEnabled: {desc['enabled']}\n"
            f"Candidate: {desc['candidate']}\nApproved: {len(desc['approved'])}\n"
            f"Blocked: {len(desc['blocked'])}\nBlocked tests: {'ALL PASS' if result['all_blocked_pass'] else 'FAIL'}\n")

if __name__ == "__main__":
    main()
