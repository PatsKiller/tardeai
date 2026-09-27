#!/usr/bin/env python3
"""Move the head of an append-only store into data/archive. Keep the tail.

Dry-run unless --apply. Refuses any path whose name is not on the allowlist.
Does not delete the archived bytes. Does not touch Postgres.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ALLOW = {
    "research_call_accounting.jsonl",
    "aif_memory_retrievals.jsonl",
    "cio_wake_jobs.jsonl",
}
KEEP_BYTES = 8 * 1024 * 1024


def plan(path: Path, keep_bytes: int = KEEP_BYTES) -> dict:
    if path.name not in ALLOW:
        return {"ok": False, "reason": "name not on the allowlist", "path": str(path)}
    if not path.is_file():
        return {"ok": False, "reason": "missing", "path": str(path)}
    size = path.stat().st_size
    if size <= keep_bytes:
        return {"ok": True, "action": "keep", "bytes": size, "path": str(path)}
    return {
        "ok": True,
        "action": "archive_head",
        "bytes": size,
        "keep_bytes": keep_bytes,
        "archive_bytes": size - keep_bytes,
        "path": str(path),
    }


def apply(path: Path, archive_dir: Path, keep_bytes: int = KEEP_BYTES) -> dict:
    decision = plan(path, keep_bytes)
    if not decision.get("ok") or decision.get("action") != "archive_head":
        return decision
    data = path.read_bytes()
    head, tail = data[:-keep_bytes], data[-keep_bytes:]
    # Start the tail on a line boundary so a reader does not see a half row.
    cut = tail.find(b"\n")
    if cut != -1 and cut + 1 < len(tail):
        head += tail[: cut + 1]
        tail = tail[cut + 1 :]
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = archive_dir / f"{path.stem}-{stamp}{path.suffix}"
    dest.write_bytes(head)
    path.write_bytes(tail)
    decision["archived_to"] = str(dest)
    decision["tail_bytes"] = len(tail)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive the head of an allowlisted jsonl")
    parser.add_argument("path")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--archive-dir", default="")
    args = parser.parse_args()
    path = Path(args.path)
    if not args.apply:
        print(json.dumps(plan(path)))
        return 0
    archive = Path(args.archive_dir) if args.archive_dir else path.parent / "archive"
    print(json.dumps(apply(path, archive)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
