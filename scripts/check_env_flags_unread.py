#!/usr/bin/env python3
"""check_env_flags_unread.py — a control that nothing reads is not a control.

Audit finding R-06 / K-07 (2026-09-26): `TRADEAI_TIER2_DAILY_USD_CAP`, `RISK_GATE_H4_ENABLED`,
`CORRELATION_CAP` and friends were SET in host env files and unit drop-ins while no code read
them. This gate lists every env name that is *set* in a governed surface (tracked env
templates, tracked systemd units/drop-ins, optionally the host's own env files with
``--host``) and *read* by no code under ``scripts/``, ``bin/``, ``linux_launchers/``.

Names only. Values are never printed — a host env file holds secrets.

`--fail-on-new` compares against ``config/env_flags_unread_baseline.json``; every baseline row
carries the decision taken for it (IMPLEMENT / RETIRE / KEEP_DOCUMENTED) so the baseline is
the flag registry the audit asked for, not a permission slip.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "config" / "env_flags_unread_baseline.json"
CODE_DIRS = ("scripts", "bin", "linux_launchers")
CODE_SUFFIXES = {".py", ".sh", ".bash"}
_ASSIGN = re.compile(r"^\s*(?:export\s+|Environment=\"?)?([A-Z][A-Z0-9_]{2,})=", re.M)
_NAME_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
#: Names systemd/shell own; never flags.
_IGNORE = {"PATH", "HOME", "USER", "SHELL", "LANG", "TZ", "PYTHONPATH", "PYTHONUNBUFFERED", "TERM", "LC_ALL", "TMPDIR", "VIRTUAL_ENV"}


def tracked_surfaces(root: Path = ROOT) -> list[Path]:
    """Tracked env templates and systemd unit files (the governed, reviewable set)."""
    try:
        out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    picked: list[Path] = []
    for rel in out.splitlines():
        name = rel.rsplit("/", 1)[-1]
        if name.startswith(".env") or name.endswith(".env") or (
            "/systemd/" in f"/{rel}" and name.endswith((".service", ".timer", ".conf"))
        ):
            picked.append(root / rel)
    return picked


def host_surfaces(home: Path | None = None) -> list[Path]:
    """The host's own env files and unit drop-ins (names only are ever reported)."""
    home = home or Path(os.environ.get("HOME", "~")).expanduser()
    picked: list[Path] = []
    for pat in ("**/*.env", "**/*.conf", "**/*.service"):
        picked.extend(sorted((home / ".config" / "tradeai").glob(pat)))
        picked.extend(sorted((home / ".config" / "systemd" / "user").glob(pat)))
    dev_env = ROOT / ".env"
    if dev_env.is_file():
        picked.append(dev_env)
    return [p for p in picked if p.is_file() and "/archive/" not in str(p)]


def names_set_in(paths: Iterable[Path]) -> dict[str, list[str]]:
    """env NAME -> files that assign it (names only)."""
    out: dict[str, list[str]] = {}
    for p in paths:
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for m in _ASSIGN.finditer(text):
            name = m.group(1)
            if name in _IGNORE:
                continue
            out.setdefault(name, []).append(str(p))
    return out


def code_blob(root: Path = ROOT, dirs: Iterable[str] = CODE_DIRS) -> str:
    """Every code file's text, excluding tests, concatenated once (one pass, not N greps)."""
    parts: list[str] = []
    for d in dirs:
        base = root / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in CODE_SUFFIXES and p.parent.name != "bin":
                continue
            if "/tests/" in f"/{p.relative_to(root)}" or p.name.startswith("test_"):
                continue
            try:
                parts.append(p.read_text(errors="replace"))
            except OSError:
                continue
    return "\n".join(parts)


def unread_names(set_names: Iterable[str], blob: str) -> list[str]:
    """Names that the code never mentions at all (a mention is the weakest 'read'; if even
    that is missing the flag is certainly dead)."""
    present = set(_NAME_RE.findall(blob))
    return sorted(n for n in set_names if n not in present)


def load_baseline(path: Path = BASELINE) -> dict:
    if not path.exists():
        return {"schema": "EnvFlagsUnreadBaseline@v1", "flags": {}}
    return json.loads(path.read_text())


def evaluate(*, include_host: bool, root: Path = ROOT, baseline: dict | None = None) -> dict:
    surfaces = tracked_surfaces(root)
    if include_host:
        surfaces += host_surfaces()
    set_map = names_set_in(surfaces)
    unread = unread_names(set_map, code_blob(root))
    base = (baseline if baseline is not None else load_baseline()).get("flags", {})
    new = [n for n in unread if n not in base]
    resolved = sorted(n for n in base if n not in unread and (include_host or not base[n].get("host_only")))
    return {
        "schema": "EnvFlagsUnreadReport@v1",
        "surfaces_scanned": len(surfaces),
        "names_set": len(set_map),
        "unread": [{"name": n, "set_in": sorted({os.path.relpath(f, root) if f.startswith(str(root)) else f.replace(str(Path.home()), "~") for f in set_map[n]})} for n in unread],
        "new_unread": new,
        "baseline_resolved": resolved,
        "decisions": {n: base[n] for n in unread if n in base},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", action="store_true", help="also scan ~/.config/tradeai and user unit drop-ins (names only)")
    ap.add_argument("--fail-on-new", action="store_true", help="exit 1 on an unread name absent from the baseline")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rep = evaluate(include_host=args.host)
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print(f"env flags: {rep['names_set']} set across {rep['surfaces_scanned']} surfaces; {len(rep['unread'])} read by no code")
        for row in rep["unread"]:
            d = rep["decisions"].get(row["name"], {})
            tag = d.get("decision", "NEW") if isinstance(d, dict) else "NEW"
            print(f"  [{tag}] {row['name']}  <- {', '.join(row['set_in'])}")
        if rep["baseline_resolved"]:
            print(f"  baseline rows now read (remove them): {', '.join(rep['baseline_resolved'])}")
    if args.fail_on_new and rep["new_unread"]:
        print(f"FAIL: {len(rep['new_unread'])} env name(s) set but read by no code and not in the baseline: {', '.join(rep['new_unread'])}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
