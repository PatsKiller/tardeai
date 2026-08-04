#!/usr/bin/env python3
"""CLI wrapper for autonomous discovery governance — thin, mirrors hermes_discovery_ingestors.py pattern.

Usage:
    python scripts/hermes_discovery_autonomy.py [--apply] [--limit N] [--json]

Safety: kill-switched via HERMES_DISABLED, dry-run by default.
"""
import argparse, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

KILL_FILE = ROOT / "data" / "runtime" / "HERMES_DISABLED"


def main():
    parser = argparse.ArgumentParser(description="Hermes Discovery — Autonomous Promotion")
    parser.add_argument("--apply", action="store_true", help="Apply promotions (default: dry-run)")
    parser.add_argument("--limit", type=int, default=5, help="Max candidates to promote this run")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    if KILL_FILE.exists():
        result = {"status": "kill_switch", "reason": "HERMES_DISABLED"}
        if args.json:
            print(json.dumps(result, default=str))
        else:
            print("ABORT: Kill switch active (data/runtime/HERMES_DISABLED)")
        sys.exit(1)

    from lib.hermes_discovery.autonomous_governance import run_autonomous_governance

    result = run_autonomous_governance(apply=args.apply, limit=args.limit)

    if args.json:
        print(json.dumps(result, default=str, indent=2))
    else:
        mode = result.get("mode", "unknown")
        n = result.get("actions", 0)
        skipped = result.get("skipped", 0)
        print(f"[{mode.upper()}] Autonomous governance: {n} promotions, {skipped} skipped")
        if result.get("promoted"):
            for p in result["promoted"]:
                print(f"  [{p['pathway']}] #{p['candidate_id']} {p.get('label','')} "
                      f"(score={p.get('score','')})")
        if result.get("remaining_caps"):
            print(f"  caps remaining: {result['remaining_caps']}")
        if result.get("reason") and result.get("status") != "ok":
            print(f"  BLOCKED: {result['reason']}")


if __name__ == "__main__":
    main()
