#!/usr/bin/env python3
"""Run Hermes librarian retention enforcement (archive → purge ladder).

The daily backlog timer only stages research. This entrypoint applies
``scripts/lib/hermes_librarian/retention.py`` so orphan embeddings and
archived research are actually purged per ``config/hermes_librarian_policy.yaml``.

Usage:
  python scripts/run_hermes_librarian_retention.py --dry-run
  python scripts/run_hermes_librarian_retention.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Count only (default unless --apply)")
    ap.add_argument("--apply", action="store_true", help="Mutate DB per retention policy")
    args = ap.parse_args()
    dry = True if not args.apply else False
    if args.dry_run:
        dry = True

    from db_adapter import _get_conn
    from lib.hermes_librarian.retention import apply_retention

    conn = _get_conn()
    try:
        result = apply_retention(conn, dry_run=dry)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    out = {
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry,
        **result,
    }
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
