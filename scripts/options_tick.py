#!/usr/bin/env python3
"""options_tick.py — one cron line for the three options cadence jobs (cron consolidation tranche C, rank 13).

Today three crontab lines fire nine times an hour on the same 15-minute rhythm:

    7,22,37,52 * * * *  flock -n /tmp/options_thesis_lifecycle.lock  bash -c 'set -a; . /run/user/$(id -u)/tradeai/env; set +a; M2_DSN="$M2_AGENT_DSN" $PY scripts/options_thesis_lifecycle.py --apply'
    9,24,39,54 * * * *  flock -n /tmp/options_memory_projector.lock  bash -c 'set -a; . /run/user/$(id -u)/tradeai/env; set +a; M2_DSN="$M2_AGENT_DSN" TRADEAI_M2_PRODUCTION_MEMORY_AUTHORIZED=1 $PY scripts/options_memory_projector.py --apply'
    3 * * * *           flock -n /tmp/options_runtime_export.lock    $PY scripts/export_options_runtime_snapshot.py --apply

This runner replaces them with ONE line on the lifecycle's own minutes and runs, in order:

    1. lifecycle   every tick
    2. projector   every tick, after the lifecycle (today it is "2 min after each lifecycle run")
    3. export      on the tick whose 15-minute window contains :03 — the :52 tick, which is the
                   last tick before the :05 Drive sync the export feeds ("2 min before the sync")

Every step is executed EXACTLY as its crontab line executes it: the same ``flock -n <lock>`` on the
same lock path (the lifecycle inherits an ancestor flock through /proc/self/fd — see
acquire_lifecycle_lock in scripts/options_thesis_lifecycle.py — so the lock MUST stay the parent of
the python process, which is why each step is a ``flock … bash -c`` child and not an in-process
call), the same env sourcing, the same argv, and stdout+stderr appended to the same per-step log, so
the three ACTIVE lanes' output signals (file_mtime on those logs) keep proving the steps ran during
the cutover. The only additions: ``flock -E 75`` so a held lock is distinguishable from a failure,
continue-on-error, an optional per-step timeout (none by default — the crontab lines have none),
and a receipt.

    python3 scripts/options_tick.py                      # plan only: which steps are due this tick
    python3 scripts/options_tick.py --apply              # run the due steps in order
    python3 scripts/options_tick.py --apply --tick-minute 52   # force the export-due tick (manual)
    python3 scripts/options_tick.py --manifest steps.json --apply --root /tmp/x   # hermetic (tests)

Proposed crontab line (NOT installed by this PR; see docs/implementation/n8n-parallel/proposals/cron-tranche-c-lowrisk.md):

    7,22,37,52 * * * * cd $PROJ && $PY scripts/options_tick.py --apply >> logs/options_tick.log 2>&1  # TRADEAI_LANE options-tick

Receipt: $TRADEAI_STATE_ROOT/data/runtime/options_tick_last.json (OptionsTickReceipt@v1).
Env:     PY (the interpreter the step shells expand as $PY; default sys.executable), TRADEAI_STATE_ROOT.

AUTHORITY: READ_ONLY_ADVISORY. This script sequences existing jobs; it reads no broker, no secret value
and writes nothing but its receipt and the steps' own logs. Lane registry: options-tick (NEVER_SCHEDULED).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.atomic_json_store import atomic_write_json  # noqa: E402

SCHEMA = "OptionsTickReceipt@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
LANE = "options-tick"
NO_CONSUMER_REASON = (
    "Cron consolidation tranche C (rank 13): the one-line replacement for the options-thesis-lifecycle, "
    "options-memory-projector and options-runtime-export crontab lines. Proposal only -- not installed; "
    "the operator installs the single line under a cron grant and the three old lines are deleted after two "
    "observed cycles. Its receipt is read by the lane monitor (output_signal file_mtime)."
)

TICK_LOCK = "/tmp/options_tick.lock"
LOCK_CONFLICT_RC = 75          # flock -E 75: EX_TEMPFAIL, "lock held", never a step failure
DEFAULT_PERIOD_MIN = 15
DEFAULT_TICK_MINUTES = (7, 22, 37, 52)

# Exactly the crontab lines' command bodies. $PY is expanded by bash from the environment (cron sets
# PY=... at the top of the crontab; this runner exports it for the child when it is unset).
_SOURCE_ENV = "set -a; . /run/user/$(id -u)/tradeai/env; set +a; "
DEFAULT_STEPS: list[dict[str, Any]] = [
    {
        "name": "lifecycle",
        "lane": "options-thesis-lifecycle",
        "lock": "/tmp/options_thesis_lifecycle.lock",
        "shell": _SOURCE_ENV + 'M2_DSN="$M2_AGENT_DSN" $PY scripts/options_thesis_lifecycle.py --apply',
        "log": "logs/options_thesis_lifecycle.log",
        "every_tick": True,
        "today": "7,22,37,52 * * * *",
    },
    {
        "name": "projector",
        "lane": "options-memory-projector",
        "lock": "/tmp/options_memory_projector.lock",
        "shell": _SOURCE_ENV + 'M2_DSN="$M2_AGENT_DSN" TRADEAI_M2_PRODUCTION_MEMORY_AUTHORIZED=1 '
                               '$PY scripts/options_memory_projector.py --apply',
        "log": "logs/options_memory_projector.log",
        "every_tick": True,
        "today": "9,24,39,54 * * * *",
    },
    {
        "name": "export",
        "lane": "options-runtime-export",
        "lock": "/tmp/options_runtime_export.lock",
        "shell": "$PY scripts/export_options_runtime_snapshot.py --apply",
        "log": "logs/options_runtime_export.log",
        "every_tick": False,
        "due_minute": 3,
        "today": "3 * * * *",
    },
]


def state_root(env: Optional[dict] = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def served_sha() -> Optional[str]:
    explicit = os.environ.get("TRADEAI_SERVED_SHA")
    if explicit:
        return explicit.strip()
    try:
        return (Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT" / "GIT_SHA").read_text().strip()
    except OSError:
        return None


def export_due(tick_minute: int, due_minute: int = 3, period_min: int = DEFAULT_PERIOD_MIN) -> bool:
    """True when the window [tick_minute, tick_minute + period) — wrapping at :60 — contains due_minute.

    With ticks at :07/:22/:37/:52 and due_minute 3 only the :52 tick qualifies ((3-52) % 60 = 11 < 15).
    """
    return (int(due_minute) - int(tick_minute)) % 60 < int(period_min)


def plan(steps: list[dict[str, Any]], tick_minute: int, period_min: int, force_export: bool = False) -> list[dict[str, Any]]:
    """Which steps are due on this tick, in table order. Pure; no side effects."""
    out = []
    for s in steps:
        if s.get("every_tick"):
            due, why = True, "every tick"
        elif force_export:
            due, why = True, "forced"
        else:
            due = export_due(tick_minute, int(s.get("due_minute", 3)), period_min)
            why = (f"window [{tick_minute:02d}, +{period_min}) contains :{int(s.get('due_minute', 3)):02d}"
                   if due else f"window [{tick_minute:02d}, +{period_min}) does not contain :{int(s.get('due_minute', 3)):02d}")
        out.append({"name": s["name"], "lane": s.get("lane"), "due": due, "why": why, "lock": s["lock"],
                    "log": s["log"], "today": s.get("today"), "cmd": step_argv(s)})
    return out


def step_argv(step: dict[str, Any]) -> list[str]:
    """The crontab line's own shape: flock -n <lock> bash -c '<body>' (+ -E 75 so a held lock is typed)."""
    if step.get("argv"):
        return ["flock", "-n", "-E", str(LOCK_CONFLICT_RC), step["lock"], *step["argv"]]
    return ["flock", "-n", "-E", str(LOCK_CONFLICT_RC), step["lock"], "bash", "-c", step["shell"]]


