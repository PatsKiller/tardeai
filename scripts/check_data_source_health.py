#!/usr/bin/env python3
"""Report data sources whose EFFECTIVE health is not healthy while something is
scheduled to feed them. Read-only.

WHY
---
On 2026-09-13 the data_source_health table said `yahoo_finance` was "healthy".
Its last success was 2026-08-24 -- twenty days earlier. The status column is
written once by report_source() and then sits there; nothing ever ages it. In
the same table `brave_search`, `fred` and `alpha_vantage` had been "unknown"
since the row was seeded, because no caller was wired, while Brave alone made
163 governed calls that month. `finnhub` read "error" (HTTP 401) for seven
weeks while four scheduled callers still tried it first every run.

The health agent and the API read that raw column and scored the platform 75.

This gate reads the same table through lib/data_source_health_view, which gives
a row the status it is ENTITLED to right now: healthy only if it succeeded
inside its registry window (config/data_source_authority.json
`stale_after_hours`), otherwise unknown -- or error if a failure is newer than
the last success. A source that is not healthy AND has a scheduled caller is a
finding: a job exists to feed it and either did not run or failed. A source
with no scheduled caller is idle, listed, and not alerted.

STATES (effective)
------------------
    healthy   succeeded inside its window, nothing failed since
    error     a failure is newer than the last success
    unknown   never reported, or the last success aged out of its window

USAGE
-----
    python scripts/check_data_source_health.py            # human-readable
    python scripts/check_data_source_health.py --json
    python scripts/check_data_source_health.py --alert    # notify on change
    python scripts/check_data_source_health.py --dry-run  # read + print; write nothing

EXIT CODES
----------
    0  every source with a scheduled caller is effectively healthy
    1  at least one such source is not
    2  could not run (no registry, no database)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.data_source_health_view import (  # noqa: E402
    HEALTHY,
    SCHEDULED_CALLERS,
    load_registry,
    not_healthy_with_scheduled_caller,
    view_rows,
)

STATE_PATH = Path.home() / ".local/state/tradeai/data_source_health_last_alert.json"

SCHEMA = "DataSourceHealthReport@v1"
RECEIPT_NAME = "data_source_health_last_run.json"

NO_CONSUMER_REASON = (
    "this IS an availability gate; an operator or a scheduled run invokes it and reads "
    "the report, nothing imports it. Same shape as check_expected_services.py."
)


def _db_env() -> dict:
    """Same resolution as data_plausibility_monitor: the runtime env file, then the process env."""
    env = {}
    runtime = Path("/run/user/1000/tradeai/env")
    if runtime.exists():
        for line in runtime.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            m = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
            if m:
                env[m.group(1)] = m.group(2).strip("\"'")
    for k in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def _read_ledger(env: dict) -> list[dict]:
    """SELECT the whole table in a READ-ONLY session. psycopg2 is imported lazily so
    the pure parts of this module (and its tests) never need the driver."""
    import psycopg2  # noqa: PLC0415
    import psycopg2.extras  # noqa: PLC0415

    conn = psycopg2.connect(
        host=env.get("DB_HOST", "localhost"),
        port=env.get("DB_PORT", 5432),
        dbname=env["DB_NAME"],
        user=env["DB_USER"],
        password=env.get("DB_PASSWORD", ""),
        connect_timeout=5,
        application_name="check_data_source_health",
    )
    try:
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT source_key, status, last_success_at, last_failure_at, last_row_count, "
            "failure_count, last_error, degraded, max_stale_minutes, updated_at "
            "FROM data_source_health ORDER BY source_key"
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def classify(rows: list[dict], now: datetime, registry: dict) -> tuple[list[dict], list[dict]]:
    """(all viewed rows, the alert set). Pure -- rows are injected."""
    viewed = view_rows(rows, now, registry)
    return viewed, not_healthy_with_scheduled_caller(viewed)


def _describe(r: dict) -> str:
    age = r.get("age_minutes")
    win_h = float(r.get("window_minutes") or 0) / 60.0
    if age is None:
        when = "never succeeded"
    else:
        when = f"last success {age / 60.0:.1f}h ago (window {win_h:.0f}h)"
    bits = [when]
    if r.get("decayed"):
        bits.append("table still says healthy")
    if r.get("status") != HEALTHY and r.get("last_error"):
        bits.append(f"last_error: {str(r['last_error'])[:90]}")
    callers = SCHEDULED_CALLERS.get(r.get("source_key") or "", [])
    if callers:
        bits.append("fed by " + "; ".join(f"{c['script']} [{c['cron']}]" for c in callers[:2]))
    return " -- ".join(bits)


def _write_run_receipt(checked: int, off: int, detail: dict) -> None:
    """Prove this ran, every run, whether or not it found anything.

    The alert state file only changes when findings change, so a quiet run
    leaves no trace -- and a timer that silently stopped would look exactly like
    a clean result. config/lane_registry.json requires an output_signal that is
    a durable artifact, "not its exit code, not its log file existing", and this
    is that artifact.
    """
    path = PROJECT_ROOT / "data" / "runtime" / RECEIPT_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "ran_at": datetime.now(timezone.utc).isoformat(),
                    "checked": checked,
                    "off": off,
                    **detail,
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
    except OSError as exc:
        print(f"  receipt: could not write {path} ({exc})", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alert", action="store_true", help="notify the operator when the not-healthy set changes")
    ap.add_argument("--dry-run", action="store_true",
                    help="read and report; write no receipt, no state, no alert (AGENTS.md section 0 rule 7)")
    args = ap.parse_args()

    registry = load_registry()
    if not registry.get("domains"):
        print("ERROR: config/data_source_authority.json unreadable or has no domains", file=sys.stderr)
        return 2

    env = _db_env()
    if not env.get("DB_NAME"):
        print("ERROR: database settings unavailable", file=sys.stderr)
        return 2
    try:
        rows = _read_ledger(env)
    except Exception as exc:
        print(f"ERROR: could not read data_source_health: {exc}", file=sys.stderr)
        return 2
    if not rows:
        # An empty table is not "everything healthy". Refuse to report a clean bill.
        print("ERROR: data_source_health returned no rows -- refusing to report all-clear", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    viewed, off = classify(rows, now, registry)
    idle = [r for r in viewed if r.get("status") != HEALTHY and not r.get("scheduled_caller")]

    if args.json:
        print(json.dumps({"schema": SCHEMA, "as_of": now.isoformat(), "checked": len(viewed),
                          "off": len(off), "off_items": off, "idle_not_alerted": idle,
                          "rows": viewed}, indent=2, default=str))
    else:
        print("Data source health -- EFFECTIVE status (decayed), sources with a scheduled caller")
        print("=" * 78)
        for r in sorted(off, key=lambda x: x["source_key"]):
            print(f"  [{r['status']:<8}] {r['source_key']}")
            print(f"             {_describe(r)}")
        if not off:
            fed = sum(1 for r in viewed if r.get("scheduled_caller"))
            print(f"  all {fed} sources with a scheduled caller are effectively healthy.")
        if idle:
            print("-" * 78)
            print("  not healthy, NO scheduled caller (listed, not alerted):")
            for r in sorted(idle, key=lambda x: x["source_key"]):
                print(f"    [{r['status']:<8}] {r['source_key']} -- {_describe(r)}")
        decayed = [r["source_key"] for r in viewed if r.get("decayed")]
        if decayed:
            print("-" * 78)
            print(f"  raw column said 'healthy' but the success is outside its window: {', '.join(decayed)}")
        print("-" * 78)
        print(f"  checked={len(viewed)}  off={len(off)}  idle={len(idle)}")

    if args.dry_run:
        print("\n  dry-run: no receipt, no state, no alert written.")
        return 1 if off else 0

    _write_run_receipt(len(viewed), len(off), {
        "off_items": [f"{r['status']}:{r['source_key']}" for r in off],
        "decayed": [r["source_key"] for r in viewed if r.get("decayed")],
    })

    if args.alert:
        _alert(off)

    return 1 if off else 0


def _alert(off: list[dict]) -> None:
    """Notify only when the not-healthy set changes. Never raises."""
    fingerprint = {r["source_key"]: r["status"] for r in off}
    previous = {}
    try:
        previous = json.loads(STATE_PATH.read_text()).get("fingerprint", {})
    except (OSError, ValueError):
        pass

    if fingerprint == previous:
        print("\n  alert: suppressed -- unchanged since the last run.")
        return

    newly = [k for k in fingerprint if k not in previous]
    if not fingerprint:
        body = ("[PLATFORM_AVAILABILITY] ✅ Data sources: every source with a scheduled caller "
                "succeeded inside its window.")
    else:
        # The sentinel is what operator_alert_policy_v2 routes on -- prose is
        # not load-bearing, this token is. Without it the alert classifies as
        # job_telemetry and waits in the 4-hourly digest.
        head = (
            "[PLATFORM_AVAILABILITY] 🚨 A scheduled data source stopped reporting"
            if newly
            else "[PLATFORM_AVAILABILITY] 🚨 Data sources not healthy"
        )
        lines = [head, ""]
        for r in sorted(off, key=lambda x: x["source_key"]):
            lines.append(f"• [{r['status']}] {r['source_key']}")
            lines.append(f"    {_describe(r)}")
        if newly:
            lines += ["", "NEW since the last run: " + ", ".join(newly)]
        recovered = [k for k in previous if k not in fingerprint]
        if recovered:
            lines += ["", "Recovered: " + ", ".join(recovered)]
        lines += [
            "",
            "healthy means succeeded inside its window; the raw table column does not decay.",
            "config/data_source_authority.json declares the windows.",
        ]
        body = "\n".join(lines)

    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from telegram_alert import send_telegram

        ok = send_telegram(body, message_class="operator_alert")
        print(f"\n  alert: {'accepted' if ok else 'NOT accepted'} by the platform")
    except Exception as exc:
        print(f"\n  alert: FAILED to send ({exc}). The findings above still stand.", file=sys.stderr)
        return

    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({"fingerprint": fingerprint}, indent=2))
    except OSError as exc:
        print(f"  alert: could not record state ({exc}).", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
