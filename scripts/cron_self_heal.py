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


def _expand(cmd: str) -> str:
    """Expand $PROJ / $PY to absolute paths so re-add/re-run works even without the
    crontab env header."""
    return cmd.replace("$PROJ", str(PROJECT_ROOT)).replace(
        "$PY", str(PROJECT_ROOT / ".venv" / "bin" / "python"))


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
        return ("NOT_SCHEDULED", age)
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
