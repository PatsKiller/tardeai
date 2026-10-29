#!/usr/bin/env python3
"""Mergify Dequeued monitor — classify, auto-requeue, or wake the claim owner.

Dequeued is not done. Default is ``--dry-run`` (receipt only). Live needs the
operator or a scheduled lane once the hotfix is on main.

Usage::

  .venv/bin/python scripts/mergify_queue_monitor.py --dry-run
  .venv/bin/python scripts/mergify_queue_monitor.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.mergify_queue_monitor import run_once  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", default=False, help="Receipt only (default if neither flag)")
    ap.add_argument("--apply", action="store_true", help="Comment / requeue / wake / page")
    ap.add_argument("--repo", default="PatsKiller/tardeai")
    args = ap.parse_args()
    dry = not args.apply
    if args.dry_run:
        dry = True
    receipt = run_once(dry_run=dry, repo=args.repo)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
