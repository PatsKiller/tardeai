#!/usr/bin/env python3
"""Render / apply Mergify window presets into config + .mergify.yml.

Usage:
  .venv/bin/python scripts/render_mergify_windows.py              # print active schedules
  .venv/bin/python scripts/render_mergify_windows.py --preset after_hours --apply
  .venv/bin/python scripts/render_mergify_windows.py --json         # Ops / Releases view

--apply updates config/mergify_windows.json preset and rewrites every schedule
or-block in .mergify.yml. Commit both in the same PR. Mergify only honors
schedules after that PR reaches main.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import mergify_windows as MW  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preset", help="Preset id (after_hours | narrow_four | weekends_only)")
    ap.add_argument("--apply", action="store_true", help="Write config + .mergify.yml")
    ap.add_argument("--json", action="store_true", help="Print Ops view JSON")
    ap.add_argument("--dry-run", action="store_true", help="Show .mergify.yml diff intent without writing")
    args = ap.parse_args()

    if args.json:
        print(json.dumps(MW.view_for_ops(), indent=2, default=str))
        return 0

    preset = args.preset or MW.active_preset()
    schedules = MW.schedules_for(preset)
    print(f"preset={preset}")
    for s in schedules:
        print(f"  {s}")
    snap = MW.in_window()
    print(f"open_now={snap['open']} market_freeze={snap['market_freeze']} as_of={snap['as_of']}")

    if args.apply or args.dry_run:
        new_yml = MW.apply_schedules_to_mergify_yml(preset=preset)
        if args.dry_run:
            print("--- dry-run: would write .mergify.yml (%d bytes) ---" % len(new_yml))
            return 0
        MW.set_preset_in_config(preset)
        MW.MERGIFY_YML.write_text(new_yml, encoding="utf-8")
        print(f"wrote {MW.CONFIG_PATH} preset={preset}")
        print(f"wrote {MW.MERGIFY_YML}")
        print("Commit both files and open a PR; Mergify reads schedules from main only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
