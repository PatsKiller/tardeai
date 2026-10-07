#!/usr/bin/env python3
"""n8n_export_workflows.py — export the lab n8n workflows to versioned JSON.

n8n Community has no Git source control (Business/Enterprise feature), so the repo
copy under docs/implementation/n8n-parallel/workflows/ is the history. Reads the lab
database through `docker exec` (no host port, no credential on this side); writes one
file per workflow plus an index. Pinned data and credential references are stripped
(there are none today; the strip is a guard, not a cleanup).

    python3 scripts/n8n_export_workflows.py --dry-run
    python3 scripts/n8n_export_workflows.py --write [--out DIR]

AUTHORITY: READ_ONLY_ADVISORY. Lab only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "docs" / "implementation" / "n8n-parallel" / "workflows"
SQL = ("select json_agg(json_build_object('id', id, 'name', name, 'active', active, "
       "'createdAt', \"createdAt\", 'updatedAt', \"updatedAt\", 'nodes', nodes, "
       "'connections', connections, 'settings', settings, 'versionId', \"versionId\")) "
       "from workflow_entity")


def read_workflows(container: str) -> list[dict]:
    cmd = ["docker", "exec", container, "sh", "-c",
           'psql -tA -U "$POSTGRES_USER" "$POSTGRES_DB" -c "' + SQL.replace('"', '\\"') + '"']
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    return json.loads(out) if out else []


def strip(wf: dict) -> dict:
    wf = dict(wf)
    wf.pop("pinData", None)
    for node in wf.get("nodes") or []:
        node.pop("credentials", None)
        node.pop("webhookId", None)
    return wf


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workflow"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", default="m8m-n8n-db")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--write", action="store_true")
    a = ap.parse_args()
    try:
        rows = read_workflows(a.container)
    except Exception as e:  # cannot run != pass
        print(f"n8n_export_workflows CANNOT RUN: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    out = Path(a.out)
    index = {"schema": "N8nWorkflowExport@v1", "as_of": datetime.now(timezone.utc).isoformat(),
             "container": a.container, "count": len(rows), "workflows": []}
    for wf in rows:
        s = strip(wf)
        types = sorted({n.get("type", "") for n in s.get("nodes") or []})
        fn = f"{slug(wf['name'])}.json"
        index["workflows"].append({"file": fn, "id": wf["id"], "name": wf["name"], "active": wf["active"],
                                   "node_types": types, "updatedAt": wf.get("updatedAt")})
        if a.write:
            out.mkdir(parents=True, exist_ok=True)
            (out / fn).write_text(json.dumps(s, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if a.write:
        (out / "INDEX.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"mode": "write" if a.write else "dry-run", "count": len(rows),
                      "files": [w["file"] for w in index["workflows"]], "out": str(out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
