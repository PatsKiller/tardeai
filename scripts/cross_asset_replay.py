#!/usr/bin/env python3
"""Replay frozen cross-asset events into an explicit shadow output.

This command is intentionally offline.  It reads caller-supplied JSONL files,
does not resolve production state, and does not contact a broker or scheduler.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.lib.cross_asset_decision import replay_events
except ImportError:  # script-by-path invocation with scripts/ on sys.path
    from lib.cross_asset_decision import replay_events  # type: ignore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--identities", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    events = [json.loads(line) for line in args.events.read_text(encoding="utf-8").splitlines() if line.strip()]
    identities = json.loads(args.identities.read_text(encoding="utf-8"))
    decisions = replay_events(events, identity_by_symbol=identities)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in decisions),
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "events": len(events), "decisions": len(decisions), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
