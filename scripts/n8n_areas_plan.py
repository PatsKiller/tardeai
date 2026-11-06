#!/usr/bin/env python3
"""n8n program 0.1g: plan the folder + tag for every workflow from config/n8n_workflow_areas.json. READ-ONLY.

Reads the live workflow list (``select name, parentFolderId`` from the n8n database, read-only) and prints what
would change: every workflow must map to exactly one area, no mapped name may be absent, and the workflows still in
the root list are the ones to move. It writes nothing. Creating folders and tags is a separate, operator-approved
step (the n8n public API is disabled and has no key, AGENTS.md 23.26), taken after a fresh bundle
(scripts/n8n_backup.py --apply); this plan is its input and its acceptance query ("no workflow in the root list").

    python3 scripts/n8n_areas_plan.py            # live read-only plan; exit 1 when the mapping and the instance disagree
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
MAPPING = ROOT / "config/n8n_workflow_areas.json"
DB_CONTAINER = "m8m-n8n-db"


def load_areas(path: Path = MAPPING) -> dict[str, list[str]]:
    return json.loads(path.read_text(encoding="utf-8"))["areas"]


def plan(areas: dict[str, list[str]], live: dict[str, Optional[str]]) -> dict:
    """``live`` maps workflow name -> parentFolderId (None = root list)."""
    owner: dict[str, list[str]] = {}
    for area, names in areas.items():
        for n in names:
            owner.setdefault(n, []).append(area)
    duplicated = sorted(n for n, a in owner.items() if len(a) > 1)
    unmapped = sorted(n for n in live if n not in owner)
    missing = sorted(n for n in owner if n not in live)
    to_move = {n: owner[n][0] for n in sorted(live) if n in owner and live[n] is None}
    return {"ok": not (duplicated or unmapped or missing), "duplicated": duplicated, "unmapped": unmapped,
            "mapped_but_absent": missing, "in_root_list": len(to_move), "to_move": to_move,
            "per_area": {a: len(v) for a, v in areas.items()}}


def read_live() -> dict[str, Optional[str]]:
    sql = 'select name || E\'\\t\' || coalesce("parentFolderId", \'\') from workflow_entity order by name'
    res = subprocess.run(["docker", "exec", "-i", DB_CONTAINER, "sh", "-c",
                          'psql -v ON_ERROR_STOP=1 -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
                         input=sql + ";\n", capture_output=True, text=True, timeout=60, check=False)
    if res.returncode != 0:
        raise RuntimeError("live_read_failed")
    out: dict[str, Optional[str]] = {}
    for ln in res.stdout.splitlines():
        if ln.strip():
            name, _, folder = ln.partition("\t")
            out[name] = folder or None
    return out


def main() -> int:
    try:
        live = read_live()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    res = plan(load_areas(), live)
    print(json.dumps(res, indent=1))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
