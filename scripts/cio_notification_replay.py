#!/usr/bin/env python3
"""CLI: run the deterministic CIO notification replay (shadow only, no sends).

Usage:
  python scripts/cio_notification_replay.py [--state PATH]

Reports raw evaluations vs. immediate / digest / command-center-only /
suppressed counts for the Aug-17-shaped operator-history fixture.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state", default="", help="Override notification state path")
    args = p.parse_args(argv)

    from scripts.lib.cio_notification_replay import run_aug17_replay
    from scripts.lib.cio_notification_signal import NotificationStateStore

    store = None
    if args.state:
        sp = Path(args.state)
        store = NotificationStateStore(
            state_path=sp / "state.jsonl",
            audit_path=sp / "audit.jsonl",
            metrics_path=sp / "metrics.jsonl",
        )
    result = run_aug17_replay(store=store)
    result["authority"] = "READ_ONLY_ADVISORY"
    result["telegram_sends"] = 0
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
