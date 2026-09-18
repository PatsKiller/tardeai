#!/usr/bin/env python3
"""remediate_postgres_main.py — allowlisted start of postgresql@17-main.

Safe path only:
  1. Measure free disk on /
  2. Refuse restart if below floor (avoid ENOSPC restart loops)
  3. Check unit state; no-op if already active
  4. `sudo -n systemctl start postgresql@17-main` (passwordless sudoers required)
  5. Verify is-active; write a JSON receipt under logs/

Never touches PG data, never runs pg_resetwal, never deletes files.

Usage:
  .venv/bin/python scripts/remediate_postgres_main.py           # dry status
  .venv/bin/python scripts/remediate_postgres_main.py --apply   # attempt start
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.postgres_main_health import (  # noqa: E402
    DEFAULT_RESTART_CFG,
    evaluate_disk_usage,
    restart_safe,
    unit_inactive_statuses,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
RECEIPT = LOG_DIR / "postgres_main_remediate.jsonl"
COOLDOWN_FLAG = Path("/tmp/tradeai_postgres_main_remediate.cooldown")
UNIT = str(DEFAULT_RESTART_CFG["unit"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(argv: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    uid = os.getuid()
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)


def unit_state() -> str:
    try:
        p = _run(["systemctl", "is-active", UNIT], timeout=15)
        return (p.stdout or p.stderr or "unknown").strip().splitlines()[0].strip() or "unknown"
    except Exception as e:
        return f"error:{e}"


def disk_snapshot() -> dict:
    u = shutil.disk_usage("/")
    v = evaluate_disk_usage(total_bytes=u.total, used_bytes=u.used, free_bytes=u.free)
    return {
        "free_gb": v.free_gb,
        "free_pct": v.free_pct,
        "severity": v.severity,
        "finding_type": v.finding_type,
        "message": v.message,
    }


def cooldown_active(minutes: int) -> bool:
    if not COOLDOWN_FLAG.is_file():
        return False
    try:
        age = time.time() - COOLDOWN_FLAG.stat().st_mtime
        return age < minutes * 60
    except OSError:
        return False


def mark_cooldown() -> None:
    try:
        COOLDOWN_FLAG.write_text(_now() + "\n", encoding="utf-8")
    except OSError:
        pass


def write_receipt(payload: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with RECEIPT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def attempt_start() -> dict:
    disk = disk_snapshot()
    state = unit_state()
    out: dict = {
        "ts": _now(),
        "unit": UNIT,
        "disk": disk,
        "state_before": state,
        "action": "none",
        "ok": False,
    }

    ok_disk, reason = restart_safe(free_pct=float(disk["free_pct"]), free_gb=float(disk["free_gb"]))
    out["restart_safe"] = ok_disk
    out["restart_safe_reason"] = reason
    if not ok_disk:
        out["action"] = "refused_disk"
        out["message"] = reason
        return out

    if state == "active":
        out["action"] = "already_active"
        out["ok"] = True
        out["message"] = f"{UNIT} already active"
        return out

    if state not in unit_inactive_statuses() and not state.startswith("error:"):
        # activating / reloading — don't fight it
        out["action"] = "wait_state"
        out["message"] = f"{UNIT} state={state}; not starting"
        return out

    cooldown_m = int(DEFAULT_RESTART_CFG["cooldown_minutes"])
    if cooldown_active(cooldown_m):
        out["action"] = "cooldown"
        out["message"] = f"cooldown active ({cooldown_m}m) — skip start"
        return out

    try:
        p = _run(["sudo", "-n", "systemctl", "start", UNIT], timeout=120)
    except Exception as e:
        out["action"] = "start_exception"
        out["message"] = f"start raised: {e}"
        return out

    out["start_rc"] = p.returncode
    out["start_stdout"] = (p.stdout or "")[:500]
    out["start_stderr"] = (p.stderr or "")[:500]
    if p.returncode != 0:
        out["action"] = "start_failed"
        err = (p.stderr or p.stdout or "").strip()
        if "password" in err.lower() or "a password is required" in err.lower() or p.returncode == 1:
            out["message"] = (
                f"sudo -n systemctl start {UNIT} failed (rc={p.returncode}). "
                "Install passwordless sudoers for this unit (see "
                "linux_launchers/sudoers/tradeai-postgres-main-start) or start manually: "
                f"sudo systemctl start {UNIT}"
            )
            out["needs_sudoers"] = True
        else:
            out["message"] = f"systemctl start failed rc={p.returncode}: {err[:300]}"
        return out

    mark_cooldown()
    # Brief settle then verify
    time.sleep(2)
    after = unit_state()
    out["state_after"] = after
    out["action"] = "started"
    out["ok"] = after == "active"
    out["message"] = (
        f"started {UNIT}; is-active={after}"
        if out["ok"]
        else f"start returned 0 but is-active={after} — check journalctl -u {UNIT}"
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Attempt allowlisted start")
    ap.add_argument("--json", action="store_true", default=True)
    args = ap.parse_args()

    if not args.apply:
        payload = {
            "ts": _now(),
            "unit": UNIT,
            "disk": disk_snapshot(),
            "state": unit_state(),
            "action": "status_only",
            "ok": True,
            "message": "pass --apply to attempt start",
        }
    else:
        payload = attempt_start()

    write_receipt(payload)
    print(json.dumps(payload, indent=2))
    # Soft outcomes (missing sudoers, cooldown, disk refuse, already up) exit 0 so the
    # watchdog timer does not flap failed every 5m while waiting on operator sudoers.
    soft = {
        "status_only",
        "already_active",
        "cooldown",
        "refused_disk",
        "wait_state",
    }
    if payload.get("ok") or payload.get("action") in soft or payload.get("needs_sudoers"):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
