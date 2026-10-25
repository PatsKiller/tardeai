#!/usr/bin/env python3
"""Production guards for the design capture (AGENTS.md §28.8, §28.13; design/README.md).

    python3 scripts/lib/design_capture_guard.py window  --base URL   # exit 0 allowed, 3 refused
    python3 scripts/lib/design_capture_guard.py memory  --base URL   # exit 0 ok, 3 wait, 4 abort (or unreadable)

Rules for a capture against the live Command Center:
  - never 04:00-16:15 ET Monday to Friday (§28.8);
  - before EACH page, portfolio-server MemoryCurrent must be < 1.2 GB; at or above 1.2 GB the caller waits 30 s and
    asks again (bounded tries); at or above 1.3 GB, or when the reading is unavailable, it aborts.
A non-production base URL (fixtures, a lab port) is never refused. Clock and memory reader are injectable for tests.

AUTHORITY: READ_ONLY_ADVISORY — reads the clock and `systemctl --user show` only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MEM_OK_BELOW = 1.2e9
MEM_ABORT_AT = 1.3e9
PRODUCTION = re.compile(r"//(127\.0\.0\.1|localhost|\[::1\]):7777\b|ms01-openclaw\.")
OK, WAIT, ABORT = 0, 3, 4


def is_production(base: str) -> bool:
    return bool(PRODUCTION.search(base or ""))


def window_refusal(base: str, now: datetime | None = None) -> str | None:
    if not is_production(base):
        return None
    t = (now or datetime.now(ET)).astimezone(ET)
    minutes = t.hour * 60 + t.minute
    if t.weekday() < 5 and 4 * 60 <= minutes < 16 * 60 + 15:
        return (f"refusing production capture {t:%a %H:%M} ET (§28.8: 04:00-16:15 ET Mon-Fri); "
                "run after 16:15 ET or at the weekend, or point at a non-production host")
    return None


def server_memory() -> int | None:
    try:
        out = subprocess.run(["systemctl", "--user", "show", "portfolio-server.service", "-p", "MemoryCurrent", "--value"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return int(out) if out.isdigit() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def memory_verdict(base: str, read: Callable[[], int | None] = server_memory) -> tuple[int, int | None, str]:
    if not is_production(base):
        return OK, None, "non-production base: no memory gate"
    m = read()
    if m is None:
        return ABORT, None, "portfolio-server MemoryCurrent unavailable: refusing to load pages blind"
    if m >= MEM_ABORT_AT:
        return ABORT, m, f"MemoryCurrent {m / 1e9:.2f} GB >= 1.3 GB: abort"
    if m >= MEM_OK_BELOW:
        return WAIT, m, f"MemoryCurrent {m / 1e9:.2f} GB >= 1.2 GB: wait 30 s and recheck"
    return OK, m, f"MemoryCurrent {m / 1e9:.2f} GB < 1.2 GB"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("check", choices=("window", "memory"))
    ap.add_argument("--base", required=True)
    args = ap.parse_args(argv)
    if args.check == "window":
        why = window_refusal(args.base)
        print(json.dumps({"allowed": why is None, "reason": why}))
        return WAIT if why else OK
    code, mem, why = memory_verdict(args.base)
    print(json.dumps({"verdict": {OK: "ok", WAIT: "wait", ABORT: "abort"}[code], "memory_bytes": mem, "reason": why}))
    return code


if __name__ == "__main__":
    sys.exit(main())
