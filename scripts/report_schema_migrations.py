#!/usr/bin/env python3
"""List migration files that are not in an applied-name set.

Read-only. This does not connect to Postgres and does not apply SQL.
Pass applied names on stdin, one per line, or omit stdin for the full list.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def pending(files: list[str], applied: set[str]) -> list[str]:
    return sorted(name for name in files if Path(name).name not in applied)


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("migrations")
    files = [p.name for p in sorted(root.glob("*.sql"))] if root.is_dir() else []
    applied = {ln.strip() for ln in sys.stdin if ln.strip()} if not sys.stdin.isatty() else set()
    missing = pending(files, applied)
    print(json.dumps({"files": len(files), "pending": missing}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
