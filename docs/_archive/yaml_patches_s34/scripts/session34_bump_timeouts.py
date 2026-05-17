#!/usr/bin/env python3
"""
session34_bump_timeouts.py
==========================
Locates the 180-second LLM timeout in run_deep_overnight_llm_queue.py
and bumps to 300 seconds for `risk_synthesis` and `growth_strategy_scan`
(both observed timing out at 180s in the 2026-05-13 manual run).

Two strategies, picked based on what we find in the file:

  A) PER-JOB-TYPE OVERRIDE: if the file has a job-type dispatch or
     a TIMEOUT_BY_JOB_TYPE dict, add/update entries there.

  B) GLOBAL BUMP: if there's just a single timeout=180 constant,
     bump it to 300 globally.

Always creates a timestamped backup. Idempotent (skips if already patched).

Usage:
    cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
    python3 scripts/session34_bump_timeouts.py --dry-run
    python3 scripts/session34_bump_timeouts.py --apply
"""

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


TARGET = Path("scripts/run_deep_overnight_llm_queue.py")
HEAVY_JOB_TYPES = ["risk_synthesis", "growth_strategy_scan", "rebalance_analysis"]
NEW_TIMEOUT_SEC = 300


def find_timeout_lines(content):
    """Return list of (lineno, line) where timeout=N or TIMEOUT=N appears with N in 60..240."""
    hits = []
    for i, line in enumerate(content.splitlines(), 1):
        m = re.search(r"(timeout\s*[=:]\s*)(\d{2,3})\b", line, re.IGNORECASE)
        if m:
            val = int(m.group(2))
            if 60 <= val <= 240:
                hits.append((i, line, val))
        m2 = re.search(r"(TIMEOUT\w*\s*=\s*)(\d{2,3})\b", line)
        if m2:
            val = int(m2.group(2))
            if 60 <= val <= 240:
                hits.append((i, line, val))
    return hits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--target", default=str(TARGET))
    parser.add_argument("--backup-root", default="backups")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("ERROR: Specify --dry-run or --apply")
        sys.exit(1)

    target = Path(args.target)
    if not target.exists():
        print(f"ERROR: target file not found: {target}")
        sys.exit(1)

    content = target.read_text()
    hits = find_timeout_lines(content)

    print(f"Session 34 timeout bump — {'DRY-RUN' if args.dry_run else 'APPLY'}")
    print(f"Target: {target}")
    print(f"Heavy job types: {HEAVY_JOB_TYPES}")
    print(f"New timeout: {NEW_TIMEOUT_SEC}s")
    print("=" * 70)

    if not hits:
        print("No 180-range timeout values found via regex.")
        print("Manual inspection required. Showing all 'timeout' lines:")
        for i, line in enumerate(content.splitlines(), 1):
            if "timeout" in line.lower():
                print(f"  {i:4}: {line.rstrip()}")
        sys.exit(0)

    print(f"\nFound {len(hits)} timeout reference(s):")
    for lineno, line, val in hits:
        print(f"  L{lineno} (={val}s): {line.rstrip()}")

    # Decide strategy: is there evidence of per-job-type dispatch?
    has_job_type_dispatch = bool(re.search(
        r"(timeout.*job_type|job_type.*timeout|TIMEOUT_BY_JOB_TYPE|TIMEOUTS_BY_TYPE)",
        content, re.IGNORECASE,
    ))
    print(f"\nStrategy: {'PER-JOB-TYPE OVERRIDE' if has_job_type_dispatch else 'GLOBAL BUMP'}")

    new_content = content

    if not has_job_type_dispatch:
        # Strategy B: bump all 180->300 (only when 180 is the value and 'timeout' is on the line)
        def repl(m):
            val = int(m.group(2))
            return m.group(1) + str(NEW_TIMEOUT_SEC) if val == 180 else m.group(0)

        new_content = re.sub(
            r"(timeout\s*[=:]\s*)(180)\b",
            lambda m: m.group(1) + str(NEW_TIMEOUT_SEC),
            new_content,
            flags=re.IGNORECASE,
        )
        # Also TIMEOUT_FOO = 180
        new_content = re.sub(
            r"(TIMEOUT\w*\s*=\s*)(180)\b",
            lambda m: m.group(1) + str(NEW_TIMEOUT_SEC),
            new_content,
        )
    else:
        # Strategy A: inject a dispatch table near the top of main() if not present
        if "TIMEOUTS_BY_TYPE_SESSION34" not in new_content:
            injection = (
                "\n# === Session 34 hotfix: per-job-type timeout overrides ===\n"
                f"TIMEOUTS_BY_TYPE_SESSION34 = {{\n"
                + "".join(f'    "{jt}": {NEW_TIMEOUT_SEC},\n' for jt in HEAVY_JOB_TYPES)
                + "}\n"
                "def _resolve_timeout_session34(job_type, default_timeout):\n"
                "    return TIMEOUTS_BY_TYPE_SESSION34.get(job_type, default_timeout)\n"
                "# === end Session 34 hotfix ===\n\n"
            )
            # Inject after the imports
            new_content = re.sub(
                r"(\n(?:import |from )[^\n]+\n)(\n)",
                lambda m: m.group(1) + injection + m.group(2),
                new_content,
                count=1,
            )
            print("\nInjected TIMEOUTS_BY_TYPE_SESSION34 dispatch table.")
            print("**NOTE: you'll need to wire `_resolve_timeout_session34(job_type, 180)` "
                  "at the actual LLM call site. Grep for ollama.generate or local_llm call.**")

    if new_content == content:
        print("\nNo changes needed. (Already patched or no 180s timeouts to bump.)")
        sys.exit(0)

    # Show diff summary
    old_lines = content.splitlines()
    new_lines = new_content.splitlines()
    changed = sum(1 for o, n in zip(old_lines, new_lines) if o != n)
    print(f"\nLines changed: {changed}")

    if args.apply:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(args.backup_root) / f"session34_timeout_{ts}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup_dir / target.name)
        print(f"Backup: {backup_dir / target.name}")

        target.write_text(new_content)
        print(f"Wrote: {target}")
    else:
        print("\nDry-run. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
