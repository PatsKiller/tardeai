#!/usr/bin/env python3
"""unit_run_snapshot.py — per-run evidence for systemd jobs (JobsN8n mockup ask 4, operator decision 2026-11-06).

/api/v2/jobs-history has no per-run record for systemd-scheduled jobs: their runs live only in the systemd
journal, which the page does not read. This lane reads each registry systemd row's unit state with
``systemctl show`` (read-only; user scope first, then system scope) and records every newly finished run
once, keyed by the unit's InvocationID:

    <TRADEAI_STATE_ROOT>/data/runtime/unit_runs.jsonl      one UnitRun@v1 line per finished run
    <TRADEAI_STATE_ROOT>/data/runtime/unit_run_snapshot_state.json   last InvocationID seen per unit

``--dry-run`` (default) reads the units and prints what would be recorded; nothing is written.
``--apply`` appends the new runs, replaces the state file and writes a LaneRunReceipt v2.

Limits (named, not hidden): a 15-minute snapshot sees only the LAST run of each unit, so a timer that fires
more often than the snapshot records one run per snapshot; a unit that is running at snapshot time is
recorded on a later snapshot once it has finished. Never starts, stops or reloads a unit.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANE_ID = "unit-run-snapshot"
SCHEMA = "UnitRun@v1"
RUNS_NAME = "unit_runs.jsonl"
STATE_NAME = "unit_run_snapshot_state.json"
UNIT_RE = re.compile(r"^([A-Za-z0-9@_.:-]+\.(?:timer|service))\b")
SERVICE_PROPS = ("Id", "LoadState", "ActiveState", "SubState", "Result", "InvocationID", "NRestarts",
                 "ExecMainStartTimestamp", "ExecMainExitTimestamp", "ExecMainStatus")
TIMER_PROPS = ("Id", "LoadState", "Unit")
SHOW_TIMEOUT_S = 30


def unit_of(lane: dict) -> str | None:
    """The unit named at the start of a systemd row's scheduler.expression, else None."""
    scheduler = lane.get("scheduler") or {}
    if scheduler.get("kind") != "systemd":
        return None
    match = UNIT_RE.match(str(scheduler.get("expression") or "").strip())
    return match.group(1) if match else None


def registry_units(registry: dict) -> dict[str, str]:
    """{unit: lane_id} for every non-retired systemd lane that names a unit."""
    out = {}
    for lane in registry.get("lanes") or []:
        if lane.get("state") == "RETIRED":
            continue
        unit = unit_of(lane)
        if unit:
            out.setdefault(unit, str(lane.get("lane_id") or lane.get("id")))
    return out


def parse_show(text: str) -> list[dict]:
    """``systemctl show`` output for several units -> one dict per unit (blocks are blank-line separated)."""
    blocks, current = [], {}
    for line in text.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = {}
            continue
        key, _, value = line.partition("=")
        current[key] = value
    if current:
        blocks.append(current)
    return blocks


def systemctl_show(units: list[str], props: tuple[str, ...], scope: str) -> dict[str, dict]:
    """Read-only ``systemctl [--user] show`` for ``units``; {Id: properties}. Failure -> {}."""
    if not units:
        return {}
    cmd = ["systemctl"] + (["--user"] if scope == "user" else []) + [
        "show", "--no-pager", "--timestamp=unix", "-p", ",".join(props), *units]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=SHOW_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return {}
    return {b.get("Id"): b for b in parse_show(proc.stdout) if b.get("Id")}


def _unix(value) -> datetime | None:
    text = str(value or "").strip()
    if not text.startswith("@"):
        return None
    try:
        seconds = int(text[1:])
    except ValueError:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc) if seconds > 0 else None


def run_record(lane_id: str, unit: str, service: dict, scope: str, now: datetime) -> dict | None:
    """A finished run from one service's properties, else None (never ran, running, or no exit yet)."""
    started, finished = _unix(service.get("ExecMainStartTimestamp")), _unix(service.get("ExecMainExitTimestamp"))
    if started is None or finished is None or finished < started:
        return None
    if service.get("ActiveState") in {"activating", "reloading"} or service.get("SubState") == "running":
        return None
    try:
        status = int(service.get("ExecMainStatus"))
    except (TypeError, ValueError):
        status = None
    result = service.get("Result") or None
    return {"schema": SCHEMA, "lane_id": lane_id, "unit": unit, "service": service.get("Id"), "scope": scope,
            "invocation_id": service.get("InvocationID") or None,
            "started_at": started.isoformat(), "finished_at": finished.isoformat(),
            "exit_status": status, "result": result,
            "succeeded": result == "success" and status in (0, None),
            "restarts": int(service["NRestarts"]) if str(service.get("NRestarts") or "").isdigit() else None,
            "observed_at": now.isoformat()}


