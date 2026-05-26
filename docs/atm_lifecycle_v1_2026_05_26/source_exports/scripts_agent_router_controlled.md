# Source Export: scripts/agent_router_controlled.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/agent_router_controlled.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `10a42a23bd03a278b323c9b84356235672bef3d9fa14f482ae6f206c90316b0a` |
| **File Size** | 2026 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""
agent_router_controlled.py

Final controlled router wrapper:
1. agent_router.py does intent routing
2. agent_reliability.py attaches DB-backed reliability
3. reliability_decision_control.py changes behavior
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from agent_reliability import get_agent_reliability
from reliability_decision_control import apply_reliability_controls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--message", "-m", required=True)
    parser.add_argument("--from-agent", default="user")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    cmd = [
        "python3", "scripts/agent_router.py",
        "--message", args.message,
        "--from-agent", args.from_agent,
        "--json",
    ]
    if args.save:
        cmd.append("--save")

    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, capture_output=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        sys.exit(proc.returncode)

    route = json.loads(proc.stdout)

    rel = get_agent_reliability(route.get("to_agent", "orchestrator"))
    old_conf = float(route.get("confidence", 0.0) or 0.0)
    adj = float(rel.get("confidence_adjustment", 0.0) or 0.0)

    route["reliability"] = rel
    route["confidence_before_reliability"] = old_conf
    route["confidence"] = max(0.0, min(1.0, round(old_conf + adj, 2)))

    if rel.get("warnings"):
        route.setdefault("pending_actions", []).append({
            "type": "reliability_warning",
            "message": "DB freshness history reduced confidence.",
            "warnings": rel.get("warnings"),
            "confidence_adjustment": adj,
        })

    route = apply_reliability_controls(route)

    print(json.dumps(route, indent=2))


if __name__ == "__main__":
    main()
```
