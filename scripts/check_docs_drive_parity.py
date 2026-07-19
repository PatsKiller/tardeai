#!/usr/bin/env python3
"""check_docs_drive_parity.py — v1.1 P9: alert when canonical lifecycle docs are
missing or stale in the Drive sync manifest. Piggybacks the hourly
sync-docs-to-drive.sh (gog) manifest — read-only; exit 1 + stderr line on drift
so the health surface can alarm."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = Path.home() / ".local" / "state" / "drive-sync-manifest.txt"
CANONICAL = [
    "docs/OPTIONS_LIFECYCLE_DESK.md",
    "docs/_findings/OPTIONS_LIFECYCLE_DESK_DIAGNOSIS_2026-07-19.md",
    "docs/_findings/OPTIONS_LIFECYCLE_V1_1_INTEGRATION_AUDIT_2026-07-19.md",
    "docs/options-module.md",
    "docs/DOCUMENTATION_INDEX.md",
]
STALE_HOURS = 26   # hourly sync + slack


def main() -> int:
    problems = []
    manifest = MANIFEST.read_text() if MANIFEST.exists() else ""
    for rel in CANONICAL:
        p = ROOT / rel
        if not p.exists():
            problems.append(f"MISSING IN REPO: {rel}")
            continue
        if Path(rel).name not in manifest:
            problems.append(f"NOT IN DRIVE MANIFEST yet: {rel} (next hourly sync should pick it up; "
                            "alarm only if this persists)")
    if MANIFEST.exists():
        age_h = (time.time() - MANIFEST.stat().st_mtime) / 3600
        if age_h > STALE_HOURS:
            problems.append(f"Drive sync manifest {age_h:.0f}h old (> {STALE_HOURS}h) — sync cron may be dead")
    else:
        problems.append("Drive sync manifest absent — sync has never run on this host?")
    if problems:
        print("DOCS↔DRIVE PARITY: DRIFT", file=sys.stderr)
        for x in problems:
            print(" -", x)
        return 1
    print(f"DOCS↔DRIVE PARITY: OK ({len(CANONICAL)} canonical docs tracked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
