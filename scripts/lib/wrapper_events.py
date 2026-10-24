"""Append a bounded operational event without following an unsafe journal path.

This is telemetry, not permission to run. Any append failure leaves the caller's
original refusal / exit untouched. Never unlocks, chmods, unlinks or clears flags.
"""
from __future__ import annotations

import argparse
import grp
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path


def _unsafe(st) -> bool:
    if st.st_mode & 0o002:
        return not bool(st.st_mode & stat.S_ISVTX)
    if st.st_mode & 0o020:
        return not (st.st_gid == os.getegid() and not grp.getgrgid(st.st_gid).gr_mem)
    return False


def append_event(path: Path, event: dict) -> bool:
    """One append; refused symlink/hardlink/foreign-owner/unsafe/immutable sinks stay untouched."""
    try:
        path = Path(os.path.abspath(path))
        for parent in reversed(path.parents):
            st = parent.lstat()
            if not stat.S_ISDIR(st.st_mode) or _unsafe(st):
                return False
        before = None
        try:
            before = path.lstat()
        except FileNotFoundError:
            pass
        if before and (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_nlink != 1):
            return False
        payload = dict(event)
        payload.setdefault("ts", datetime.now(timezone.utc).isoformat())
        raw = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        if len(raw) > 4096:
            return False
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            after = os.fstat(fd)
            if not stat.S_ISREG(after.st_mode) or after.st_uid != os.geteuid() or after.st_nlink != 1:
                return False
            if before and (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                return False
            if os.write(fd, raw) != len(raw):
                return False
            os.fsync(fd)
            return True
        finally:
            os.close(fd)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--wrapper", required=True)
    parser.add_argument("--event", required=True, choices=["started", "completed", "refused"])
    parser.add_argument("--reason", default="wrapper_refused")
    parser.add_argument("--mode", default="business", choices=["business", "dry_run", "preflight"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--stderr-fallback", action="store_true", help="report the same refused outcome on existing stderr; never repair the sink")
    args = parser.parse_args()
    event = {"event_type": args.event, "job_id": args.job_id, "component": args.job_id,
             "wrapper": args.wrapper, "reason": args.reason, "mode": args.mode,
             "run_id": args.run_id, "event_id": f"{args.wrapper}:{args.run_id}:{args.event}"}
    if args.exit_code is not None:
        event["exit_code"] = args.exit_code
    if append_event(args.journal, event):
        return 0
    if args.stderr_fallback and args.event == "refused":
        event.update(ts=datetime.now(timezone.utc).isoformat(), journal_fallback="stderr")
        print(json.dumps(event, separators=(",", ":")), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
