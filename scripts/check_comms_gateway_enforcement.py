#!/usr/bin/env python3
"""Run all communications gateway static enforcement checks.

Exit non-zero if any ratchet fails (new bypass or growth vs baseline).

    scripts/check_comms_gateway_enforcement.py
    scripts/check_comms_gateway_enforcement.py --report
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKS = (
    ("telegram", ROOT / "scripts" / "check_telegram_chokepoint.py"),
    ("provider", ROOT / "scripts" / "check_provider_chokepoint.py"),
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    rc = 0
    for name, path in CHECKS:
        if not path.is_file():
            print(f"[comms-enforcement] MISSING {path}", file=sys.stderr)
            rc = 1
            continue
        args = [sys.executable, str(path)]
        if a.report:
            args.append("--report")
        print(f"\n== {name} chokepoint ==")
        p = subprocess.run(args, cwd=str(ROOT))
        if p.returncode != 0:
            rc = p.returncode or 1
    if rc == 0:
        print("\n[comms-enforcement] pass (all ratchets held)")
    else:
        print("\n[comms-enforcement] FAIL", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
