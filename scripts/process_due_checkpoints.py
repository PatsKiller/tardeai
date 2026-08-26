#!/usr/bin/env python3
"""Observational due-checkpoint processor. No trading. No fabricated elapsed time.

Intended for a later-authorized systemd timer. Does not self-install.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.r17_checkpoint_binding import process_due_store  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=str(ROOT))
    p.add_argument("--source-available", action="store_true")
    p.add_argument("--persist", action="store_true")
    p.add_argument("--event-occurred", action="store_true")
    args = p.parse_args()
    out = process_due_store(
        args.root,
        source_available=args.source_available,
        persist=args.persist,
        event_occurred=args.event_occurred,
    )
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
