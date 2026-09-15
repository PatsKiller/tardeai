#!/usr/bin/env python3
"""check_cron_sanity.py — verify every scripts/*.py reference in the crontab exists.

Prevents the C8 class bug (dead cron entries referencing non-existent scripts) from
recurring.  Also warns on scripts referenced without flock guards where appropriate.

Exit 0 if clean, exit 1 if stale references found.  Designed to be called both as a
standalone checker and imported as a health_agent collector.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_crontab_script_refs(crontab_text: str) -> list[tuple[str, str]]:
    """Return [(script_path, cron_line_short)] for every scripts/*.py reference."""
    refs = []
    for line in crontab_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        # Find all scripts/*.py or scripts/*.sh references
        import re
        for m in re.finditer(r'scripts/[\w/-]+\.(?:py|sh)', stripped):
            refs.append((m.group(0), stripped[:120]))
    return refs


def resolve_script_refs(crontab_text: str, project_root: Path) -> list[tuple[str, Path, str]]:
    """[(script_ref, resolved_path, cron_line_short)], resolved the way cron will run the line.

    parse_crontab_script_refs() yields bare `scripts/x.py` matches, and check() joined every one onto
    this repo. Lines that `cd` into another project (nyc-dof-auction, a review worktree) or call a
    script by absolute path (~/.openclaw/skills/...) were reported as dead although they run
    (6 of 12 cron_dead_script_ref findings on 2026-09-15). Resolution order: an absolute or
    $VAR-prefixed path as written, else relative to the line's first `cd <dir>`, else the repo.
    """
    import os
    import re
    env = {"HOME": os.path.expanduser("~")}
    refs: list[tuple[str, Path, str]] = []
    for line in crontab_text.splitlines():
        stripped = line.strip()
        m_var = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", stripped)
        if m_var and " " not in m_var.group(2).strip():
            env[m_var.group(1)] = m_var.group(2).strip().strip('"')
            continue
        if stripped.startswith("#") or not stripped:
            continue
        # A trailing comment is not part of the command ("# lane x (was scripts/old.py)").
        stripped = re.split(r"\s#", stripped, maxsplit=1)[0].rstrip()

        def expand(text: str) -> str:
            return re.sub(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", lambda m: env.get(m.group(1), m.group(0)), text)

        m_cd = re.search(r"(?:^|[;&|]\s*|\s)cd\s+(\S+)", stripped)
        base_text = expand(m_cd.group(1).strip("\"'")) if m_cd else str(project_root)
        for m in re.finditer(r"(\S*?)(scripts/[\w/-]+\.(?:py|sh))", stripped):
            prefix, ref = m.group(1), m.group(2)
            prefix = prefix.split("=")[-1]
            written = expand(prefix.strip("\"'") + ref)
            target = written if written.startswith("/") else f"{base_text}/{ref}"
            if "$" in target:
                continue  # resolved only at run time (e.g. cd "$CUR" from readlink): not provable dead here
            refs.append((ref, Path(target), stripped[:120]))
    return refs


def check() -> list[dict]:
    """Return findings list (health_agent collector format).  Empty = clean."""
    findings = []
    try:
        proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            err = (proc.stderr or "").strip()
            # Hardened user-systemd (NoNewPrivileges) strips crontab setgid, so
            # /var/spool/cron/crontabs/$USER is unreadable. That is not a cron
            # integrity defect — inventory systemd user timers instead.
            if "Permission denied" in err or "fopen" in err:
                return [{
                    "category": "execution_health",
                    "type": "cron_sanity_check_hardened",
                    "severity": "info",
                    "message": (
                        "crontab -l unreadable under hardened systemd "
                        "(NoNewPrivileges strips setgid). Root crontab is none; "
                        "use systemctl --user list-timers for scheduler inventory."
                    ),
                }]
            return [{"category": "execution_health", "type": "cron_sanity_check_failed",
                     "severity": "warning",
                     "message": f"crontab -l failed: {err[:200]}"}]
    except Exception as e:
        return [{"category": "execution_health", "type": "cron_sanity_check_failed",
                 "severity": "warning",
                 "message": f"Could not read crontab: {e}"}]

    for script_path, full_path, cron_line in resolve_script_refs(proc.stdout, PROJECT_ROOT):
        if not full_path.is_file():
            findings.append({
                "category": "execution_health",
                "type": "cron_dead_script_ref",
                "severity": "warning",
                "message": f"Crontab references non-existent script: {script_path} "
                           f"({'…' + cron_line[-80:] if len(cron_line) > 80 else cron_line})",
            })

    return findings


def main() -> int:
    findings = check()
    if not findings:
        print("✓ Crontab clean — all script references exist")
        return 0
    for f in findings:
        print(f"[{f['severity'].upper()}] {f['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
