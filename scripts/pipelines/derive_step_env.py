#!/usr/bin/env python3
"""derive_step_env.py — write each manifest step's `env` block from a crontab SNAPSHOT (names only).

2026-10-10 (operator "Yes" ~19:45 ET): the stage runner must give every step exactly the environment its cron
line had instead of sourcing $PROJ/.env wholesale. This reads a crontab text file (never .env, never a key
file) and, for each step, records:

  cron_base     the names Debian cron 3.0pl1 gives every job here (pipeline_manifest.CRON_BASE_ENV)
  crontab_vars  the names of the crontab's own NAME=value lines that PRECEDE the step's line (vixie cron
                copies the environment at parse time, so an assignment reaches only the lines below it)
  inline        NAME=... prefixes the command sets itself (kept verbatim in the command; recorded for review)
  sources       files the command sources itself (`. ./.env`, `source X`) — paths only, never contents
  wrappers      shell wrappers the command runs (they may source files themselves; verbatim in the command)

Values are not stored: the runner hands each listed name the value cron gave the runner (which runs from
the same crontab, below every assignment). The step's line is found by its `inv_id` (cron:L<n>) and must
equal `cron_line_verbatim`, or the script refuses.

    python3 scripts/pipelines/derive_step_env.py --crontab <snapshot> [--write] [manifest ...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import pipeline_manifest as pm  # noqa: E402

ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
INLINE_RE = re.compile(r"(?:^|&&\s*|;\s*|\benv\s+)((?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+)")
SOURCE_RE = re.compile(r"(?:^|[;&|(\s])(?:\.|source)\s+([^\s;&|)]+)")
WRAPPER_RE = re.compile(r"([\w./$\"{}-]*\.sh)\b")
DEFAULT = ["premarket", "after_close", "hermes_learning", "hermes_overnight"]


def crontab_assignments(text: str) -> list[tuple[int, str]]:
    out = []
    for i, ln in enumerate(text.splitlines(), 1):
        if ln.lstrip().startswith("#"):
            continue
        m = ASSIGN_RE.match(ln)
        if m and not re.match(r"^\s*\S+\s+\S+\s+\S+\s+\S+\s+\S+\s", ln.split("=", 1)[0] + " "):
            out.append((i, m.group(1)))
    return out


def env_spec(command: str, line_no: int, assigns: list[tuple[int, str]]) -> dict:
    crontab_vars: list[str] = []
    for n, name in assigns:
        if n < line_no and name not in crontab_vars:
            crontab_vars.append(name)
    inline: list[str] = []
    for grp in INLINE_RE.findall(command):
        for tok in grp.split():
            name = tok.split("=", 1)[0]
            if name not in inline:
                inline.append(name)
    sources = sorted({s.strip('"') for s in SOURCE_RE.findall(command)})
    wrappers = sorted({w.strip('"') for w in WRAPPER_RE.findall(command)})
    return {"inherit": "cron", "cron_base": list(pm.CRON_BASE_ENV), "crontab_vars": crontab_vars,
            "inline": inline, "sources": sources, "wrappers": wrappers,
            "derived_from": f"crontab line {line_no} (names only; values are the runner's cron environment)"}


def cron_env_names(line_no: int, assigns: list[tuple[int, str]]) -> list[str]:
    """What cron hands the line's shell, by name (before the command's own inline/sourced additions)."""
    names = list(pm.CRON_BASE_ENV)
    for n, name in assigns:
        if n < line_no and name not in names:
            names.append(name)
    return names


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--crontab", required=True, type=Path)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("manifests", nargs="*", default=DEFAULT)
    a = ap.parse_args(argv)
    text = a.crontab.read_text(encoding="utf-8")
    lines = text.splitlines()
    assigns = crontab_assignments(text)
    print(f"crontab assignments (name@line): {', '.join(f'{n}@L{i}' for i, n in assigns)}")
    problems = 0
    for name in a.manifests:
        path = a.root / "config" / "pipelines" / f"{name}.json"
        raw = path.read_text(encoding="utf-8")
        doc = json.loads(raw)
        for sname, stage in doc["stages"].items():
            for st in stage["steps"]:
                inv = str(st.get("inv_id") or "")
                if not inv.startswith("cron:L"):
                    print(f"REFUSED {name}/{sname}/{st['id']}: no inv_id")
                    problems += 1
                    continue
                n = int(inv[6:])
                if lines[n - 1].rstrip() != st["cron_line_verbatim"].rstrip():
                    print(f"REFUSED {name}/{sname}/{st['id']}: L{n} is not cron_line_verbatim")
                    problems += 1
                    continue
                st["env"] = env_spec(st["command"], n, assigns)
                e = st["env"]
                print(f"  {name}/{sname}/{st['id']} L{n}: vars={','.join(e['crontab_vars'])} inline={','.join(e['inline']) or '-'} "
                      f"sources={','.join(e['sources']) or '-'} wrappers={len(e['wrappers'])}")
        out = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        if a.write and not problems and out != raw:
            path.write_text(out, encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
