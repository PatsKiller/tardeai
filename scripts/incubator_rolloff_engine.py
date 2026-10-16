#!/usr/bin/env python3
"""incubator_rolloff_engine.py — Roll off stale or failed incubator entries.

Run daily on trading days (6 PM). Marks symbols as ROLLED_OFF.
Does NOT delete rows.

Usage:
    .venv/bin/python scripts/incubator_rolloff_engine.py --dry-run    # offline plan: no env, DB, telemetry or writes
    .venv/bin/python scripts/incubator_rolloff_engine.py --preview    # READ ONLY DB preview of what --apply would do
    .venv/bin/python scripts/incubator_rolloff_engine.py --apply

n8n shadow wave LD-W1 (2026-10-15): an explicit ``--dry-run`` returns an offline plan before the DB import, the env
load, pipeline telemetry and any file write, and wins over ``--apply`` (before this change ``--dry-run`` opened a
DB session and ``--dry-run --apply`` COMMITTED). The old DB-reading preview is ``--preview`` on a READ ONLY session.
A real ``--apply`` run writes LaneRunReceipt@v1 ``<state_root>/data/runtime/incubator-rolloff-engine_last.json``
(``ok_at`` advances only on success).
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

LANE_ID = "incubator-rolloff-engine"

if __name__ == "__main__" and "--dry-run" in sys.argv[1:]:
    print(f"DRY-RUN {LANE_ID}: would evaluate ACTIVE incubator_universe rows, mark stale/failed entries ROLLED_OFF "
          "with one incubator_events row each (--apply) and write a LaneRunReceipt; no env, DB, telemetry or writes")
    raise SystemExit(0)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn  # noqa: E402

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass

log = logging.getLogger("incubator_rolloff_engine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

ACTIVE_INCUBATOR_QUERY = """
SELECT id, symbol, strategy_id, baseline_score, latest_score, best_score,
       rvol_latest, catalyst, catalyst_verified,
       days_active, last_seen_at, status, lifecycle_state
FROM incubator_universe
WHERE status = 'ACTIVE'
ORDER BY symbol
"""

RECENT_EVENTS_QUERY = """
SELECT event_type
FROM incubator_events
WHERE symbol = %s AND strategy_id = %s
ORDER BY created_at DESC
LIMIT 3
"""

ROLLOFF_UPDATE = """
UPDATE incubator_universe SET
    status = 'ROLLED_OFF',
    lifecycle_state = 'ROLLED_OFF',
    rolloff_reason = %s,
    updated_at = NOW()
WHERE id = %s
"""

EVENT_INSERT = """
INSERT INTO incubator_events (symbol, strategy_id, event_type, reason_codes, old_score, new_score, payload)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


def check_stale(inc):
    """Not seen in latest scan for > 7 calendar days (approx 5 trading days)."""
    last_seen = inc.get("last_seen_at")
    if not last_seen:
        return True, "never_seen_in_scan"
    now = datetime.now(timezone.utc)
    if hasattr(last_seen, "tzinfo") and last_seen.tzinfo is None:
        from datetime import timezone as tz
        last_seen = last_seen.replace(tzinfo=tz.utc)
    delta = (now - last_seen).days
    if delta > 7:
        return True, f"not_seen_for_{delta}_days"
    return False, None


def check_consecutive_degraded(conn, symbol, strategy_id):
    """Check if last 3 events are all DEGRADED."""
    cur = conn.cursor()
    cur.execute(RECENT_EVENTS_QUERY, [symbol, strategy_id or ""])
    rows = cur.fetchall()
    if len(rows) < 3:
        return False, None
    events = [r[0] for r in rows]
    if all(e == "DEGRADED" for e in events):
        return True, "3_consecutive_degraded_events"
    return False, None


def check_no_catalyst_no_volume(inc):
    """No catalyst and low volume."""
    rvol = float(inc.get("rvol_latest") or 0)
    catalyst = inc.get("catalyst")
    if rvol < 1.0 and not catalyst:
        return True, f"no_catalyst_rvol={rvol:.2f}"
    return False, None


def evaluate_rolloff(conn, inc):
    """Evaluate all roll-off criteria. Return (should_rolloff, reasons)."""
    reasons = []

    stale, reason = check_stale(inc)
    if stale:
        reasons.append(reason)

    degraded, reason = check_consecutive_degraded(
        conn, inc["symbol"], inc.get("strategy_id") or ""
    )
    if degraded:
        reasons.append(reason)

    no_catalyst, reason = check_no_catalyst_no_volume(inc)
    if no_catalyst:
        reasons.append(reason)

    return len(reasons) > 0, reasons


