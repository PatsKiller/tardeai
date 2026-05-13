#!/usr/bin/env python3
"""Update stale metric claims in documentation files.

Reads live system counts and replaces known stale values in docs.

Usage:
    .venv/bin/python scripts/update_doc_metrics.py --dry-run
    .venv/bin/python scripts/update_doc_metrics.py
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
DOCS = PROJ / "docs"


def get_live_counts():
    """Get current system metric counts."""
    counts = {}

    # Table count
    try:
        pw = ""
        for line in (PROJ / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip()
        result = subprocess.run(
            ["psql", "-h", "localhost", "-U", "trade_ai", "-d", "trade_ai",
             "-tAc", "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"],
            capture_output=True, text=True, env={**os.environ, "PGPASSWORD": pw})
        counts["table_count"] = int(result.stdout.strip())
    except Exception:
        counts["table_count"] = None

    # Python script count
    try:
        result = subprocess.run(
            ["find", str(PROJ / "scripts"), "-name", "*.py", "-type", "f"],
            capture_output=True, text=True)
        counts["python_script_count"] = len(result.stdout.strip().splitlines())
    except Exception:
        counts["python_script_count"] = None

    # Cron count
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        lines = [l for l in result.stdout.splitlines()
                 if l.strip() and not l.startswith("#") and not l.startswith("PROJ=") and not l.startswith("PY=")]
        counts["cron_count"] = len(lines)
    except Exception:
        counts["cron_count"] = None

    # Frontend page count
    try:
        pages_dir = PROJ / "apps" / "command-center-v2" / "src" / "pages"
        counts["frontend_page_count"] = len(list(pages_dir.glob("*.tsx")))
    except Exception:
        counts["frontend_page_count"] = None

    return counts


# Known stale values and their replacements
# Format: (file_glob, old_pattern, metric_key, context_description)
REPLACEMENTS = [
    # table_count: 299 → live
    ("CHEAT_SHEET.md", r"\b299\b", "table_count", "tables"),
    ("ARCHITECTURE_OVERVIEW.md", r"\b299\b", "table_count", "tables"),
    ("RESTORE_GUIDE.md", r"\b299\b", "table_count", "tables"),
    ("MASTER_SYSTEM_DOCUMENTATION.md", r"\b299\b", "table_count", "tables"),
    ("COST_MODEL.md", r"\b299\b", "table_count", "tables"),

    # python_script_count: various → live
    ("CHEAT_SHEET.md", r"\b3 Python scripts\b", "python_script_count", "scripts_phrase"),
    ("RESTORE_GUIDE.md", r"\b3 Python scripts\b", "python_script_count", "scripts_phrase"),
    ("MASTER_SYSTEM_DOCUMENTATION.md", r"\b90 Python\b", "python_script_count", "scripts_90"),

    # cron_job_count: 142 → live
    ("ARCHITECTURE_OVERVIEW.md", r"\b142 cron\b", "cron_count", "crons"),
    ("MASTER_SYSTEM_DOCUMENTATION.md", r"\b142 cron\b", "cron_count", "crons"),

    # frontend_page_count: 55 → live
    ("ARCHITECTURE_OVERVIEW.md", r"\b55 (routes|pages)\b", "frontend_page_count", "pages"),
]


def update_file(filepath, replacements, counts, dry_run):
    """Apply metric replacements to a single file. Returns count of changes."""
    if not filepath.exists():
        return 0

    text = filepath.read_text()
    original = text
    changes = 0

    for old_pattern, metric_key, context in replacements:
        val = counts.get(metric_key)
        if val is None:
            continue

        if context == "tables":
            new_text = re.sub(r"\b299\b(?=.*table)", str(val), text)
            if new_text != text:
                text = new_text
                changes += 1
        elif context == "scripts_phrase":
            text_new = text.replace("3 Python scripts", f"{val} Python scripts")
            if text_new != text:
                text = text_new
                changes += 1
        elif context == "scripts_90":
            text_new = text.replace("90 Python", f"{val} Python")
            if text_new != text:
                text = text_new
                changes += 1
        elif context == "crons":
            text_new = text.replace("142 cron", f"{val} cron")
            if text_new != text:
                text = text_new
                changes += 1
        elif context == "pages":
            text_new = re.sub(r"\b55 (routes|pages)", f"{val} \\1", text)
            if text_new != text:
                text = text_new
                changes += 1

    if changes and not dry_run:
        filepath.write_text(text)

    return changes


def main():
    parser = argparse.ArgumentParser(description="Update stale doc metrics")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    counts = get_live_counts()
    print("Live system counts:")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print()

    # Group replacements by file
    file_replacements = {}
    for filename, pattern, metric_key, context in REPLACEMENTS:
        filepath = DOCS / filename
        if filepath not in file_replacements:
            file_replacements[filepath] = []
        file_replacements[filepath].append((pattern, metric_key, context))

    total_changes = 0
    files_changed = 0

    for filepath, repls in file_replacements.items():
        n = update_file(filepath, repls, counts, args.dry_run)
        if n > 0:
            print(f"  {'Would update' if args.dry_run else 'Updated'} {filepath.name}: {n} replacements")
            total_changes += n
            files_changed += 1
        else:
            print(f"  {filepath.name}: no changes needed")

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Updated {total_changes} values across {files_changed} files")


if __name__ == "__main__":
    main()
