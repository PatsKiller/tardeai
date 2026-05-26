# Source Export: scripts/agent_router_reliable.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/agent_router_reliable.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `625ddc7c8f74f3493cc245a6f7073d2d1233ed741006f926faab441f7093806c` |
| **File Size** | 2039 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""
agent_router_reliable.py

Safe wrapper around agent_router.py.
Does not modify router internals.

Flow:
1. Calls agent_router.py --json
2. Loads DB-backed reliability context
3. Adjusts confidence
4. Prints enriched route JSON
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from agent_reliability import get_agent_reliability


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--message", "-m", required=True)
    parser.add_argument("--from-agent", default="user")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    cmd = [
        "python3",
        "scripts/agent_router.py",
        "--message",
        args.message,
        "--from-agent",
        args.from_agent,
        "--json",
    ]

    if args.save:
        cmd.append("--save")

    proc = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )

    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        sys.exit(proc.returncode)

    route = json.loads(proc.stdout)

    agent = route.get("to_agent", "orchestrator")
    rel = get_agent_reliability(agent)

    old_conf = float(route.get("confidence", 0.0) or 0.0)
    adj = float(rel.get("confidence_adjustment", 0.0) or 0.0)
    new_conf = max(0.0, min(1.0, round(old_conf + adj, 2)))

    route["reliability"] = rel
    route["confidence_before_reliability"] = old_conf
    route["confidence"] = new_conf

    if rel.get("warnings"):
        route.setdefault("pending_actions", []).append({
            "type": "reliability_warning",
            "message": "DB freshness history reduced confidence.",
            "warnings": rel.get("warnings"),
            "confidence_adjustment": adj,
        })

    print(json.dumps(route, indent=2))


if __name__ == "__main__":
    main()
```
