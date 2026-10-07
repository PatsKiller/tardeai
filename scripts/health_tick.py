#!/usr/bin/env python3
"""health_tick.py — one 5-minute tick that runs the health/monitor cadence table.

Cron consolidation RANK 3 (2026-10-07). Seventeen independent crontab lines
(system_health_agent, opend_health, cio_bridge_watchdog, health_agent,
cron_self_heal, siem_critical_notify, log_error_scraper, system_freshness_monitor,
portfolio_live_monitor, freshness_watchdog_heartbeat, pipeline_liveness_report,
pipeline_watchdog, pipeline_freshness_monitor, pipeline_freshness_slo,
check_llm_provider_health, symbol_news_curation_monitor, system_health_alerts)
become ONE systemd timer (`tradeai-health-tick.timer`, `OnCalendar=*:0/5`) that
runs this script. The table `config/health_tick_steps.json` (HealthTickSteps@v1)
carries each line's exact command, cadence, minute phase, hour/weekday window,
lock path, timeout, log target and the `market_day_gate.sh` wrapper.

What one tick does
  1. Snap "now" to the 5-minute grid (floor), in the host's local time — cron's
     clock. A step is due when the tick minute matches its cron-equivalent
     schedule (see `step_is_due`).
  2. Run the due steps sequentially (or `max_parallel` at a time), each
       - under the SAME /tmp flock the cron line used (flock(2) on the same
         path, non-blocking: a still-running earlier instance ⇒ lock_skipped),
       - under a hard timeout (SIGTERM to the process group, SIGKILL 10 s later),
       - with cwd = the project root (what `cd $PROJ` did),
       - with stdout+stderr appended to the cron line's `>> logs/...` file, so
         every log-freshness monitor keeps seeing the files it already watches.
  3. Write the receipt `<state_root>/data/runtime/health_tick_last.json`
     (HealthTickReceipt@v1) and append one line to `health_tick_history.jsonl`.
  4. Exit 1 when any due step failed (non-zero rc, timeout, or deferred past the
     tick budget) so the unit logs it; 0 otherwise; 2 when the table is unreadable.

A wedged step cannot block the next tick: its lock makes the next tick skip it
(recorded, not hidden), its timeout kills it, and `tick_budget_s` bounds the
whole tick below the timer period. A lock skip is recorded as `lock_skipped`,
not as a failure — cron's `flock -n` was silent about it; this is louder.
A timeout IS a failure.

    scripts/health_tick.py --dry-run                 # print the due plan, run nothing
    scripts/health_tick.py --dry-run --now 2026-10-07T09:20:00
    scripts/health_tick.py --apply                   # the timer's ExecStart
    scripts/health_tick.py --once --step cio-bridge-watchdog   # run one step now

What stays in cron on purpose: the three safety nets (portfolio_server_watchdog.sh
*/2, process_reaper.py */3, cleanup_stale_locks.sh */5), resolve_due_checkpoints.py
(a declared lane with its own semantics) and the @reboot moomoo line.

AUTHORITY: READ_ONLY_ADVISORY. Runs existing monitor scripts; never touches a
broker, an order, a stop, a credential or the crontab. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

NO_CONSUMER_REASON = (
    "Scheduled entrypoint for the proposed tradeai-health-tick.timer (NEVER_SCHEDULED "
    "until the operator's config-write grant). Consumers of its receipt are the lane "
    "registry (data/runtime/health_tick_last.json) and journalctl; nothing imports it."
)

STEPS_SCHEMA = "HealthTickSteps@v1"
RECEIPT_SCHEMA = "HealthTickReceipt@v1"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TABLE = PROJECT_ROOT / "config" / "health_tick_steps.json"
RECEIPT_REL = "data/runtime/health_tick_last.json"
HISTORY_REL = "data/runtime/health_tick_history.jsonl"
KILL_GRACE_S = 10.0
# Never let a captured stderr line carry a secret into a receipt (token=, DSNs, bearer).
SECRET_RE = re.compile(r"(postgres(?:ql)?://\S+|(?<![A-Za-z])sk-[A-Za-z0-9]{6,}|bearer\s+\S+|"
                       r"(?:token|password|secret|api[_-]?key)=\S+)", re.I)

EXIT_OK = 0
EXIT_STEP_FAILED = 1
EXIT_CANNOT_RUN = 2


# ── table ───────────────────────────────────────────────────────────────────

def load_table(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != STEPS_SCHEMA:
        raise ValueError(f"{path}: schema {data.get('schema')!r} != {STEPS_SCHEMA}")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"{path}: steps must be a non-empty list")
    seen: set[str] = set()
    for s in steps:
        sid = str(s.get("step_id") or "")
        if not sid or sid in seen:
            raise ValueError(f"{path}: step_id missing or duplicate: {sid!r}")
        seen.add(sid)
        cmd = s.get("command")
        if not isinstance(cmd, list) or not cmd or not all(isinstance(c, str) for c in cmd):
            raise ValueError(f"{path}: {sid}: command must be a non-empty list of strings")
        cad = int(s.get("cadence_minutes") or 0)
        if cad <= 0:
            raise ValueError(f"{path}: {sid}: cadence_minutes must be > 0")
        if cad >= 60 and cad % 60:
            raise ValueError(f"{path}: {sid}: an hour-and-up cadence must be a whole number of hours")
    return data


# ── due computation (cron-equivalent) ───────────────────────────────────────

def snap_to_tick(now: datetime, tick_minutes: int) -> datetime:
    """Floor to the tick grid. systemd fires at or after the boundary, never before."""
    minute = (now.minute // tick_minutes) * tick_minutes
    return now.replace(minute=minute, second=0, microsecond=0)


def step_is_due(step: dict[str, Any], tick: datetime, tick_minutes: int) -> bool:
    """Cron semantics on the tick grid.

    cadence < 60   : `*/N` — minute % N == offset % N (cron's `*/N` is phase 0 from
                     the top of the hour; an offset keeps a `/N` line's phase).
    cadence >= 60  : minute == offset snapped to the grid; hour in `hours` when a
                     list is given (an explicit `a-b/2` or `12,15` list), else
                     hour % (cadence/60) == 0 — cron's `*/2`, `*/4`.
    hours/weekdays : inclusive windows; weekdays are ISO 1=Mon..7=Sun.
    """
    cad = int(step["cadence_minutes"])
    offset = int(step.get("minute_offset") or 0)
    hours = step.get("hours")
    weekdays = step.get("weekdays")
    if weekdays is not None and tick.isoweekday() not in {int(d) for d in weekdays}:
        return False
    if hours is not None and tick.hour not in {int(h) for h in hours}:
        return False
    if cad < 60:
        return tick.minute % cad == offset % cad
    snapped = (offset // tick_minutes) * tick_minutes
    if tick.minute != snapped:
        return False
    if hours is None:
        return tick.hour % (cad // 60) == 0
    return True


def due_steps(table: dict[str, Any], tick: datetime) -> list[dict[str, Any]]:
    tm = int(table.get("tick_minutes") or 5)
    return [s for s in table["steps"] if step_is_due(s, tick, tm)]


def firings_per_week(table: dict[str, Any], start: datetime) -> dict[str, int]:
    """Count due firings per step over 7 days of ticks from `start` (planning aid)."""
    from datetime import timedelta
    tm = int(table.get("tick_minutes") or 5)
    counts = {s["step_id"]: 0 for s in table["steps"]}
    t = snap_to_tick(start, tm)
    end = t + timedelta(days=7)
    while t < end:
        for s in table["steps"]:
            if step_is_due(s, t, tm):
                counts[s["step_id"]] += 1
        t += timedelta(minutes=tm)
    return counts


# ── execution ───────────────────────────────────────────────────────────────

def render_command(step: dict[str, Any], *, py: str, project_root: Path) -> list[str]:
    """`$PY`/`$PROJ` as the crontab defined them; the market_day_gate wrapper verbatim."""
    cmd = [c.replace("$PY", py).replace("$PROJ", str(project_root)) for c in step["command"]]
    if step.get("market_day_gate"):
        cmd = ["bash", "scripts/market_day_gate.sh", *cmd]
    return cmd


def _env_for(step: dict[str, Any], project_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    if step.get("needs_env"):
        env_file = project_root / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip())
    return env


def _first_stderr_line(stderr: bytes) -> Optional[str]:
    for raw in (stderr or b"").decode("utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line:
            return SECRET_RE.sub("[redacted]", line)[:240]
    return None


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + KILL_GRACE_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_step(step: dict[str, Any], *, py: str, project_root: Path, default_timeout_s: float,
             log_root: Optional[Path] = None) -> dict[str, Any]:
    """Run one step under its flock and timeout. Never raises."""
    sid = step["step_id"]
    timeout_s = float(step.get("timeout_s") or default_timeout_s)
    row: dict[str, Any] = {"step_id": sid, "due": True, "ran": False, "rc": None,
                           "duration_s": 0.0, "lock_skipped": False, "timeout": False,
                           "stderr_first_line": None, "error": None}
    cmd = render_command(step, py=py, project_root=project_root)
    lock_path = step.get("lock")
    lock_fd = None
    if lock_path:
        try:
            lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(lock_fd)
            row["lock_skipped"] = True
            row["error"] = f"lock held: {lock_path}"
            return row
        except OSError as exc:
            if lock_fd is not None:
                os.close(lock_fd)
            row["error"] = f"lock unavailable: {type(exc).__name__}"
            return row

    log_path = None
    if step.get("log"):
        base = Path(log_root) if log_root else project_root
        log_path = base / str(step["log"])
    started = time.monotonic()
    out = err = b""
    try:
        proc = subprocess.Popen(cmd, cwd=str(project_root), env=_env_for(step, project_root),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
        row["ran"] = True
        try:
            out, err = proc.communicate(timeout=timeout_s)
            row["rc"] = proc.returncode
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            try:
                out, err = proc.communicate(timeout=KILL_GRACE_S)
            except subprocess.TimeoutExpired:
                out, err = b"", b""
            row["timeout"] = True
            row["rc"] = proc.returncode if proc.returncode is not None else -9
            row["error"] = f"timeout after {timeout_s:.0f}s"
    except (OSError, ValueError) as exc:
        row["rc"] = 127
        row["error"] = f"spawn failed: {type(exc).__name__}: {exc}"[:240]
    finally:
        row["duration_s"] = round(time.monotonic() - started, 3)
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
    row["stderr_first_line"] = _first_stderr_line(err)
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "ab") as fh:
                if out:
                    fh.write(out if out.endswith(b"\n") else out + b"\n")
                if err:
                    fh.write(err if err.endswith(b"\n") else err + b"\n")
                if row["timeout"]:
                    fh.write(f"[health_tick] {sid} {row['error']}\n".encode())
        except OSError as exc:
            row["error"] = (row["error"] or "") + f" | log append failed: {type(exc).__name__}"
    return row


def step_ok(row: dict[str, Any]) -> bool:
    if row.get("lock_skipped"):
        return True          # information, not failure: cron's flock -n was silent here
    if not row.get("ran"):
        return False         # deferred / spawn failed
    return (not row.get("timeout")) and row.get("rc") == 0


# ── receipt ─────────────────────────────────────────────────────────────────

def state_root() -> Path:
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env)
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root())
    except Exception:
        return PROJECT_ROOT


def served_sha(project_root: Path) -> Optional[str]:
    explicit = os.environ.get("TRADEAI_SERVED_SHA")
    if explicit:
        return explicit.strip()
    for cand in (project_root / "GIT_SHA",
                 Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT" / "GIT_SHA"):
        try:
            return cand.read_text(encoding="utf-8").strip() or None
        except OSError:
            continue
    return None


def write_receipt(root: Path, receipt: dict[str, Any]) -> tuple[Path, Path]:
    last = root / RECEIPT_REL
    hist = root / HISTORY_REL
    last.parent.mkdir(parents=True, exist_ok=True)
    tmp = last.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, last)
    with open(hist, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(receipt, sort_keys=True) + "\n")
    return last, hist


# ── tick ────────────────────────────────────────────────────────────────────

def run_tick(table: dict[str, Any], *, now: datetime, py: str, project_root: Path,
             apply: bool, only_step: Optional[str] = None, max_parallel: Optional[int] = None,
             tick_budget_s: Optional[float] = None, log_root: Optional[Path] = None) -> dict[str, Any]:
    tm = int(table.get("tick_minutes") or 5)
    tick = snap_to_tick(now, tm)
    default_timeout = float(table.get("default_timeout_s") or 240)
    budget = float(tick_budget_s if tick_budget_s is not None else table.get("tick_budget_s") or 280)
    workers = int(max_parallel if max_parallel is not None else table.get("max_parallel") or 1)

    if only_step:
        selected = [s for s in table["steps"] if s["step_id"] == only_step]
        if not selected:
            raise KeyError(only_step)
        due_ids = {only_step}
    else:
        due_ids = {s["step_id"] for s in due_steps(table, tick)}
        selected = [s for s in table["steps"] if s["step_id"] in due_ids]

    rows: dict[str, dict[str, Any]] = {}
    for s in table["steps"]:
        rows[s["step_id"]] = {"step_id": s["step_id"], "due": s["step_id"] in due_ids,
                              "ran": False, "rc": None, "duration_s": 0.0,
                              "lock_skipped": False, "timeout": False,
                              "command": render_command(s, py=py, project_root=project_root),
                              "lock": s.get("lock"), "timeout_s": float(s.get("timeout_s") or default_timeout)}

    started = time.monotonic()
    deferred: list[str] = []
    if apply and selected:
        def _run(step: dict[str, Any]) -> dict[str, Any]:
            return run_step(step, py=py, project_root=project_root,
                            default_timeout_s=default_timeout, log_root=log_root)

        if workers <= 1:
            for step in selected:
                elapsed = time.monotonic() - started
                if elapsed >= budget:
                    deferred.append(step["step_id"])
                    rows[step["step_id"]].update({"error": f"deferred: tick budget {budget:.0f}s spent"})
                    continue
                rows[step["step_id"]].update(_run(step))
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for step, res in zip(selected, pool.map(_run, selected)):
                    rows[step["step_id"]].update(res)

    failed = [sid for sid in due_ids if apply and not step_ok(rows[sid])]
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "served_sha": served_sha(project_root),
        "tick": tick.isoformat(timespec="minutes"),
        "tick_minutes": tm,
        "mode": "once" if only_step else ("apply" if apply else "dry-run"),
        "steps": [rows[s["step_id"]] for s in table["steps"]],
        "due_count": len(due_ids),
        "ran_count": sum(1 for r in rows.values() if r["ran"]),
        "lock_skipped": sorted(sid for sid in due_ids if rows[sid]["lock_skipped"]),
        "timed_out": sorted(sid for sid in due_ids if rows[sid]["timeout"]),
        "deferred": deferred,
        "failed": sorted(failed),
        "duration_s": round(time.monotonic() - started, 3),
        "ok": not failed,
        "sends": False,
        "state_root_note": "receipt path resolves against TRADEAI_STATE_ROOT / persistent-state, not the code tree",
    }
    return receipt


def _parse_now(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now().astimezone()
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.astimezone()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="run the due steps (the timer's mode)")
    mode.add_argument("--dry-run", action="store_true", help="print the due plan; run nothing, write nothing")
    mode.add_argument("--once", action="store_true", help="run exactly one step now (needs --step)")
    ap.add_argument("--step", default=None, help="step_id for --once")
    ap.add_argument("--now", default=None, help="ISO datetime to evaluate instead of the wall clock (tests)")
    ap.add_argument("--table", default=str(DEFAULT_TABLE))
    ap.add_argument("--project-root", default=str(PROJECT_ROOT), help="what `cd $PROJ` meant (CURRENT)")
    ap.add_argument("--state-root", default=None, help="where the receipt goes (default: persistent state root)")
    ap.add_argument("--log-root", default=None, help="base for the steps' `log` paths (default: project root)")
    ap.add_argument("--py", default=os.environ.get("TRADEAI_PY") or sys.executable, help="what `$PY` meant")
    ap.add_argument("--max-parallel", type=int, default=None)
    ap.add_argument("--tick-budget-s", type=float, default=None)
    ap.add_argument("--json", action="store_true", help="print the receipt as JSON")
    ap.add_argument("--week-plan", action="store_true", help="print firings per step over 7 days and exit")
    args = ap.parse_args(argv)

    try:
        table = load_table(Path(args.table))
    except Exception as exc:
        print(f"health_tick CANNOT RUN: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    try:
        now = _parse_now(args.now)
    except ValueError as exc:
        print(f"health_tick CANNOT RUN: bad --now: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    if args.week_plan:
        counts = firings_per_week(table, now)
        print(json.dumps({"from": snap_to_tick(now, int(table.get("tick_minutes") or 5)).isoformat(),
                          "ticks_per_week": 7 * 24 * 60 // int(table.get("tick_minutes") or 5),
                          "firings": counts, "total": sum(counts.values())}, indent=2))
        return EXIT_OK

    if args.once and not args.step:
        print("--once needs --step <step_id>", file=sys.stderr)
        return EXIT_CANNOT_RUN
    apply = bool(args.apply or args.once)
    project_root = Path(args.project_root)
    try:
        receipt = run_tick(table, now=now, py=args.py, project_root=project_root, apply=apply,
                           only_step=args.step if args.once else None,
                           max_parallel=args.max_parallel, tick_budget_s=args.tick_budget_s,
                           log_root=Path(args.log_root) if args.log_root else None)
    except KeyError as exc:
        print(f"health_tick CANNOT RUN: unknown step {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    if apply:
        root = Path(args.state_root) if args.state_root else state_root()
        try:
            last, _hist = write_receipt(root, receipt)
            receipt["receipt_path"] = str(last)
        except OSError as exc:
            print(f"health_tick: receipt write failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            receipt["ok"] = False
            receipt["failed"] = sorted(set(receipt["failed"]) | {"__receipt__"})

    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        due = [r for r in receipt["steps"] if r["due"]]
        print(f"[health_tick] tick={receipt['tick']} mode={receipt['mode']} due={len(due)} "
              f"ran={receipt['ran_count']} ok={receipt['ok']} served_sha={receipt['served_sha']}")
        for r in due:
            state = ("LOCK_SKIPPED" if r["lock_skipped"] else "TIMEOUT" if r["timeout"]
                     else f"rc={r['rc']}" if r["ran"] else "PLANNED" if not apply else "DEFERRED")
            print(f"  {r['step_id']:<32} {state:<13} {r['duration_s']:>7.1f}s  {' '.join(r['command'])}")
            if r.get("stderr_first_line"):
                print(f"      stderr: {r['stderr_first_line']}")
        if receipt.get("receipt_path"):
            print(f"[health_tick] receipt {receipt['receipt_path']}")
    if not apply:
        return EXIT_OK
    return EXIT_OK if receipt["ok"] else EXIT_STEP_FAILED


if __name__ == "__main__":
    sys.exit(main())
