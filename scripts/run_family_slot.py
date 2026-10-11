#!/usr/bin/env python3
"""run_family_slot.py — one parameterised entry for a same-script cron family (n8n-maturity B families).

    cd $PROJ && $PY scripts/run_family_slot.py --family <lane_id> >> logs/run_family_slot.log 2>&1

The family's slot table (scripts/lib/family_slot_jobs.py) maps the fire minute to one or more modes; each mode
is EXACTLY the crontab command it replaces (same argv, env, lock and log). Modes of one fire run in table order,
each as `/bin/bash -c <command>` with cwd = the project root and stdout+stderr appended to the mode's log, which
is what cron did with `cd <root> && <command> >> <log> 2>&1` under SHELL=/bin/bash.

  --family ID         required (except --list)
  --now ISO           local wall time instead of the clock (tests, replay): 2026-10-16T21:20
  --mode NAME         run this mode explicitly (repeatable); skips the clock (manual run, rollback check)
  --dry-run           print the plan; run nothing, write nothing (no log line, no receipt)
  --print-crontab     print the family's crontab lines and exit
  --audit-week DATE   print fires/week old vs new and predicted gate refusals for the week of DATE (a Monday)
  --list              print every family, its modes and slots
  --project-root DIR  root instead of $PWD (default: the directory cron `cd`-ed into)
  --tolerance-min N   slot attribution window (default 10)

Exit: 0 every mode exited 0 (a gate SKIP/DEFER/PEAK_SKIP exits 0, as before); the first non-zero mode exit
otherwise; 2 when the fire matches no slot (refused, never a guessed mode) or the arguments are wrong.
A real run writes LaneRunReceipt@v1 <state_root>/data/runtime/<lane_id>_last.json (ok_at only when every mode
exited 0). MBI_BEHAVIOR = 0: no broker, order, stop or send of its own; it runs the retired lines' commands.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for _p in (str(REPO), str(REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import family_slot_jobs as FSJ  # noqa: E402

BASH = "/bin/bash"  # the crontab's SHELL


def _root(arg: str | None) -> str:
    """The project root as the old line named it: the logical $PWD cron `cd`-ed into (not the resolved
    release dir), so `{root}` renders to the same string the retired line carried."""
    if arg:
        return str(arg).rstrip("/")
    pwd = os.environ.get("PWD")
    try:
        if pwd and os.path.samefile(pwd, os.getcwd()):
            return pwd.rstrip("/")
    except OSError:
        pass
    return os.getcwd()


def _parse_now(raw: str | None) -> datetime:
    if not raw:
        return datetime.now()
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=None)
    except ValueError:
        raise SystemExit(f"run_family_slot: --now must be ISO local time (2026-10-16T21:20), got {raw!r}")


def _gate_prediction(mode: FSJ.Mode, t: datetime) -> str:
    if not mode.gates:
        return "none"
    try:
        return "allow" if FSJ.mode_allowed(mode, t) else "refuse"
    except Exception as exc:  # noqa: BLE001 -- the prediction is advisory; the wrapper in the command decides
        return f"unknown:{type(exc).__name__}"


def _emit(obj: dict) -> None:
    print("[run_family_slot] " + json.dumps(obj, sort_keys=True, default=str), flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--family")
    ap.add_argument("--now")
    ap.add_argument("--mode", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--print-crontab", action="store_true")
    ap.add_argument("--audit-week")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--project-root")
    ap.add_argument("--tolerance-min", type=int, default=FSJ.DEFAULT_TOLERANCE_MIN)
    a = ap.parse_args(argv)

    if a.list:
        for f in FSJ.FAMILIES:
            print(f"{f.design_id} {f.lane_id}: lines {list(f.cron_lines)}")
            for s in f.slots:
                print(f"    slot {s.cron:24s} -> {', '.join(s.modes)}")
            for m in f.modes:
                tag = " (unscheduled)" if m.name in f.unscheduled_modes else ""
                print(f"    mode {m.name}{tag}: replaces {m.replaces_lane} [{m.old_schedule}] log {m.log}")
        return 0
    if not a.family:
        print("run_family_slot: --family is required", file=sys.stderr)
        return 2
    try:
        fam = FSJ.family(a.family)
    except KeyError as exc:
        print(f"run_family_slot: {exc.args[0]}", file=sys.stderr)
        return 2
    if a.print_crontab:
        print("\n".join(FSJ.crontab_lines(fam)))
        return 0
    if a.audit_week:
        print(json.dumps(FSJ.audit_week(fam, _parse_now(a.audit_week)), indent=1))
        return 0

    now = _parse_now(a.now)
    started = datetime.now(timezone.utc)
    if a.mode:
        try:
            modes = [fam.mode(m) for m in a.mode]
        except KeyError as exc:
            print(f"run_family_slot: {exc.args[0]}", file=sys.stderr)
            return 2
        slot_at = None
    else:
        hit = FSJ.resolve(fam, now, a.tolerance_min)
        if hit is None:
            _emit({"family": fam.lane_id, "now": now.isoformat(timespec="minutes"), "status": "REFUSED_NO_SLOT",
                   "tolerance_min": a.tolerance_min})
            print(f"run_family_slot: {fam.lane_id}: no slot within {a.tolerance_min} min of "
                  f"{now:%Y-%m-%d %H:%M} — refusing to guess a mode", file=sys.stderr)
            return 2
        slot_at, names = hit
        modes = [fam.mode(n) for n in names]

    root = _root(a.project_root)
    plan = [{"mode": m.name, "command": FSJ.render(m, root), "log": m.log,
             "gates": list(m.gates), "gate_prediction": _gate_prediction(m, slot_at or now)} for m in modes]
    head = {"family": fam.lane_id, "design_id": fam.design_id, "now": now.isoformat(timespec="minutes"),
            "slot": slot_at.isoformat(timespec="minutes") if slot_at else "explicit --mode", "root": root}

    if a.dry_run:
        _emit(dict(head, status="DRY_RUN", plan=plan))
        for p in plan:
            print(f"DRY RUN (cwd={root}): {BASH} -c {p['command']!r} >> {p['log']} 2>&1")
        try:
            from scripts.lib.lane_last_receipt import dry_run_report
            dry_run_report(fam.lane_id, {"modes": [p["mode"] for p in plan]},
                           would_write=[p["log"] for p in plan])
        except Exception as exc:  # noqa: BLE001 -- a dry run reports; it does not fail on the receipt path
            print(f"run_family_slot: receipt path unresolved ({type(exc).__name__})", file=sys.stderr)
        return 0

    results = []
    for p in plan:
        log_path = Path(root) / p["log"]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "ab", buffering=0) as log:
            rc = subprocess.run([BASH, "-c", p["command"]], cwd=root, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, env=os.environ.copy()).returncode
        results.append({"mode": p["mode"], "rc": rc, "log": p["log"], "gate_prediction": p["gate_prediction"]})
    rc = next((r["rc"] for r in results if r["rc"] != 0), 0)
    _emit(dict(head, status="DONE" if rc == 0 else "FAILED", results=results))
    try:
        from scripts.lib.lane_last_receipt import write_lane_receipt
        write_lane_receipt(fam.lane_id, ok=rc == 0, exit_code=rc, started_at=started, script=FSJ.ENTRY,
                           summary={"schema": FSJ.SCHEMA, "slot": head["slot"], "results": results})
    except Exception as exc:  # noqa: BLE001 -- the receipt never masks the run's own result
        print(f"run_family_slot: receipt failed ({type(exc).__name__})", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
