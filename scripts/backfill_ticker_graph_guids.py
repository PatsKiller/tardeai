#!/usr/bin/env python3
"""Backfill deterministic GUID lineage into legacy ticker graph rows.

Default mode is a report-only dry run.  ``--apply`` writes an atomic replacement
and keeps a timestamped JSONL backup beside the source file.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from scripts.lib.ticker_knowledge_graph import graph_path, upgrade_record_guids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    path = graph_path(args.root)
    if not path.exists():
        print(json.dumps({"ok": False, "error": "graph_missing", "path": str(path)}))
        return 1
    raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows = []
    changed = 0
    for line in raw:
        try:
            original = json.loads(line)
            upgraded = upgrade_record_guids(original)
        except json.JSONDecodeError:
            continue
        rows.append(upgraded)
        if upgraded != original:
            changed += 1
    result = {"ok": True, "path": str(path), "rows": len(rows), "rows_needing_guid_backfill": changed, "applied": False}
    if args.apply and changed:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name(f"{path.name}.pre-guid-{stamp}.bak")
        temp = path.with_suffix(path.suffix + ".guid.tmp")
        shutil.copy2(path, backup)
        temp.write_text("".join(json.dumps(row, sort_keys=True, default=str) + "\n" for row in rows), encoding="utf-8")
        temp.replace(path)
        result.update({"applied": True, "backup": str(backup)})
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
