#!/usr/bin/env python3
"""Reclaim disk the moment it crosses a threshold — do not wait for Sunday.

WHY THIS EXISTS
---------------
Operator, 2026-09-21: "create an alerted automated mechanism that if it is over
85% full it should execute and not wait for the weekly schedule".

The reaper already existed and was not broken. `disk_hygiene_enforcer.py` ran
correctly, protected CURRENT and EXPECTED_RELEASE, and reclaimed 74 GB the
moment it was invoked. What failed was **cadence**: it is driven only by
`tradeai-weekly-disk-cleanup.timer` (Sun 06:30). Between the 09-20 run and the
09-27 run, six deploys landed on 09-21 and the disk went to 100% full with 84 MB
free -- systemd could no longer allocate inotify watches for 11 services.

This guard changes the trigger, not the policy. It shells the SAME enforcer with
the SAME protections. It mints no retention rule of its own.

WHAT IT DOES
------------
  1. Reads disk usage. Above the trigger (default 85% used == 15% free, which is
     exactly `disk_hygiene_enforcer`'s existing `warn_free_pct`), it runs
     `disk_hygiene_enforcer.py --apply`.
  2. Records the condition through `alert_condition_state.observe()`, so the
     operator is told on a TRANSITION (ok -> pressure -> recovered) and then at
     most once per `min_realert_minutes` while it stays bad. A guard that pages
     every 15 minutes during a long cleanup is noise, and this codebase already
     has ~5,500 alerts/day of that.
  3. Sends one Telegram line on a notify-worthy transition, using the same
     idiom as weekly_disk_cleanup_notify.py:285.

WHAT IT DOES NOT DO
-------------------
Never deletes anything itself. Every deletion is the enforcer's, under the
enforcer's `keep_n` and its protected set (CURRENT, EXPECTED_RELEASE). If the
enforcer is absent or fails, this reports and exits non-zero -- it does not
improvise a fallback.

It also does not touch the database. The 2026-09-21 crisis was builds: releases
were 167 GB against a 26 GB database. Postgres retention is a separate ladder
(`hermes-librarian-retention.timer`, `db-retention.timer`) and is deliberately
out of scope here.

    python scripts/disk_pressure_guard.py                 # check + act if over
    python scripts/disk_pressure_guard.py --dry-run       # report only
    python scripts/disk_pressure_guard.py --used-pct 80   # tighter trigger

AUTHORITY: OPERATOR_APPROVED 2026-09-21. Delegates all deletion to
disk_hygiene_enforcer.py.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

#: 85% used == 15% free == disk_hygiene_enforcer's own `warn_free_pct`. Kept
#: identical on purpose: two components disagreeing about what "pressure" means
#: is how a guard ends up firing against a policy that will not act.
DEFAULT_USED_PCT = 85.0

#: OPERATIONS.md:71-75 -- while a condition stays bad, say so again every 6h
#: rather than every run.
REALERT_MINUTES = 360

CONDITION_KEY = "system_health:disk_pressure"


def disk_used_pct(path: str = "/") -> tuple[float, int, int]:
    """Percent used AS `df` REPORTS IT — used/(used+available), not used/total.

    Found by dry-running against the real disk, 2026-09-21: `df -h /` said 89%
    while this returned 83.63%, so the guard printed `over_threshold: false`
    for an operator who had just been told 85% would act.

    The gap is the ~5% root reserve. `shutil.disk_usage()` reports `total` over
    ALL blocks but `free` over blocks reachable by an UNPRIVILEGED writer, so
    used/total mixes two denominators. `df` divides by what a normal process can
    actually reach, and "over 85% full" in the request means the number on the
    operator's screen — not a second, quieter number only this script can see.
    Trigger 85 now fires at df 85 instead of df ~90.5.
    """
    total, used, free = shutil.disk_usage(path)
    reachable = used + free  # df's "1K-blocks used + available"
    return (used / reachable * 100.0) if reachable else 0.0, free, total


def _fmt_gb(n: int) -> str:
    return f"{n / (1024 ** 3):.1f}GB"


def run_enforcer(*, dry_run: bool) -> dict:
    """Shell the existing enforcer. Its policy, its protections, its deletions."""
    script = ROOT / "scripts" / "disk_hygiene_enforcer.py"
    if not script.is_file():
        return {"ok": False, "error": "disk_hygiene_enforcer.py missing", "skipped": True}
    py = str(ROOT / ".venv" / "bin" / "python")
    argv = [py if Path(py).exists() else sys.executable, str(script),
            "--dry-run" if dry_run else "--apply"]
    try:
        proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True,
                              text=True, timeout=1800)
    except Exception as exc:  # noqa: BLE001 - report, never improvise a fallback
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    payload: dict = {}
    try:
        payload = json.loads(proc.stdout or "{}")
    except Exception:  # noqa: BLE001 - non-JSON output is still a result
        payload = {"raw_tail": (proc.stdout or "")[-400:]}
    # NOTE: the enforcer exits 1 while the disk is still "critical" even when its
    # own plan succeeded -- that is its alarm, not a failure. Judge on the plan.
    rel = (payload.get("releases_result") or {})
    payload["_rc"] = proc.returncode
    payload["_deleted_count"] = len(rel.get("deleted") or [])
    payload["_reclaimed"] = int(rel.get("bytes_reclaimed_est") or 0)
    payload["_plan_ok"] = bool(rel.get("ok", False))
    return payload


def notify(text: str) -> str:
    try:
        from telegram_alert import send_telegram  # noqa: PLC0415
        ok = send_telegram(text, bypass_router=True, message_class="operator_alert")
        return "accepted" if ok else "send_returned_false"
    except Exception as exc:  # noqa: BLE001 - alerting must never raise here
        return f"error:{type(exc).__name__}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--used-pct", type=float, default=DEFAULT_USED_PCT,
                    help=f"act at or above this %% used (default {DEFAULT_USED_PCT})")
    ap.add_argument("--path", default="/")
    ap.add_argument("--dry-run", action="store_true",
                    help="report and plan only; never deletes")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    used, free, total = disk_used_pct(a.path)
    over = used >= a.used_pct
    out: dict = {
        "schema": "DiskPressureGuard@v1",
        "ts": datetime.now(timezone.utc).isoformat(),
        "path": a.path,
        "used_pct": round(used, 2),
        "free": _fmt_gb(free),
        "trigger_pct": a.used_pct,
        "over_threshold": over,
        "dry_run": bool(a.dry_run),
    }

    if over:
        out["enforcer"] = run_enforcer(dry_run=a.dry_run)
        used_after, free_after, _ = disk_used_pct(a.path)
        out["used_pct_after"] = round(used_after, 2)
        out["free_after"] = _fmt_gb(free_after)
        out["reclaimed"] = _fmt_gb(max(0, free_after - free))

    # State AFTER acting: if the reclaim worked, the operator should be told the
    # condition recovered, not that it is still bad.
    final_used = out.get("used_pct_after", out["used_pct"])
    state = "PRESSURE" if final_used >= a.used_pct else "OK"
    try:
        from lib.alert_condition_state import observe  # noqa: PLC0415
        obs = observe(CONDITION_KEY, state,
                      alertable=(state == "PRESSURE"),
                      min_realert_minutes=REALERT_MINUTES,
                      extra={"used_pct": final_used, "free": out.get("free_after", out["free"])})
        out["condition"] = {"action": obs.get("action"), "notify": bool(obs.get("notify"))}
    except Exception as exc:  # noqa: BLE001
        out["condition"] = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    if out.get("condition", {}).get("notify"):
        enf = out.get("enforcer") or {}
        line = (f"💾 Disk {final_used:.1f}% used ({out.get('free_after', out['free'])} free)"
                f" — trigger {a.used_pct:.0f}%")
        if enf:
            line += (f"\nreclaimed {out.get('reclaimed', '0GB')} from "
                     f"{enf.get('_deleted_count', 0)} release(s)")
        if a.dry_run:
            line += "\n(dry run — nothing deleted)"
        out["telegram"] = notify(line)

    print(json.dumps(out, indent=2))
    # Non-zero only when we are STILL over after acting: that is the operator's
    # signal that automatic reclaim was not enough.
    return 0 if final_used < a.used_pct else 1


if __name__ == "__main__":
    raise SystemExit(main())
