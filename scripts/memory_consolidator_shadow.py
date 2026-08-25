#!/usr/bin/env python3
"""CLI: SHADOW-ONLY consolidator against an isolated root.

Never apply to production Postgres. MEMORY_BEHAVIOR_INFLUENCE=0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.memory_consolidator_shadow import run_shadow_consolidator  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="SHADOW-ONLY memory consolidator")
    parser.add_argument("--isolated-root", required=True, help="Non-authoritative workspace root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = Path(args.isolated_root)
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
    # Refuse obvious production cluster paths.
    if str(root).rstrip("/").endswith(":5432") or "5432" in str(root):
        print("REFUSED: production postgres path", file=sys.stderr)
        return 2
    result = run_shadow_consolidator(root)
    if result.get("memory_behavior_influence") != 0:
        print("REFUSED: influence must be 0", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(result, sort_keys=True, default=str))
    else:
        print(
            f"shadow admitted={result['admitted_candidates']} "
            f"pref={result['preference_candidates']} "
            f"lessons={result['lesson_candidates']} "
            f"influence={result['memory_behavior_influence']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
