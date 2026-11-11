#!/usr/bin/env python3
"""release_status — DEPLOYED / LIVE / VERIFIED for the release CURRENT points at (QA-GOLDEN-RULES E15, LQ-20261107-1902).

PROCESS   n8n lane ``release-status``, nightly 20:05 ET, LaneRunReceipt@v2 under --apply. The activation (promote)
          also calls it, report only, so a promote logs DEPLOYED, not LIVE, while any unit lags.
CONTRACT  target = the release CURRENT resolves to. Every running tradeai-* / portfolio-server user unit bound to a
          release must have ``/proc/<pid>/cwd`` inside the target: all do = LIVE, else DEPLOYED. LIVE + every
          acceptance probe PASS = VERIFIED. Exit 0 LIVE or VERIFIED, 2 DEPLOYED, 3 UNDETERMINED.
HEAL      none, by design: this reports and prints the exact ``systemctl --user restart <unit>`` line per lagging
          unit. It never restarts anything (the page-only units are page-only because a restart is a deliberate act).
          Escalation under --apply: one ``system_health`` alert_events row per target+lagging-set per cooldown.

Dry run is the default: read-only, nothing written, nothing escalated. ``--apply`` escalates when not LIVE and
writes the receipt. MBI_BEHAVIOR = 0: no broker, no order, no restart.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib import release_status as rsl  # noqa: E402

LANE_ID = "release-status"
ESCALATION_SOURCE = "release_status.py"
ESCALATION_COOLDOWN_H = 20  # one page per night; a retry inside the same wall never doubles it


def signature(rs: rsl.ReleaseStatus) -> str:
    """Identity of what is wrong: same target and same lagging set = same page."""
    raw = rs.target_name + "|" + ",".join(sorted(rs.lagging + rs.unknown)) + "|" + rs.status
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _connect(read_only: bool):
    import psycopg2  # noqa: PLC0415

    kwargs: dict[str, Any] = {"dbname": os.getenv("DB_NAME", "trade_ai"), "user": os.getenv("DB_USER", "johnclaw"),
                              "host": os.getenv("DB_HOST", "/var/run/postgresql"), "connect_timeout": 10}
    if os.getenv("DB_PORT"):
        kwargs["port"] = os.getenv("DB_PORT")
    if os.getenv("DB_PASSWORD"):
        kwargs["password"] = os.getenv("DB_PASSWORD")
    if read_only:
        kwargs["options"] = "-c default_transaction_read_only=on"
    return psycopg2.connect(**kwargs)


def _recently_alerted(sig: str) -> bool:
    conn = _connect(read_only=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM alert_events WHERE source_script = %s AND alert_type = 'system_health' "
                "AND parsed_payload->>'signature' = %s AND created_at > now() - make_interval(hours => %s) LIMIT 1",
                (ESCALATION_SOURCE, sig, ESCALATION_COOLDOWN_H))
            return cur.fetchone() is not None
    finally:
        conn.close()


def _alert_default(rs: rsl.ReleaseStatus, sig: str) -> bool:
    from alert_event_writer import save_alert_event  # noqa: PLC0415

    return save_alert_event(
        alert_type="system_health",
        raw_text=rsl.alert_text(rs),
        severity="warning",
        source_script=ESCALATION_SOURCE,
        parsed_payload={"kind": "release_not_live", "signature": sig, "status": rs.status, "target": rs.target_name,
                        "lagging": rs.lagging, "unknown": rs.unknown,
                        "restart_commands": [u.restart_command for u in rs.units if u.on_target is not True]},
    ) is not None


def escalate(rs: rsl.ReleaseStatus, *, alert: Callable[[rsl.ReleaseStatus, str], bool] = _alert_default,
             recent: Callable[[str], bool] = _recently_alerted) -> dict[str, Any]:
    """Alert on DEPLOYED or UNDETERMINED (anything that is not LIVE/VERIFIED), once per signature per cooldown."""
    if rs.status in (rsl.LIVE, rsl.VERIFIED):
        return {"needed": False, "sent": False}
    sig = signature(rs)
    try:
        if recent(sig):
            return {"needed": True, "sent": False, "suppressed_cooldown": True, "signature": sig}
        return {"needed": True, "sent": bool(alert(rs, sig)), "signature": sig}
    except Exception as exc:  # noqa: BLE001 - an alert that cannot be written is a failed run, never a silent one
        return {"needed": True, "sent": False, "signature": sig, "error": type(exc).__name__}


def log_line(rs: rsl.ReleaseStatus) -> str:
    """One line for the activation log: DEPLOYED (naming the laggards) or LIVE/VERIFIED."""
    if rs.status == rsl.DEPLOYED:
        names = ", ".join(rs.lagging + rs.unknown)
        return f"RELEASE {rs.target_name} is DEPLOYED, not LIVE: {names} still on another release (restart lines: scripts/release_status.py)"
    return f"RELEASE {rs.target_name} is {rs.status}: {rs.reason}"


def exit_code(rs: rsl.ReleaseStatus) -> int:
    return {rsl.VERIFIED: 0, rsl.LIVE: 0, rsl.DEPLOYED: 2}.get(rs.status, 3)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--json", action="store_true", help="machine output")
    ap.add_argument("--log-line", action="store_true", help="print only the one-line status (the activation uses this)")
    ap.add_argument("--no-probes", action="store_true", help="skip the acceptance probes (status stops at LIVE)")
    ap.add_argument("--releases-base", default=None, help="override the releases directory (tests)")
    ap.add_argument("--apply", action="store_true", help="escalate when not LIVE and write the lane receipt")
    ap.add_argument("--report", action="store_true",
                    help="dry run for the n8n dispatcher: no writes, exit 0 whenever the release was judged "
                         "(DEPLOYED included), non-zero only when it could not be (the --apply ok logic)")
    args = ap.parse_args(argv)
    started = datetime.now(timezone.utc).isoformat()
    kwargs: dict[str, Any] = {"run_probes": not args.no_probes}
    if args.releases_base:
        kwargs["releases_base"] = args.releases_base
    rs = rsl.compute(**kwargs)
    esc = escalate(rs) if args.apply else {"needed": rs.status not in (rsl.LIVE, rsl.VERIFIED), "sent": False,
                                           "dry_run": True}
    if args.log_line:
        print(log_line(rs))
    elif args.json:
        print(json.dumps({**rs.to_dict(), "escalation": esc}, indent=1, sort_keys=True))
    else:
        print(rsl.human(rs))
    if args.apply:
        try:
            from scripts.lib.lane_last_receipt import write_lane_receipt  # noqa: PLC0415
        except ImportError:
            from lib.lane_last_receipt import write_lane_receipt  # type: ignore[no-redef]  # noqa: PLC0415
        # The lane ran correctly when it could judge and (if it had to) alert: a DEPLOYED verdict that was paged is
        # a successful run with a DEGRADED verdict, never green-washed; an alert that failed to write is a failure.
        judged = rs.status != rsl.UNDETERMINED
        ok = judged and not esc.get("error") and (not esc.get("needed") or esc.get("sent") or esc.get("suppressed_cooldown"))
        write_lane_receipt(
            LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=started, script=__file__,
            summary={"verdict": {"VERIFIED": "OK", "LIVE": "OK", "DEPLOYED": "DEGRADED"}.get(rs.status, "UNVERIFIABLE"),
                     "release_status": rs.status, "target": rs.target_name, "lagging": rs.lagging,
                     "unknown": rs.unknown, "units": len(rs.units), "escalation": esc,
                     "probes": {p.name: p.status for p in rs.probes}},
            error=None if ok else (esc.get("error") or rs.reason or "not_judged"),
            produced_count=len(rs.units), attempted_count=len(rs.units),
            empty_reason=None if rs.units else "no_bound_units",
        )
        return 0 if ok else 1
    if args.report:
        # The executor maps every non-zero exit to RUN_FAILED: a DEPLOYED-not-LIVE verdict is a judged result (the
        # DEGRADED verdict is computed from the output), so only UNDETERMINED / an escalation error fails the run.
        return 0 if rs.status != rsl.UNDETERMINED and not esc.get("error") else 1
    return exit_code(rs)


if __name__ == "__main__":
    sys.exit(main())
