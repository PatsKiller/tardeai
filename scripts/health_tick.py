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
  4. Exit with the TICK's health, not the system's (see "Exit codes" below).

Exit codes (decided 2026-10-09, n8n maturity B3.1)
  0  the tick ran its table: every due step ran to completion or was lock-skipped.
     Monitors may still have FOUND something unhealthy; that is reported in the
     receipt (`status: "unhealthy"`, `findings: [...]`, each row's `outcome:
     "finding"`) and by the monitors' own alerts — not by failing this unit.
  1  the tick itself is broken: a due step crashed (rc outside its declared
     `finding_rc`, or ANY rc -- 0 and finding codes included -- with a Python
     `Traceback (most recent call last):` header anywhere in its stderr), timed
     out, could not spawn, was deferred past the budget/deadline, or the receipt
     could not be written (`status: "broken"`, `broken: [...]`).
  2  the tick cannot run at all (table unreadable, bad arguments).
  Why: under the first two days of the timer, `system_health_agent.py` exited 1
  every 5 minutes because it (correctly) saw a critical component down, and the
  unit was "failed" ~265 times — so `systemctl --failed` / health_agent's
  `systemd_unit_failed` finding could no longer tell a broken scheduler from a
  working monitor reporting a real problem. A step declares which of its exit
  codes mean "I ran and found something" with `finding_rc` in the table.
  `finding_rc` may NOT contain 1: CPython exits 1 for an uncaught exception and
  for `sys.exit("fatal ...")`, and a crash cannot be told from a finding by
  parsing stderr (a psycopg2 OperationalError ends in a second message line, a
  bare `StopIteration` has no message, a traceback may be followed by more
  output). So the three monitors that report findings by exit code use
  EXIT_FINDING = 3 (scripts/lib/monitor_exit_codes.py): system_health_agent's
  critical-down, opend_health's data-plane-down and pipeline_liveness_report
  --fail-on-finding (STARVED / NO_ELIGIBLE_INPUT / UNKNOWN). rc 1 from any step
  is a crash. A Python traceback header in stderr is a crash whatever the rc
  (none of the absorbed scripts prints a handled traceback to stderr).

A wedged step cannot block the next tick: its lock makes the next tick skip it
(recorded, not hidden), its timeout kills it, and `tick_budget_s` bounds when
the last step may START. `tick_deadline_s` (below the unit's TimeoutStartSec)
bounds when the last step must END: a step's timeout is clamped to what is left
of the deadline, so a slow step is killed and recorded by this script instead of
systemd killing the whole tick before the receipt is written (2026-10-09: every
hourly tick from 09:00 died that way while the daemon-shaped
portfolio_live_monitor.py ran into its 300 s timeout). A lock skip is recorded as
`lock_skipped`, not as a failure — cron's `flock -n` was silent about it; this
is louder. A timeout IS a failure.

Processes a step leaves behind in its process group (fire-and-forget children,
e.g. pipeline_watchdog.py's detached symbol_enrichment.py runs) are given
`orphan_wait_s` to finish and are then terminated and recorded in the row as
`orphans`. Under cron they outlived the parent; inside this oneshot unit systemd
SIGTERMs them when the tick exits, they outlived the 90 s stop timeout, and the
unit ended `Result=timeout` after a clean receipt (every even hour, 10-07..10-09).

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
EXIT_STEP_FAILED = 1          # the tick is broken (a step crashed / timed out / was deferred)
EXIT_TICK_BROKEN = EXIT_STEP_FAILED
EXIT_CANNOT_RUN = 2
# Below the unit's TimeoutStartSec=330 with room for one kill grace + the receipt.
DEFAULT_TICK_DEADLINE_S = 300.0
DEFAULT_ORPHAN_WAIT_S = 30.0
MIN_STEP_WINDOW_S = 5.0
EXIT_SEMANTICS = ("0=tick completed (findings, if any, in `findings`/status=unhealthy); "
                  "1=tick broken (a step crashed, timed out, could not spawn or was deferred; "
                  "or the receipt failed); 2=cannot run")
# CPython's status for an uncaught exception or sys.exit("<str>"): never a finding.
PYTHON_CRASH_RC = 1
TRACEBACK_HEADER = b"Traceback (most recent call last):"


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
        frc = s.get("finding_rc", [])
        if not isinstance(frc, list) or not all(isinstance(x, int) and x != 0 for x in frc):
            raise ValueError(f"{path}: {sid}: finding_rc must be a list of non-zero ints")
        if PYTHON_CRASH_RC in frc:
            raise ValueError(f"{path}: {sid}: finding_rc may not contain {PYTHON_CRASH_RC} "
                             "(Python's uncaught-exception exit); use EXIT_FINDING=3")
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


def has_traceback(stderr: bytes) -> bool:
    """True when stderr carries a Python `Traceback (most recent call last):`
    header anywhere. Deliberately not a parse of the LAST line: a multi-line
    psycopg2 OperationalError, a message-less StopIteration, a traceback followed
    by more output and a chained exception all end differently, and each of them
    was being recorded as a finding (2026-10-09 review of PR #1600)."""
    return TRACEBACK_HEADER in (stderr or b"")


def classify(row: dict[str, Any], finding_rc: list[int], *, crashed: bool) -> str:
    """One outcome per due row: ok | finding | lock_skipped | timeout | crashed |
    spawn_failed | deferred | not_run."""
    if row.get("lock_skipped"):
        return "lock_skipped"
    if row.get("deferred"):
        return "deferred"
    if not row.get("ran"):
        return "spawn_failed" if row.get("rc") == 127 else "not_run"
    if row.get("timeout"):
        return "timeout"
    if crashed:
        return "crashed"
    rc = row.get("rc")
    if rc == 0:
        return "ok"
    if rc in set(finding_rc or []) and rc != PYTHON_CRASH_RC:
        return "finding"
    return "crashed"


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def reap_orphans(pgid: int, wait_s: float) -> Optional[dict[str, Any]]:
    """Wait up to `wait_s` for processes the step left in its process group, then
    SIGTERM, then SIGKILL after KILL_GRACE_S. None when nothing was left behind."""
    if not _group_alive(pgid):
        return None
    deadline = time.monotonic() + max(0.0, wait_s)
    while time.monotonic() < deadline:
        if not _group_alive(pgid):
            return {"lingered": True, "finished_within_s": round(max(0.0, wait_s), 1), "killed": False}
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return {"lingered": True, "killed": False}
    grace = time.monotonic() + KILL_GRACE_S
    while time.monotonic() < grace:
        if not _group_alive(pgid):
            return {"lingered": True, "killed": True, "signal": "SIGTERM", "waited_s": round(wait_s, 1)}
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return {"lingered": True, "killed": True, "signal": "SIGKILL", "waited_s": round(wait_s, 1)}


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
             log_root: Optional[Path] = None, time_left_s: Optional[float] = None,
             orphan_wait_s: float = DEFAULT_ORPHAN_WAIT_S) -> dict[str, Any]:
    """Run one step under its flock and timeout. Never raises.

    `time_left_s` is what remains of the tick deadline: the step's own timeout is
    clamped to it (minus one kill grace) so the tick always outlives its steps."""
    sid = step["step_id"]
    declared_timeout_s = float(step.get("timeout_s") or default_timeout_s)
    timeout_s = declared_timeout_s
    if time_left_s is not None:
        timeout_s = max(1.0, min(timeout_s, time_left_s - KILL_GRACE_S))
    row: dict[str, Any] = {"step_id": sid, "due": True, "ran": False, "rc": None,
                           "duration_s": 0.0, "lock_skipped": False, "timeout": False,
                           "stderr_first_line": None, "error": None, "outcome": None,
                           "effective_timeout_s": round(timeout_s, 1), "orphans": None}
    finding_rc = list(step.get("finding_rc") or [])
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
            row["outcome"] = classify(row, finding_rc, crashed=False)
            return row
        except OSError as exc:
            if lock_fd is not None:
                os.close(lock_fd)
            row["error"] = f"lock unavailable: {type(exc).__name__}"
            row["outcome"] = "not_run"
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
            clamped = timeout_s < declared_timeout_s
            row["error"] = (f"timeout after {timeout_s:.0f}s"
                            + (f" (clamped from {declared_timeout_s:.0f}s to the tick deadline)" if clamped else ""))
        if not row["timeout"]:
            wait = orphan_wait_s
            if time_left_s is not None:
                wait = max(0.0, min(wait, time_left_s - (time.monotonic() - started) - 2 * KILL_GRACE_S))
            row["orphans"] = reap_orphans(proc.pid, wait)
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
    row["outcome"] = classify(row, finding_rc, crashed=has_traceback(err))
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
                if row.get("orphans") and row["orphans"].get("killed"):
                    fh.write(f"[health_tick] {sid} left processes in its group; terminated "
                             f"after {row['orphans'].get('waited_s')}s ({row['orphans'].get('signal')})\n".encode())
        except OSError as exc:
            row["error"] = (row["error"] or "") + f" | log append failed: {type(exc).__name__}"
    return row


def step_ok(row: dict[str, Any]) -> bool:
    """Green: ran clean or lock-skipped. A finding is NOT ok (it is in `failed`),
    but it is not broken either — see step_broken."""
    if row.get("lock_skipped"):
        return True          # information, not failure: cron's flock -n was silent here
    if not row.get("ran"):
        return False         # deferred / spawn failed
    if row.get("outcome") == "crashed":
        return False         # rc 0 with a traceback in stderr is a crash too
    return (not row.get("timeout")) and row.get("rc") == 0


def step_broken(row: dict[str, Any]) -> bool:
    """The tick could not do this step's job: anything but ok / finding / lock skip."""
    return row.get("outcome") not in ("ok", "finding", "lock_skipped")


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
    deadline = float(table.get("tick_deadline_s") or max(DEFAULT_TICK_DEADLINE_S, budget + 20))
    deadline = max(deadline, budget)
    orphan_wait = float(table.get("orphan_wait_s") if table.get("orphan_wait_s") is not None
                        else DEFAULT_ORPHAN_WAIT_S)
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
                              "outcome": None if s["step_id"] in due_ids else "not_due",
                              "finding_rc": list(s.get("finding_rc") or []),
                              "command": render_command(s, py=py, project_root=project_root),
                              "lock": s.get("lock"), "timeout_s": float(s.get("timeout_s") or default_timeout)}

    started = time.monotonic()
    deferred: list[str] = []
    if apply and selected:
        def _run(step: dict[str, Any]) -> dict[str, Any]:
            return run_step(step, py=py, project_root=project_root,
                            default_timeout_s=default_timeout, log_root=log_root,
                            time_left_s=deadline - (time.monotonic() - started),
                            orphan_wait_s=orphan_wait)

        if workers <= 1:
            for step in selected:
                elapsed = time.monotonic() - started
                if elapsed >= budget or deadline - elapsed < KILL_GRACE_S + MIN_STEP_WINDOW_S:
                    deferred.append(step["step_id"])
                    rows[step["step_id"]].update({"deferred": True, "outcome": "deferred",
                                                  "error": f"deferred: tick budget {budget:.0f}s spent"})
                    continue
                rows[step["step_id"]].update(_run(step))
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for step, res in zip(selected, pool.map(_run, selected)):
                    rows[step["step_id"]].update(res)

    failed = [sid for sid in due_ids if apply and not step_ok(rows[sid])]
    broken = sorted(sid for sid in failed if step_broken(rows[sid]))
    findings = sorted(sid for sid in failed if rows[sid].get("outcome") == "finding")
    orphaned = sorted(sid for sid in due_ids if (rows[sid].get("orphans") or {}).get("killed"))
    if not apply:
        status = "planned"
    elif broken:
        status = "broken"
    elif findings:
        status = "unhealthy"
    else:
        status = "healthy"
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
        "broken": broken,
        "findings": findings,
        "orphans_terminated": orphaned,
        "status": status,
        "tick_ok": not broken,
        "exit_semantics": EXIT_SEMANTICS,
        "tick_budget_s": budget,
        "tick_deadline_s": deadline,
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
            receipt["tick_ok"] = False
            receipt["status"] = "broken"
            receipt["failed"] = sorted(set(receipt["failed"]) | {"__receipt__"})
            receipt["broken"] = sorted(set(receipt["broken"]) | {"__receipt__"})

    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        due = [r for r in receipt["steps"] if r["due"]]
        print(f"[health_tick] tick={receipt['tick']} mode={receipt['mode']} due={len(due)} "
              f"ran={receipt['ran_count']} status={receipt['status']} ok={receipt['ok']} "
              f"served_sha={receipt['served_sha']}")
        for r in due:
            state = ("LOCK_SKIPPED" if r["lock_skipped"] else "TIMEOUT" if r["timeout"]
                     else f"rc={r['rc']}" if r["ran"] else "PLANNED" if not apply else "DEFERRED")
            if r.get("outcome") in ("finding", "crashed"):
                state = f"{state}:{r['outcome']}"
            print(f"  {r['step_id']:<32} {state:<13} {r['duration_s']:>7.1f}s  {' '.join(r['command'])}")
            if r.get("stderr_first_line"):
                print(f"      stderr: {r['stderr_first_line']}")
        if receipt.get("receipt_path"):
            print(f"[health_tick] receipt {receipt['receipt_path']}")
    if not apply:
        return EXIT_OK
    return EXIT_OK if receipt["tick_ok"] else EXIT_TICK_BROKEN


if __name__ == "__main__":
    sys.exit(main())
