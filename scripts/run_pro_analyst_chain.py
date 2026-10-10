#!/usr/bin/env python3
"""run_pro_analyst_chain.py -- the cron:L437 chain as one entry point with && semantics.

The crontab line runs ``bash -c "fetch --max 250; build_read_model; monitor --send"``: the ``;``
hides a failed fetch (the read model and monitor run on stale data and the line exits with the
monitor's status). This runner keeps the same three steps in the same order but stops at the first
non-zero step, launches each with ``venv_python()`` (a release directory ships no .venv), and writes a
LaneRunReceipt@v1 for lane ``pro-analyst-fetch`` (``data/runtime/pro-analyst-fetch_last.json``) that
records every step's exit code.

- ``--dry-run`` passes ``--dry-run`` to every step (each step returns before its writes, model or
  network calls) and writes no receipt (AGENTS.md §6).
- ``--send`` is passed to the monitor only when given here. Default OFF: the monitor's Telegram send
  is a sender and stays a decision for the cron line / operator (§23.3), not for this runner.

Nothing schedules this file; the crontab line is unchanged (operator decision).

    python3 scripts/run_pro_analyst_chain.py [--max 250] [--send] [--dry-run]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))


def build_steps(max_symbols: int, send: bool, dry_run: bool) -> list[tuple[str, list[str]]]:
    steps = [
        ("pro_analyst_fetch", ["pro_analyst_fetch.py", "--max", str(max_symbols)]),
        ("build_pro_analyst_read_model", ["build_pro_analyst_read_model.py"]),
        ("pro_analyst_monitor", ["pro_analyst_monitor.py"] + (["--send"] if send else [])),
    ]
    if dry_run:
        steps = [(name, argv + ["--dry-run"]) for name, argv in steps]
    return steps


def run_chain(max_symbols: int = 250, send: bool = False, dry_run: bool = False, runner=None) -> dict:
    from lib.live_project_root import venv_python

    runner = runner or subprocess.run
    python = venv_python(ROOT)
    out: dict = {"dry_run": dry_run, "steps": [], "ok": True}
    for name, argv in build_steps(max_symbols, send, dry_run):
        t0 = time.monotonic()
        proc = runner([python, str(SCRIPTS / argv[0]), *argv[1:]], cwd=str(ROOT), check=False)
        rc = int(proc.returncode)
        out["steps"].append({"step": name, "exit": rc, "duration_s": round(time.monotonic() - t0, 1)})
        if rc != 0:
            out["ok"] = False
            out["failed_step"] = name
            break  # && semantics: a failed step stops the chain
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max", type=int, default=250, help="fetch cap (cron form: 250)")
    ap.add_argument("--send", action="store_true", help="pass --send to the monitor (Telegram; default off)")
    ap.add_argument("--dry-run", action="store_true", help="--dry-run to every step; no receipt")
    args = ap.parse_args(argv)
    started_at = datetime.now(timezone.utc).isoformat()
    result = run_chain(args.max, args.send, args.dry_run)
    print(f"[pro-analyst-chain] {result}")
    if not args.dry_run:
        from lib.lane_last_receipt import write_lane_receipt

        write_lane_receipt(
            "pro-analyst-fetch",
            script="run_pro_analyst_chain.py",
            ok=result["ok"],
            exit_code=0 if result["ok"] else 1,
            started_at=started_at,
            error=None if result["ok"] else f"step {result.get('failed_step')} failed",
            summary={"steps": result["steps"], "send": bool(args.send)},
        )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