def collect(units: dict[str, str], *, show=None, now: datetime | None = None) -> dict:
    """Read every unit (user scope, then system scope for the not-found ones). Returns runs + unread units."""
    show = show or systemctl_show
    now = now or datetime.now(timezone.utc)
    found: dict[str, tuple[str, dict]] = {}  # unit -> (scope, service properties)
    pending = list(units)
    for scope in ("user", "system"):
        if not pending:
            break
        timer_props = show([u for u in pending if u.endswith(".timer")], TIMER_PROPS, scope)
        service_of, still = {}, []
        for unit in pending:
            if unit.endswith(".timer"):
                props = timer_props.get(unit) or {}
                if props.get("LoadState") != "loaded":
                    still.append(unit)
                    continue
                service_of[unit] = props.get("Unit") or unit[:-len(".timer")] + ".service"
            else:
                service_of[unit] = unit
        services = show(sorted(set(service_of.values())), SERVICE_PROPS, scope)
        for unit, svc in service_of.items():
            props = services.get(svc) or {}
            if props.get("LoadState") == "loaded":
                found[unit] = (scope, props)
            else:
                still.append(unit)
        pending = still
    runs = [r for unit, (scope, props) in found.items() if (r := run_record(units[unit], unit, props, scope, now))]
    return {"observed_at": now.isoformat(), "units": len(units), "read": len(found), "runs": runs,
            "unread": {u: "unit not loaded in the user or system manager" for u in pending}}


def new_runs(runs: list[dict], state: dict) -> list[dict]:
    """Runs not recorded before: keyed by InvocationID (start time when systemd gave none)."""
    seen = state.get("last") or {}
    return [r for r in runs if seen.get(r["unit"]) != (r["invocation_id"] or r["started_at"])]


def _runtime_dir() -> Path:
    for p in (str(ROOT / "scripts"), str(ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from lib import lane_last_receipt
    return lane_last_receipt.runtime_dir()


def _read_state(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def record(runs: list[dict], state: dict, runtime: Path, now: datetime) -> tuple[Path, Path]:
    runtime.mkdir(parents=True, exist_ok=True)
    runs_path, state_path = runtime / RUNS_NAME, runtime / STATE_NAME
    if runs:
        with runs_path.open("a", encoding="utf-8") as stream:
            for r in runs:
                stream.write(json.dumps(r, sort_keys=True) + "\n")
    last = dict(state.get("last") or {})
    for r in runs:
        last[r["unit"]] = r["invocation_id"] or r["started_at"]
    tmp = state_path.with_name(state_path.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps({"schema": "UnitRunSnapshotState@v1", "updated_at": now.isoformat(), "last": last},
                              sort_keys=True), encoding="utf-8")
    os.replace(tmp, state_path)
    return runs_path, state_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Snapshot systemd unit runs for /api/v2/jobs-history", allow_abbrev=False)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="read units and print; write nothing (default)")
    mode.add_argument("--apply", action="store_true", help="append new runs + state + lane receipt")
    ap.add_argument("--registry", default=str(ROOT / "config" / "lane_registry.json"))
    args = ap.parse_args(argv)
    runtime = _runtime_dir()
    from lib import lane_last_receipt as receipts
    started = receipts.now_iso()
    try:
        registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if args.apply:
            receipts.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                        script="unit_run_snapshot.py", error=f"{type(exc).__name__}: {exc}")
        print(f"[unit-run-snapshot] FAILED: registry unreadable ({type(exc).__name__})", file=sys.stderr)
        return 1
    now = datetime.now(timezone.utc)
    snap = collect(registry_units(registry), now=now)
    state = _read_state(runtime / STATE_NAME)
    fresh = new_runs(snap["runs"], state)
    failed = sum(1 for r in fresh if not r["succeeded"])
    line = (f"{snap['units']} units, {snap['read']} read, {len(snap['unread'])} unread, {len(snap['runs'])} finished "
            f"runs seen, {len(fresh)} new ({failed} not successful)")
    if not args.apply:
        print(f"DRY-RUN {LANE_ID}: {line}; would append to {runtime / RUNS_NAME}; nothing written")
        for r in fresh[:5]:
            print(f"  would record {r['unit']} {r['started_at']} -> {r['finished_at']} result={r['result']} "
                  f"exit={r['exit_status']}")
        return 0
    ok = snap["read"] > 0
    runs_path, state_path = record(fresh, state, runtime, now) if ok else (runtime / RUNS_NAME, runtime / STATE_NAME)
    receipts.write_lane_receipt(LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=started,
                                script="unit_run_snapshot.py",
                                summary={"units": snap["units"], "read": snap["read"], "new_runs": len(fresh),
                                         "not_successful": failed, "unread": len(snap["unread"])},
                                produced_count=len(fresh) if ok else 0, attempted_count=snap["units"],
                                skipped_reasons={"unread": len(snap["unread"])} if snap["unread"] else None,
                                output_evidence=[{"kind": "file", "path": str(runs_path)},
                                                 {"kind": "file", "path": str(state_path)}],
                                # Reason codes match the health contract: nothing_new is the allowed empty run.
                                empty_reason=None if ok and fresh else
                                ("dependency_unavailable" if not ok else "nothing_new"))
    print(f"[unit-run-snapshot] {line}; appended to {runs_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
