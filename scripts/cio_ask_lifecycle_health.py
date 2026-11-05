#!/usr/bin/env python3
"""Read-only Ask hourly/material-event health. No provider, send or writes."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cio_ask_lifecycle_health import collect_cio_ask_lifecycle_health


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, help='explicit state/fixture root')
    parser.add_argument('--now', help='timezone-aware ISO observation time')
    parser.add_argument('--dry-run', action='store_true', help='read-only projection; all modes write nothing')
    parser.add_argument('--strict', action='store_true', help='exit 3 on a measured finding/unavailable evidence')
    args = parser.parse_args(argv)
    try:
        now = datetime.fromisoformat(args.now.replace('Z', '+00:00')) if args.now else None
        result = collect_cio_ask_lifecycle_health(root=args.root, now=now)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 3 if args.strict and not result['ok'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
