#!/usr/bin/env python3
"""install_watchlist_remediation_cron.py — idempotent, reversible cron installer.

Installs the six watchlist-remediation jobs (2026-08-19 audit), enables desk auto-apply
(CURATION_AUTO_APPLY=1 on the watch_directives_service line), and schedules the
cron_self_heal watchdog. Reads the LIVE crontab, so it never clobbers concurrent changes.

Everything is additive + idempotent:
  1. Add the 6 remediation cron lines (from job_coverage_monitor.REGISTRY, cron_line).
  2. Prefix CURATION_AUTO_APPLY=1 on the watch_directives_service.py --apply line.
  3. Add the cron_self_heal.py --apply watchdog line (every 15 min, weekdays).

Usage:
    python3 scripts/install_watchlist_remediation_cron.py           # DRY-RUN diff
    python3 scripts/install_watchlist_remediation_cron.py --apply   # install (backs up first)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from job_coverage_monitor import REGISTRY  # noqa: E402

# The 6 remediation cron lines live in the monitor REGISTRY (single source of truth).
REMEDIATION_LINES = [j["cron_line"] for j in REGISTRY if j.get("cron_line")]

SELF_HEAL_LINE = (
    "*/15 6-20 * * 1-5 cd $PROJ && $PY scripts/cron_self_heal.py --apply"
    " >> logs/cron_self_heal.log 2>&1"
)

AUTO_APPLY_ENV = "CURATION_AUTO_APPLY=1"


def _script_of(cmd: str) -> str:
    for tok in cmd.split():
        if "scripts/" in tok and (tok.endswith(".py") or tok.endswith(".sh")):
            return tok.split("/")[-1]
    return ""


def transform(crontab_text: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (new_crontab, changes) where changes are (kind, description)."""
    lines = crontab_text.splitlines()
    out: list[str] = []
    changes: list[tuple[str, str]] = []

    # 1. Inject CURATION_AUTO_APPLY=1 into the watch_directives_service line.
    for ln in lines:
        if "watch_directives_service.py" in ln and "--apply" in ln:
            if AUTO_APPLY_ENV in ln:
                out.append(ln)
                continue
            # Insert before the flock guard (or before $PY when no flock).
            if "flock -n" in ln:
                new = ln.replace("flock -n", f"{AUTO_APPLY_ENV} flock -n", 1)
            else:
                new = ln.replace("$PY scripts/watch_directives_service.py",
                                 f"{AUTO_APPLY_ENV} $PY scripts/watch_directives_service.py", 1)
            out.append(new)
            changes.append(("auto-apply", "watch_directives_service: CURATION_AUTO_APPLY=1"))
        else:
            out.append(ln)

    # 2. Add missing remediation lines.
    body = "\n".join(out)
    scheduled_scripts = {_script_of(ln) for ln in out
                         if ln.strip() and not ln.strip().startswith("#")}
    for cron_line in REMEDIATION_LINES:
        if _script_of(cron_line) in scheduled_scripts:
            continue
        out.append(cron_line)
        changes.append(("add", f"remediation job: {_script_of(cron_line)}"))

    # 3. Add the self-heal watchdog line.
    if "cron_self_heal.py" not in "\n".join(out):
        out.append(SELF_HEAL_LINE)
        changes.append(("add", "self-heal watchdog: cron_self_heal.py --apply"))

    return "\n".join(out) + "\n", changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="install (backs up first)")
    args = ap.parse_args()

    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    new, changes = transform(current)

    if not changes:
        print("No changes needed — cron already contains all watchlist remediation jobs.")
        return 0

    print(f"Changes ({len(changes)}):")
    for kind, desc in changes:
        print(f"  {'+ ' if kind == 'add' else '~ '}{desc}")

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to install (timestamped backup written first).")
        return 0

    backup = PROJECT_ROOT / f"crontab_backup_pre_watchlist_remediation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    backup.write_text(current)
    r = subprocess.run(["crontab", "-"], input=new, text=True, capture_output=True)
    if r.returncode != 0:
        print(f"ERROR installing crontab: {r.stderr.strip()[:300]}")
        return 1
    print(f"\nApplied {len(changes)} changes. Backup: {backup.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
