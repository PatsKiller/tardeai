#!/usr/bin/env python3
"""Sanitize operator-collected OpenClaw runtime inventory metadata.

The helper never reads ~/.openclaw/openclaw.json by default. Operators must pass a
pre-sanitized metadata JSON file that contains only allowlisted fields.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_runtime.maturity_observability import sanitize_runtime_inventory


def main() -> int:
    parser = argparse.ArgumentParser(description="sanitize OpenClaw runtime inventory metadata")
    parser.add_argument("input_json", help="operator-supplied allowlisted metadata JSON; do not pass raw OpenClaw config")
    args = parser.parse_args()
    path = Path(args.input_json)
    if path.name == "openclaw.json" or ".openclaw" in path.parts:
        print("refusing to read raw OpenClaw config path", file=sys.stderr)
        return 2
    raw = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(sanitize_runtime_inventory(raw), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
