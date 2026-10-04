#!/usr/bin/env python3
"""Re-link a forked CIO event bus hash chain (operator-approved 2026-10-04).

The live bus (persistent-state data/cio/cio_events.jsonl) forked at line 2447 (2026-08-26) and two
branches were concatenated: branch A (08-26..09-13) then branch B (08-31..now), so line 5078's
prev_hash points at line 2447, not line 5077, and verify_integrity() fails there.

Repair, without losing or reordering anything:
  - every event keeps its position, event_id and content;
  - from the first broken link onward, prev_hash is set to the previous line's event_hash and
    event_hash is recomputed exactly as CIOEventBus._build_event_envelope does;
  - each re-linked record carries "rechain": {at, reason, original_prev_hash, original_event_hash}
    so the original chain is still provable from the records themselves;
  - the original file is first copied byte-for-byte to the archive (never deleted), with a sha256.

Safety: dry run by default (prints what would change). --apply takes the writers' own exclusive
flock on the bus file, re-reads under the lock (so events appended since the dry run are
included), archives, rewrites IN PLACE (same inode, so O_APPEND writers continue correctly),
fsyncs, releases, then verifies with CIOEventBus.verify_integrity().

    python3 scripts/repair_cio_event_bus_fork.py                 # dry run
    python3 scripts/repair_cio_event_bus_fork.py --apply
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_BUS = Path.home() / "trade-ai-releases" / "persistent-state" / "data" / "cio" / "cio_events.jsonl"
DEFAULT_ARCHIVE_DIR = Path.home() / "trade-ai-releases" / "archive" / "cio_event_bus_fork_20261004"
ZERO = "0" * 64


def event_hash(entry: dict) -> str:
    """Same computation as CIOEventBus._build_event_envelope (over the entry without event_hash)."""
    body = {k: v for k, v in entry.items() if k != "event_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def first_break(rows: list[dict]) -> int | None:
    """Index of the first record whose prev_hash does not match the previous event_hash."""
    prev = ZERO
    for i, r in enumerate(rows):
        if r.get("prev_hash") != prev:
            return i
        prev = r.get("event_hash", "")
    return None


def plan(rows: list[dict], *, now: str, reason: str) -> tuple[list[dict], dict]:
    """Return (new_rows, report). Pure: does not touch disk."""
    brk = first_break(rows)
    report: dict = {"records": len(rows), "first_break_line": None if brk is None else brk + 1, "rechained": 0}
    if brk is None:
        return rows, {**report, "status": "CHAIN_VALID_NOTHING_TO_DO"}
    if brk == 0:
        return rows, {**report, "status": "REFUSED_GENESIS_BROKEN"}
    parent = rows[brk].get("prev_hash")
    parents = [i + 1 for i, r in enumerate(rows[:brk]) if r.get("event_hash") == parent]
    report["fork_parent_line"] = parents[0] if parents else None
    ids = [r.get("event_id") for r in rows]
    if len(ids) != len(set(ids)):
        return rows, {**report, "status": "REFUSED_DUPLICATE_EVENT_IDS"}
    out = [dict(r) for r in rows]
    prev = out[brk - 1]["event_hash"]
    for i in range(brk, len(out)):
        r = out[i]
        original = {"original_prev_hash": r.get("prev_hash"), "original_event_hash": r.get("event_hash")}
        r.pop("event_hash", None)
        r["prev_hash"] = prev
        r["rechain"] = {"at": now, "reason": reason, **original}
        r["event_hash"] = event_hash(r)
        prev = r["event_hash"]
    report["rechained"] = len(out) - brk
    report["status"] = "PLANNED"
    report["first_rechained"] = {"line": brk + 1, "event_id": out[brk].get("event_id"), "timestamp": out[brk].get("timestamp")}
    report["last"] = {"line": len(out), "event_id": out[-1].get("event_id"), "timestamp": out[-1].get("timestamp")}
    if first_break(out) is not None:
        return rows, {**report, "status": "REFUSED_PLAN_DID_NOT_VERIFY"}
    return out, report


def _parse(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def run(bus: Path, archive_dir: Path, *, apply: bool, now: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc).isoformat()
    reason = "cio_event_bus fork (branches concatenated); operator-approved repair 2026-10-04"
    if not apply:
        rows = _parse(bus.read_text(encoding="utf-8"))
        _, report = plan(rows, now=now, reason=reason)
        return {"applied": False, **report}
    with open(bus, "r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)          # the same lock every CIOEventBus writer takes
        try:
            raw = fh.read()
            rows = _parse(raw)
            new_rows, report = plan(rows, now=now, reason=reason)
            if report["status"] != "PLANNED":
                return {"applied": False, **report}
            archive_dir.mkdir(parents=True, exist_ok=True)
            stamp = now.replace(":", "").replace("-", "")[:15]
            arch = archive_dir / f"cio_events.pre-rechain-{stamp}.jsonl"
            arch.write_text(raw, encoding="utf-8")
            sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            (archive_dir / f"{arch.name}.sha256").write_text(f"{sha}  {arch.name}\n", encoding="utf-8")
            if hashlib.sha256(arch.read_bytes()).hexdigest() != sha:
                return {"applied": False, **report, "status": "REFUSED_ARCHIVE_MISMATCH"}
            fh.seek(0)
            fh.write("".join(json.dumps(r, default=str) + "\n" for r in new_rows))
            fh.truncate()
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    from scripts.lib.cio_event_bus import CIOEventBus
    import tempfile
    ok, msg = CIOEventBus(bus_path=str(bus), cursor_path=str(Path(tempfile.gettempdir()) / "rechain-verify-cursor.jsonl")).verify_integrity()
    return {"applied": True, **report, "archive": str(arch), "archive_sha256": sha,
            "verify_ok": ok, "verify": msg}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bus", default=str(DEFAULT_BUS))
    ap.add_argument("--archive-dir", default=str(DEFAULT_ARCHIVE_DIR))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    res = run(Path(a.bus), Path(a.archive_dir), apply=a.apply)
    print(json.dumps(res, indent=2, default=str))
    return 0 if res.get("status") in ("PLANNED", "CHAIN_VALID_NOTHING_TO_DO") and res.get("verify_ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
