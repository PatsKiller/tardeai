#!/usr/bin/env python3
"""cron_self_heal.py — watch the watchlist cron lanes and self-heal on failure.

Closes the "monitor + notify + auto-fix + re-enable" requirement for the six
watchlist-remediation cron jobs (2026-08-19). It consumes the SAME registry that
job_coverage_monitor.py uses (single source of truth), but only acts on entries that
carry both a `cron_line` (to re-add when NOT_SCHEDULED) and a `remediate_cmd` (to
re-run when STALE).

Actions (all throttled + logged + Telegram-notified):
  NOT_SCHEDULED  -> re-add the entry to the live crontab (idempotent).
  STALE          -> re-run the job's remediate command (bounded attempts).
  NO_SIGNAL      -> notify only (first run before any heartbeat exists).

Not cron-only any more (2026-10-09, n8n maturity B3.1):
  - `$PY` expands to the interpreter that actually exists (PY / TRADEAI_PY from
    the environment the crontab header and the health-tick unit both set, else
    <project>/.venv/bin/python when present, else this interpreter). It used to
    be hard-wired to <project>/.venv/bin/python, which does not exist in the
    served tree (CURRENT) this script has run from since the health-tick cutover:
    every rerun would have exited 127 and counted as a failed heal, and every
    re-add would have installed a crontab line with a dead interpreter.
  - A lane the lane registry says is scheduled by something other than cron
    (systemd / n8n / a health-tick or nightly step table — `superseded_by`) is
    not "NOT_SCHEDULED" just because its crontab line is gone: re-adding it would
    run it twice. Such a lane is still checked for staleness. A lane the registry
    RETIRED without a successor is left alone.

Why "acted": [] is the normal output: the six managed lanes are scheduled and
fresh (cadence_h=80 against daily runs). It last acted 2026-09-21 06:00 (two
STALE reruns, both ok) — see tests/test_cron_self_heal_acts_20261009.py for the
proof that it still acts on a healable case.

Self-protection:
  - One heal action per job per cooldown window (no tight re-add/rerun loops).
  - Attempt cap: after N consecutive failed heals, back off and keep notifying only.
  - State persists to data/runtime/cron_self_heal_state.json.

This script is invoked BY cron, so its own crontab/telegram subprocesses run under
the operator's account and are not subject to the interactive guard. It is a
watch-the-watchman: it cannot re-add itself if its own entry is dropped.

Usage:
    python3 scripts/cron_self_heal.py            # DRY-RUN: report what it WOULD do
    python3 scripts/cron_self_heal.py --apply    # act + notify
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# .env (DB_PASSWORD for the monitor's DB signals; TELEGRAM_* for notify).
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

from job_coverage_monitor import (  # noqa: E402
    REGISTRY,
    _crontab_lines,
    _is_scheduled,
    _log_age_h,
    _db_age_h,
)

STATE_FILE = PROJECT_ROOT / "data" / "runtime" / "cron_self_heal_state.json"
LOG_FILE = PROJECT_ROOT / "logs" / "cron_self_heal.log"

# Throttles (seconds).
HEAL_COOLDOWN_S = float(os.getenv("CRON_SELF_HEAL_COOLDOWN_S", str(6 * 3600)))
NOTIFY_COOLDOWN_S = float(os.getenv("CRON_SELF_HEAL_NOTIFY_COOLDOWN_S", str(6 * 3600)))
MAX_FAILS = int(os.getenv("CRON_SELF_HEAL_MAX_FAILS", "3"))


def _log(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass


def _notify(msg: str) -> None:
    try:
        from telegram_alert import send_telegram
        send_telegram(f"🛠️ cron-self-heal: {msg}")
    except Exception:
        pass


def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    except Exception:
        pass


LANE_REGISTRY = PROJECT_ROOT / "config" / "lane_registry.json"


def _python() -> str:
    """The interpreter `$PY` means here — one that exists."""
    for cand in (os.environ.get("PY"), os.environ.get("TRADEAI_PY"),
                 str(PROJECT_ROOT / ".venv" / "bin" / "python")):
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            return cand
    return sys.executable


def _project() -> str:
    proj = os.environ.get("PROJ")
    return proj if proj and Path(proj).is_dir() else str(PROJECT_ROOT)


def _expand(cmd: str) -> str:
    """Expand $PROJ / $PY to absolute paths so re-add/re-run works even without the
    crontab env header."""
    return cmd.replace("$PROJ", _project()).replace("$PY", _python())


def _registry_scheduler(match: str, registry_path: Path | None = None) -> tuple[str, str] | None:
    """What the lane registry says schedules `match` when it is NOT plain cron.

    Returns ("elsewhere", why) for a non-cron scheduler or a RETIRED row with a
    successor, ("retired", why) for a RETIRED row without one, None when the
    registry has no opinion (no row, or an ACTIVE cron row — crontab is truth)."""
    path = registry_path or LANE_REGISTRY
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    rows = data.get("lanes") if isinstance(data, dict) else data
    for row in rows or []:
        sched = row.get("scheduler") or {}
        if match not in str(sched.get("match") or "") and match not in str(sched.get("expression") or ""):
            continue
        kind = str(sched.get("kind") or "")
        state = str(row.get("state") or "")
        if state == "RETIRED":
            if row.get("superseded_by"):
                return ("elsewhere", f"{row.get('lane_id')} superseded_by {row['superseded_by']}")
            return ("retired", f"{row.get('lane_id')} RETIRED")
        if kind and kind != "cron":
            return ("elsewhere", f"{row.get('lane_id')} scheduled by {kind}")
    return None


def _re_add(cron_line: str) -> bool:
    """Append cron_line to the live crontab if it is not already scheduled."""
    expanded = _expand(cron_line)
    script = _script_of(expanded)
    if not script:
        _log(f"re-add skipped: could not extract script from {cron_line}")
        return False
    try:
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    except Exception as e:
        _log(f"crontab -l failed: {e}")
        return False
    lines = [ln for ln in current.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if any(script in ln for ln in lines):
        return False  # already scheduled — nothing to do
    new = (current.rstrip("\n") + "\n" + expanded + "\n")
    r = subprocess.run(["crontab", "-"], input=new, text=True, capture_output=True)
    if r.returncode != 0:
        _log(f"crontab re-add failed: {r.stderr.strip()[:200]}")
        return False
    _log(f"re-added cron line: {expanded}")
    return True


def _script_of(cmd: str) -> str:
    for tok in cmd.split():
        if "scripts/" in tok and (tok.endswith(".py") or tok.endswith(".sh")):
            return tok.split("/")[-1]
    return ""


def _rerun(remediate_cmd: str) -> bool:
    cmd = _expand(remediate_cmd)
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=900)
        ok = r.returncode == 0
        _log(f"rerun {'ok' if ok else 'failed'} rc={r.returncode}: {cmd}")
        if not ok and r.stderr:
            _log(f"  stderr: {r.stderr.strip()[:300]}")
        return ok
    except Exception as e:
        _log(f"rerun exception: {e}")
        return False


def _job_status(job: dict) -> tuple[str, float | None]:
    scheduled = _is_scheduled(job["schedule_match"], _crontab_lines())
    kind, arg = job["signal"]
    age = _log_age_h(arg) if kind == "log" else _db_age_h(arg)
    if not scheduled:
        elsewhere = _registry_scheduler(job["schedule_match"])
        if elsewhere and elsewhere[0] == "retired":
            return ("RETIRED", age)
        if not elsewhere:
            return ("NOT_SCHEDULED", age)
        # Scheduled by systemd / n8n / a step table: judge freshness only.
    if age is None:
        return ("NO_SIGNAL", age)
    if age > job["cadence_h"]:
        return ("STALE", age)
    return ("OK", age)


def heal(dry: bool) -> dict:
    state = _load_state()
    now = time.time()
    acted: list[str] = []
    notified: list[str] = []

    for job in REGISTRY:
        cron_line = job.get("cron_line")
        remediate_cmd = job.get("remediate_cmd")
        if not cron_line or not remediate_cmd:
            continue  # not self-heal managed
        name = job["name"]
        j = state.setdefault(name, {"fails": 0, "last_act": 0, "last_notify": 0})
        status, age = _job_status(job)

        if status in ("NOT_SCHEDULED", "STALE"):
            # Notify (throttled). Dry-run never sends.
            if not dry and now - j.get("last_notify", 0) >= NOTIFY_COOLDOWN_S:
                _notify(f"{name} {status}" + (f" ({age:.0f}h stale)" if age else ""))
                j["last_notify"] = now
                notified.append(name)
            # Heal (throttled + attempt-capped). Dry-run never acts.
            if (not dry and j.get("fails", 0) < MAX_FAILS
                    and now - j.get("last_act", 0) >= HEAL_COOLDOWN_S):
                j["last_act"] = now
                if status == "NOT_SCHEDULED":
                    ok = _re_add(cron_line)
                    action = "re-added to crontab"
                else:
                    ok = _rerun(remediate_cmd)
                    action = "re-ran remediate"
                if ok:
                    j["fails"] = 0
                else:
                    j["fails"] = j.get("fails", 0) + 1
                _log(f"{name}: {action} -> {'ok' if ok else 'fail'} (fails={j['fails']})")
                acted.append(f"{name}:{action}")
            elif dry and j.get("fails", 0) < MAX_FAILS:
                # Report what dry-run WOULD do without mutating anything.
                action = ("re-added to crontab" if status == "NOT_SCHEDULED"
                          else "re-ran remediate")
                acted.append(f"{name}:{action}")
        elif status == "OK":
            # Healthy again — reset the fail counter.
            if j.get("fails"):
                j["fails"] = 0

    if not dry:
        _save_state(state)
    summary = {"acted": acted, "notified": notified, "dry": dry}
    if dry:
        _log(f"DRY-RUN would: act={acted} notify={notified}")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually heal (default: dry-run)")
    args = ap.parse_args()

    results = heal(dry=not args.apply)
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
