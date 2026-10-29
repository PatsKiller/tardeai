#!/usr/bin/env python3
"""Page the moment disk crosses a threshold — do not wait for Sunday.

2026-10-27 — THIS GUARD NO LONGER RECLAIMS (AGENTS.md §24.12, §0 rule 6)
------------------------------------------------------------------------
§24.12 makes `scripts/disk_hygiene.py` (n8n lane `disk-hygiene`, or the operator
CLI) the only automated removal of release directories, and puts backups out of
scope. The enforcer this guard shelled predates §24.12 and its `--apply` now
refuses (status REFUSED_OUTSIDE_24_12, exit 77). So above the trigger the guard
asks the enforcer for its PLAN only (`--dry-run`, never `--apply`), records the
condition and pages with the governed route. Requesting `--apply` here would only
collect a refusal every 15 minutes, and would quietly resume deleting if the
enforcer were ever reverted -- two independent changes are now needed for that.
The history below is kept because it explains the trigger and the paging.

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

AUTHORITY: OPERATOR_APPROVED 2026-09-21 (trigger + paging). Deletes nothing and
requests no deletion since 2026-10-27: reclaim is the disk-hygiene lane's job
(AGENTS.md §24.12); disk_hygiene_enforcer.py is consulted for its plan only.
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


try:
    from lib.live_project_root import venv_python  # noqa: E402  (release dirs ship no .venv)
except ImportError:  # imported with scripts/lib, not scripts/, on sys.path
    from live_project_root import venv_python  # noqa: E402


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
    return f"{n / (1024**3):.1f}GB"


#: Status the enforcer reports for a refused --apply (scripts/disk_hygiene_enforcer.py REFUSED_STATUS).
#: The guard never sends --apply; this is read only so a refusal can never be mistaken for a reclaim.
ENFORCER_REFUSED = "REFUSED_OUTSIDE_24_12"
#: What the page says instead of "reclaimed": where reclaim actually lives.
GOVERNED_ROUTE_LINE = (
    "no automatic removal here (AGENTS.md §24.12): the disk-hygiene lane owns reclaim — "
    "review `python3 scripts/disk_hygiene.py --report`"
)


def run_enforcer(*, dry_run: bool = True) -> dict:
    """Shell the enforcer for its PLAN only (``--dry-run``, always). ``dry_run`` is kept for callers; ignored.

    Since 2026-10-27 the guard requests no removal: §24.12 leaves release removal to the disk-hygiene lane and
    backups to the operator. The payload is the enforcer's dry-run plan.
    """
    del dry_run  # always plan-only
    script = ROOT / "scripts" / "disk_hygiene_enforcer.py"
    if not script.is_file():
        return {"ok": False, "error": "disk_hygiene_enforcer.py missing", "skipped": True}
    py = venv_python(ROOT)
    argv = [py if Path(py).exists() else sys.executable, str(script), "--dry-run"]
    try:
        proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    except Exception as exc:  # noqa: BLE001 - report, never improvise a fallback
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    payload: dict = {}
    try:
        payload = json.loads(proc.stdout or "{}")
    except Exception:  # noqa: BLE001 - non-JSON output is still a result
        payload = {"raw_tail": (proc.stdout or "")[-400:]}
    # NOTE: the enforcer exits 1 while the disk is still "critical" even when its
    # own plan succeeded -- that is its alarm, not a failure. Judge on the plan.
    rel = payload.get("releases_result") or {}
    entries = (rel.get("deleted") or []) + (rel.get("refused_items") or [])
    payload["_rc"] = proc.returncode
    # Counted by action, never by list length: a dry-run "deleted" list holds would_delete entries.
    payload["_deleted_count"] = sum(1 for e in entries if e.get("action") == "deleted")
    payload["_would_remove_count"] = sum(1 for e in entries if e.get("action") in ("would_delete", "refused"))
    payload["_reclaimed"] = 0
    payload["_refused"] = payload.get("status") == ENFORCER_REFUSED
    payload["_plan_ok"] = bool(rel.get("ok", False))
    return payload


def notify(text: str) -> str:
    try:
        from telegram_alert import send_telegram  # noqa: PLC0415

        ok = send_telegram(text, message_class="operator_alert", priority="P1", producer="disk_pressure_guard")
        return "accepted" if ok else "send_returned_false"
    except Exception as exc:  # noqa: BLE001 - alerting must never raise here
        return f"error:{type(exc).__name__}"


#: The lane's proof-of-run. config/lane_registry.json declares this path as the
#: lane's output_signal, and evaluate_lane() derives LIVE/SLOW/SILENT from THIS
#: FILE'S MTIME -- not from the unit's exit code (AGENTS §0 rule 8: exit 0 is not
#: evidence). A lane declared without a receipt evaluates SILENT forever, which
#: is the stdout-only-monitor defect: 24 scheduled monitors in this repo compute
#: a verdict, print it to a log nobody reads, and exit 0.
RECEIPT = ROOT / "logs" / "disk_pressure_guard_receipts.jsonl"


def _write_receipt(payload: dict) -> str:
    """Append one line per run. Never raises.

    A receipt-write failure must not abort the reclaim the operator actually
    needs -- same reasoning as notify(). Report it in the payload instead.
    """
    try:
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        with RECEIPT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
        return "written"
    except Exception as exc:  # noqa: BLE001
        return f"error:{type(exc).__name__}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--used-pct",
        type=float,
        default=DEFAULT_USED_PCT,
        help=f"act at or above this %% used (default {DEFAULT_USED_PCT})",
    )
    ap.add_argument("--path", default="/")
    ap.add_argument(
        "--dry-run", action="store_true", help="report and plan only (every run is, since 2026-10-27; kept for callers)"
    )
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

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
        # Was "reclaimed" (until 2026-10-27). Signed change in free space observed across the plan-only enforcer
        # call -- NOT a reclaim: this guard removes nothing (AGENTS.md §24.12), so a nonzero value is unrelated
        # activity on the host (writes, other cleaners), never this run's work.
        out["free_space_delta_observed_gb"] = round((free_after - free) / (1024**3), 2)

    # State measured AFTER the plan call: if free space recovered by any means, the
    # operator should be told the condition recovered, not that it is still bad.
    final_used = out.get("used_pct_after", out["used_pct"])
    state = "PRESSURE" if final_used >= a.used_pct else "OK"
    try:
        from lib.alert_condition_state import observe  # noqa: PLC0415

        obs = observe(
            CONDITION_KEY,
            state,
            alertable=(state == "PRESSURE"),
            min_realert_minutes=REALERT_MINUTES,
            extra={"used_pct": final_used, "free": out.get("free_after", out["free"])},
        )
        out["condition"] = {"action": obs.get("action"), "notify": bool(obs.get("notify"))}
    except Exception as exc:  # noqa: BLE001
        out["condition"] = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    # 2026-10-27: this guard removes nothing and requests no removal (AGENTS.md §24.12).
    out["removal"] = "none (AGENTS.md §24.12: the disk-hygiene lane owns reclaim)"
    if out.get("condition", {}).get("notify"):
        enf = out.get("enforcer") or {}
        line = f"💾 Disk {final_used:.1f}% used ({out.get('free_after', out['free'])} free) — trigger {a.used_pct:.0f}%"
        line += f"\n{GOVERNED_ROUTE_LINE}"
        if enf and not (enf.get("skipped") or enf.get("error")):
            line += f"\nenforcer plan (report only): {enf.get('_would_remove_count', 0)} old release(s) listed"
        out["telegram"] = notify(line)

    out["receipt"] = _write_receipt(out)
    print(json.dumps(out, indent=2))
    # Exit 0 whenever the guard DID ITS JOB, even if the disk is still over the
    # threshold. Returning 1 for "still over" made systemd mark the unit failed
    # on a run that worked perfectly -- it reclaimed, it paged, it wrote its
    # receipt -- and made a genuine crash indistinguishable from normal
    # operation. That is the same three-way collapse as
    # pipeline_freshness_monitor._age_days_table returning None for "absent",
    # "errored" and "empty" alike, which cost ~1,800 false pages a day.
    #
    # The operator signal for "reclaim was not enough" is the Telegram alert and
    # the receipt, both of which already fired. The exit code's only job is to
    # say whether the PROCESS succeeded (AGENTS §0 rule 8: exit 0 is not
    # evidence of work -- so it must not be overloaded as evidence of state).
    enf = out.get("enforcer") or {}
    if enf.get("skipped") or enf.get("error"):
        return 1  # the enforcer could not run: a real failure
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
