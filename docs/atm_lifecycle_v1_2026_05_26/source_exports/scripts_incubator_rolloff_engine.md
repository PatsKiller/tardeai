# Source Export: scripts/incubator_rolloff_engine.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/incubator_rolloff_engine.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `56d6279942a0a0e065fb74e23acb52b82dd4371196736453d64755663c6efca8` |
| **File Size** | 6276 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""incubator_rolloff_engine.py — Roll off stale or failed incubator entries.

Run daily on trading days (6 PM). Marks symbols as ROLLED_OFF.
Does NOT delete rows.

Usage:
    .venv/bin/python scripts/incubator_rolloff_engine.py --dry-run
    .venv/bin/python scripts/incubator_rolloff_engine.py --apply
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn

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
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing to DB")
    parser.add_argument("--apply", action="store_true", help="Write changes to DB")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        log.error("Must specify --dry-run or --apply")
        sys.exit(1)

    conn = get_conn()
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

    except Exception:
        conn.rollback()
        log.exception("incubator_rolloff_engine failed")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    with PipelineRun("incubator_rolloff_engine") as _run:
        main()
```
