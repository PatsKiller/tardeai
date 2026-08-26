#!/usr/bin/env python3
"""CLI: exit 0 iff CURRENT scripts/+docs/ match SOURCE_COMMIT.

  python3 scripts/current_pin_integrity.py
  python3 scripts/current_pin_integrity.py --json

Used by cio_phase2_exact_main_deploy.sh prepare — refuse to stamp a hybrid.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.current_pin_integrity import collect_pin_report  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    row = collect_pin_report()
    print(json.dumps(row, indent=2, default=str))
    if not args.json and not row.get("ok"):
        print("CURRENT pin mismatch — refuse hybrid", file=sys.stderr)
    return 0 if row.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