def run_step(step: dict[str, Any], root: Path, env: dict[str, str], timeout_s: Optional[float]) -> dict[str, Any]:
    log_path = root / step["log"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    row: dict[str, Any] = {"name": step["name"], "lane": step.get("lane"), "lock": step["lock"],
                           "log": str(log_path), "started_at": started.isoformat(), "rc": None,
                           "outcome": None, "duration_s": None}
    try:
        with log_path.open("ab") as fh:
            fh.write(f"[{started.isoformat()}] options_tick step={step['name']} start\n".encode())
            fh.flush()
            try:
                cp = subprocess.run(step_argv(step), cwd=str(root), env=env, stdout=fh, stderr=subprocess.STDOUT,
                                    timeout=timeout_s or None)
                row["rc"] = cp.returncode
            except subprocess.TimeoutExpired:
                row["rc"] = None
                row["outcome"] = "TIMEOUT"
                fh.write(f"[{datetime.now(timezone.utc).isoformat()}] options_tick step={step['name']} TIMEOUT after {timeout_s}s\n".encode())
    except OSError as exc:                       # log unwritable, flock missing, ...
        row["rc"] = None
        row["outcome"] = "SPAWN_FAILED"
        row["error"] = f"{type(exc).__name__}: {exc}"
    row["duration_s"] = round(time.monotonic() - t0, 3)
    if row["outcome"] is None:
        if row["rc"] == 0:
            row["outcome"] = "RAN"
        elif row["rc"] == LOCK_CONFLICT_RC:
            row["outcome"] = "LOCK_HELD"          # another run (manual or the old cron line) holds the step lock
        else:
            row["outcome"] = "FAILED"
    return row


def load_manifest(path: Optional[str]) -> list[dict[str, Any]]:
    if not path:
        return [dict(s) for s in DEFAULT_STEPS]
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    steps = data.get("steps") if isinstance(data, dict) else data
    out = []
    for s in steps or []:
        if not s.get("name") or not s.get("lock") or not s.get("log") or not (s.get("shell") or s.get("argv")):
            raise SystemExit(f"manifest step needs name, lock, log and shell|argv: {s}")
        out.append(dict(s))
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="One tick of the options cadence: lifecycle -> projector -> (export)")
    ap.add_argument("--apply", action="store_true", help="run the due steps (default: print the plan only)")
    ap.add_argument("--tick-minute", type=int, default=None, help="minute of this tick (default: now.minute)")
    ap.add_argument("--period-min", type=int, default=DEFAULT_PERIOD_MIN, help="tick period in minutes (default 15)")
    ap.add_argument("--force-export", action="store_true", help="treat the export step as due on this tick")
    ap.add_argument("--step-timeout-s", type=float, default=0.0,
                    help="per-step wall clock; 0 = none, which is what the crontab lines have today")
    ap.add_argument("--manifest", default=None, help="JSON {steps:[{name,lock,log,shell|argv,every_tick,due_minute}]} replacing the built-in table")
    ap.add_argument("--root", default=None, help="working directory for the steps (default: this checkout)")
    ap.add_argument("--tick-lock", default=TICK_LOCK, help="this runner's own non-blocking lock")
    ap.add_argument("--receipt", default=None, help="receipt path (default: $TRADEAI_STATE_ROOT/data/runtime/options_tick_last.json)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else ROOT
    steps = load_manifest(args.manifest)
    now = datetime.now(timezone.utc)
    tick_minute = args.tick_minute if args.tick_minute is not None else datetime.now().minute
    the_plan = plan(steps, tick_minute, args.period_min, args.force_export)
    receipt_path = Path(args.receipt) if args.receipt else state_root() / "data" / "runtime" / "options_tick_last.json"

    if not args.apply:
        print(json.dumps({"schema": SCHEMA, "mode": "plan", "tick_minute": tick_minute, "period_min": args.period_min,
                          "root": str(root), "receipt_would_be": str(receipt_path), "steps": the_plan}, indent=1))
        return 0

    env = dict(os.environ)
    env.setdefault("PY", sys.executable)

    receipt: dict[str, Any] = {"schema": SCHEMA, "authority": AUTHORITY, "lane": LANE, "mode": "apply",
                               "as_of": now.isoformat(), "tick_minute": tick_minute, "period_min": args.period_min,
                               "served_sha": served_sha(), "root": str(root), "tick_lock": args.tick_lock,
                               "step_timeout_s": args.step_timeout_s or None, "steps": [], "ok": False}

    # The runner's own lock: a tick that overlaps the previous tick is skipped and SAYS so. The step
    # locks are not taken here -- each step's flock child takes its own, exactly as the crontab lines do.
    lock_fh = open(args.tick_lock, "a+")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        receipt["outcome"] = "SKIPPED_TICK_LOCK_HELD"
        receipt["steps"] = [{**p, "outcome": "NOT_RUN"} for p in the_plan]
        atomic_write_json(receipt_path, receipt)
        print(json.dumps({"mode": "apply", "outcome": receipt["outcome"], "tick_lock": args.tick_lock}))
        return 0

    try:
        for s, p in zip(steps, the_plan):
            if not p["due"]:
                receipt["steps"].append({"name": s["name"], "lane": s.get("lane"), "outcome": "NOT_DUE", "why": p["why"]})
                continue
            receipt["steps"].append(run_step(s, root, env, args.step_timeout_s or None))   # continue on error
    finally:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
        finally:
            lock_fh.close()

    ran = [r for r in receipt["steps"] if r.get("outcome") not in ("NOT_DUE",)]
    receipt["ok"] = all(r.get("outcome") in ("RAN", "LOCK_HELD") for r in ran) and bool(ran)
    receipt["outcome"] = "OK" if receipt["ok"] else "STEP_FAILED"
    receipt["ended_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(receipt_path, receipt)
    receipt["receipt_path"] = str(receipt_path)
    print(json.dumps({"mode": "apply", "outcome": receipt["outcome"], "tick_minute": tick_minute,
                      "steps": [(r["name"], r.get("outcome"), r.get("rc"), r.get("duration_s")) for r in receipt["steps"]],
                      "receipt": str(receipt_path)}, default=str))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