def rolloff_ticker(conn, inc, reasons, dry_run=False):
    """Mark a ticker as ROLLED_OFF."""
    symbol = inc["symbol"]
    strategy_id = inc.get("strategy_id") or ""
    rolloff_reason = "; ".join(reasons)
    old_score = float(inc.get("latest_score") or inc.get("baseline_score") or 0)

    if dry_run:
        log.info("[DRY-RUN] ROLL-OFF %s strategy=%s score=%.1f reasons=%s",
                 symbol, strategy_id, old_score, reasons)
        return

    cur = conn.cursor()

    # Update status
    cur.execute(ROLLOFF_UPDATE, [rolloff_reason, inc["id"]])

    # Write event
    payload = {
        "rolloff_reasons": reasons,
        "final_score": old_score,
        "best_score": float(inc.get("best_score") or 0),
        "days_active": inc.get("days_active") or 0,
        "rvol_latest": float(inc.get("rvol_latest") or 0),
    }
    cur.execute(EVENT_INSERT, [
        symbol, strategy_id, "ROLLED_OFF",
        json.dumps(reasons),
        old_score, None,
        json.dumps(payload),
    ])


def main():
    parser = argparse.ArgumentParser(description="Incubator roll-off engine")
    parser.add_argument("--dry-run", action="store_true", help="offline plan (handled before any import); wins")
    parser.add_argument("--preview", action="store_true", help="READ ONLY DB preview of the roll-offs")
    parser.add_argument("--apply", action="store_true", help="Write changes to DB")
    args = parser.parse_args()
    args.dry_run = bool(args.dry_run or args.preview)
    if args.dry_run:
        args.apply = False

    if not args.dry_run and not args.apply:
        log.error("Must specify --dry-run, --preview or --apply")
        sys.exit(1)

    conn = get_conn()
    if args.dry_run:
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(conn)  # the preview cannot write even if a write statement were reached
    try:
        cur = conn.cursor()
        cur.execute(ACTIVE_INCUBATOR_QUERY)
        cols = [d[0] for d in cur.description]
        active = [dict(zip(cols, row)) for row in cur.fetchall()]
        log.info("Evaluating %d active incubator entries for roll-off", len(active))

        rolled_off = 0
        still_active = 0

        for inc in active:
            should_rolloff, reasons = evaluate_rolloff(conn, inc)
            if should_rolloff:
                rolloff_ticker(conn, inc, reasons, dry_run=args.dry_run)
                rolled_off += 1
            else:
                still_active += 1

        if args.apply:
            conn.commit()
            log.info("Committed changes to database")
        else:
            conn.rollback()

        log.info("=== SUMMARY ===")
        log.info("Rolled off:    %d", rolled_off)
        log.info("Still active:  %d", still_active)
        log.info("Total checked: %d", len(active))
        log.info("Mode:          %s", "DRY-RUN" if args.dry_run else "APPLIED")
        return {"rolled_off": rolled_off, "still_active": still_active, "checked": len(active),
                "mode": "preview" if args.dry_run else "apply"}

    except Exception:
        conn.rollback()
        log.exception("incubator_rolloff_engine failed")
        sys.exit(1)
    finally:
        conn.close()


def _apply_with_receipt() -> int:
    """A real --apply run: run main() and write the lane receipt whatever the outcome (never from a preview)."""
    from lib.lane_last_receipt import now_iso, write_lane_receipt

    started = now_iso()
    try:
        summary = main()
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        write_lane_receipt(LANE_ID, ok=rc == 0, exit_code=rc, started_at=started, script="incubator_rolloff_engine.py",
                           summary={"completed": rc == 0}, output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {"dependency_unavailable": 1}})
        raise
    except Exception as exc:
        write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started, script="incubator_rolloff_engine.py",
                           error=type(exc).__name__, output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {"dependency_unavailable": 1}})
        raise
    write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started, script="incubator_rolloff_engine.py",
                       summary=summary or {}, output=lane_output(summary or {}))
    return 0


def lane_output(summary: dict) -> dict:
    """LaneRunReceipt@v2 output fields (n8n expected_output, unit: incubator roll-offs recorded = incubator_events
    rows, one per rolled-off entry). attempted = active entries checked; nothing to roll off = ``no_new_input``."""
    rolled, checked = int(summary.get("rolled_off") or 0), int(summary.get("checked") or 0)
    return {"produced_count": rolled, "attempted_count": max(checked, rolled), "skipped_reasons": {},
            "empty_reason": None if rolled else "no_new_input"}


if __name__ == "__main__":
    with PipelineRun("incubator_rolloff_engine") as _run:
        if "--apply" in sys.argv[1:] and "--preview" not in sys.argv[1:]:
            sys.exit(_apply_with_receipt())
        main()

