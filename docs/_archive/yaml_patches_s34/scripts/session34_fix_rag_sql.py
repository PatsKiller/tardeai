#!/usr/bin/env python3
"""
session34_fix_rag_sql.py
========================
The rag_content_curation queue-builder uses:

    ORDER BY created_at DESC LIMIT 8

But the target table doesn't have a `created_at` column. This script
finds the file containing that SQL and rewrites the column name to
match what actually exists on the target table.

Usage:
    # 1. From the diagnostic report Section 2, identify:
    #    - the file that contains 'ORDER BY created_at DESC LIMIT 8'
    #    - the actual timestamp column on the RAG source table
    #      (commonly inserted_at, ingested_at, indexed_at, or just date)

    # 2. Run the fix:
    python3 scripts/session34_fix_rag_sql.py \\
        --file scripts/some_file.py \\
        --replacement-column inserted_at \\
        --dry-run

    python3 scripts/session34_fix_rag_sql.py \\
        --file scripts/some_file.py \\
        --replacement-column inserted_at \\
        --apply
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="File containing the broken SQL")
    parser.add_argument("--replacement-column", required=True,
                        help="The actual column name to use (e.g. inserted_at)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-root", default="backups")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("ERROR: Specify --dry-run or --apply")
        sys.exit(1)

    target = Path(args.file)
    if not target.exists():
        print(f"ERROR: file not found: {target}")
        sys.exit(1)

    content = target.read_text()
    needle = "ORDER BY created_at DESC LIMIT 8"
    if needle not in content:
        print(f"WARN: pattern '{needle}' not found in {target}")
        print("Showing all 'created_at' references in file:")
        for i, line in enumerate(content.splitlines(), 1):
            if "created_at" in line:
                print(f"  L{i}: {line.rstrip()}")
        sys.exit(0)

    replacement = f"ORDER BY {args.replacement_column} DESC LIMIT 8"
    new_content = content.replace(needle, replacement)

    print(f"Session 34 RAG SQL fix — {'DRY-RUN' if args.dry_run else 'APPLY'}")
    print(f"File: {target}")
    print(f"Replacing: {needle!r}")
    print(f"With:      {replacement!r}")
    print(f"Occurrences: {content.count(needle)}")

    if args.apply:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(args.backup_root) / f"session34_rag_sql_{ts}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup_dir / target.name)
        print(f"Backup: {backup_dir / target.name}")

        target.write_text(new_content)
        print(f"Wrote: {target}")
    else:
        print("\nDry-run. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
