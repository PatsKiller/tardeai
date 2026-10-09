#!/usr/bin/env python3
"""Archive-rotate data/runtime/advisory_kb_lessons.jsonl (never deletes).

Dry-run (read-only: no lock file, no writes) unless --apply. Rows older than
retain_days (config/advisory_kb_lessons_retention.json, default 90) move into
<state_root>/archive/advisory_kb_lessons/YYYY-MM.jsonl.gz with a SHA256SUMS
manifest; the newest row per lesson id and rows with an unparseable timestamp
stay live. See scripts/lib/advisory/kb_lessons_retention.py for the ordering
and verify steps.

  python3 scripts/rotate_advisory_kb_lessons.py                 # dry-run report
  python3 scripts/rotate_advisory_kb_lessons.py --apply         # rotate
  python3 scripts/rotate_advisory_kb_lessons.py --live PATH --archive-dir DIR --retain-days N
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.advisory import kb_lessons_retention as ret  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report only (default)")
    mode.add_argument("--apply", action="store_true", help="move old rows into archives")
    ap.add_argument("--live", default="", help="live jsonl (default: <state_root>/<live_rel>)")
    ap.add_argument("--archive-dir", default="", help="archive dir (default: <state_root>/<archive_subdir>)")
    ap.add_argument("--retain-days", type=int, default=None, help="override config retain_days")
    ap.add_argument("--config", default="", help="alternate retention config")
    args = ap.parse_args(argv)
    cfg = ret.load_config(Path(args.config)) if args.config else ret.load_config()
    live = Path(args.live) if args.live else None
    if args.apply:
        out = ret.apply(live, archive_dir=Path(args.archive_dir) if args.archive_dir else None,
                        cfg=cfg, retain_days=args.retain_days)
    else:
        out = ret.plan(live, cfg=cfg, retain_days=args.retain_days)
        if args.archive_dir:
            out["archive_dir"] = args.archive_dir
    print(json.dumps(out, indent=1, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
