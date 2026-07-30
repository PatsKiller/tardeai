#!/usr/bin/env python3
"""Read-only historical outcome completeness dry run.

Input is optional synthetic JSON. The script never writes backfill rows and never
alters maturity scores.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_runtime.maturity_observability import analyze_outcome_completeness


def main() -> int:
    parser = argparse.ArgumentParser(description="agent maturity outcome completeness dry run")
    parser.add_argument("--input-json", help="optional synthetic/sanitized records")
    args = parser.parse_args()
    records = []
    if args.input_json:
        payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
        records = payload if isinstance(payload, list) else payload.get("records", [])
    print(json.dumps(analyze_outcome_completeness(records), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
