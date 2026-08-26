#!/usr/bin/env python3
"""CIO defer/revisit worker — reopen + revalidate + publish-if-material.

Authority: READ_ONLY_ADVISORY.
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
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--live", action="store_true", default=False)
    args = p.parse_args(argv)
    dry = not (args.live and "--dry-run" not in (argv or sys.argv[1:]))
    from scripts.lib.cio_defer_revisit import process_due_defers
    rec = process_due_defers(dry_run=dry)
    print(json.dumps({
        "ok": rec.get("ok"),
        "dry_run": rec.get("dry_run"),
        "delivery_mode": rec.get("delivery_mode"),
        "due": rec.get("due"),
        "processed": rec.get("processed"),
        "receipt_path": rec.get("receipt_path"),
        "authority": rec.get("authority"),
    }, indent=2, default=str))
    return 0 if rec.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
