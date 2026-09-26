#!/usr/bin/env python3
"""check_unit_env_files.py — every EnvironmentFile= a user unit names must exist.

Audit 2026-09-26 (K-04): `tradeai-active-trader-motion.service` loads
`EnvironmentFile=-/etc/tardeai/active-trader-motion.env` (typo; the directory
does not exist) and `tradeai-advisory-shadow-session.service` names a missing
`~/.config/tradeai/advisory-shadow.env`. The leading `-` makes systemd skip a
missing file silently, so both services run on defaults and nothing says so.

Pure parser + injectable `exists` so tests never touch the host. Exit 0 clean,
1 when a referenced file is missing. Health-agent collector format.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Callable, Iterable

NO_CONSUMER_REASON = (
    "operator/health linter; stdout and the health_agent collector are the consumers"
)
SCHEMA = "UnitEnvFileCheck@v1"
UNIT_DIR = Path(os.environ.get("TRADEAI_USER_UNIT_DIR", str(Path.home() / ".config/systemd/user")))
_ENV_RE = re.compile(r"^\s*EnvironmentFile\s*=\s*(-?)(\S+)\s*$")


def expand_specifier(path: str, *, home: str | None = None) -> str:
    """systemd %h / %u / ~ expansion for user units."""
    h = home or os.path.expanduser("~")
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    out = (path.replace("%h", h).replace("%t", runtime).replace("%T", "/tmp")
           .replace("%u", os.environ.get("USER", "")).replace("%U", str(os.getuid())))
    if out.startswith("~"):
        out = h + out[1:]
    return out


def env_files_in(text: str) -> list[tuple[bool, str]]:
    """[(optional, path)] for each EnvironmentFile= line in a unit or drop-in."""
    out = []
    for line in text.splitlines():
        m = _ENV_RE.match(line)
        if m:
            out.append((m.group(1) == "-", m.group(2)))
    return out


def lint_units(units: Iterable[tuple[str, str]], *, exists: Callable[[str], bool] = os.path.exists,
               home: str | None = None) -> list[dict]:
    """units: iterable of (unit_name_or_path, text). Returns findings."""
    findings = []
    for name, text in units:
        for optional, raw in env_files_in(text):
            path = expand_specifier(raw, home=home)
            if exists(path):
                continue
            findings.append({
                "category": "execution_health",
                "type": "unit_env_file_missing",
                "severity": "warning" if optional else "critical",
                "unit": str(name),
                "path": path,
                "message": (f"{name}: EnvironmentFile {raw} does not exist"
                            + (" (leading '-': systemd skips it SILENTLY, service runs on defaults)"
                               if optional else " (service will fail to start)")),
            })
    return findings


def host_units(unit_dir: Path = UNIT_DIR) -> list[tuple[str, str]]:
    rows = []
    if not unit_dir.is_dir():
        return rows
    for p in sorted(unit_dir.glob("*.service")):
        try:
            rows.append((p.name, p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    for d in sorted(unit_dir.glob("*.service.d")):
        for p in sorted(d.glob("*.conf")):
            try:
                rows.append((f"{d.name}/{p.name}", p.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return rows


def check() -> list[dict]:
    """health_agent collector entry point."""
    return lint_units(host_units())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--unit-dir", default=None)
    args = ap.parse_args()
    findings = lint_units(host_units(Path(args.unit_dir) if args.unit_dir else UNIT_DIR))
    if args.json:
        print(json.dumps({"schema": SCHEMA, "findings": findings, "ok": not findings}, indent=2))
    elif not findings:
        print("✓ every EnvironmentFile named by a user unit exists")
    else:
        for f in findings:
            print(f"[{f['severity'].upper()}] {f['message']}")
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
