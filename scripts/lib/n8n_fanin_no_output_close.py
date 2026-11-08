"""Close stale NO_OUTPUT breach incidents in the n8n incident fan-in (LQ-20261107-456).

The breach detector writes one OPEN row per lane+kind per UTC day (breach_id hashes the day) and never writes
a CLEARED row. A lane that breached on day D and recovered is simply not re-emitted on day D+1, so its row
stayed "latest" until the 48 h window dropped it: open incidents grew 266 -> 269 while lanes had resumed output.

Rule (pure, reads nothing): a NO_OUTPUT row is superseded when the detector's own receipt proves a FRESH run on
a later UTC day than the row. That run evaluated the lane and would have re-emitted the breach had it
persisted. A stalled detector (no fresh ok_at) closes nothing: silence then proves nothing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

DETECTOR_FRESH_H = 3.0
KINDS = frozenset({"NO_OUTPUT"})  # lane-level detect(); freshness/starvation checks are gated by slow-check cadence


def _instant(value):
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def detector_ran_since(detector_latest, row_detected_at, now: datetime) -> bool:
    """True when the detector's latest receipt is under 3 h old AND falls on a later UTC day than the row."""
    ok_at = _instant((detector_latest or {}).get("ok_at")) if isinstance(detector_latest, dict) else None
    row_at = _instant(row_detected_at)
    if ok_at is None or row_at is None:
        return False
    if not timedelta(0) <= now - ok_at <= timedelta(hours=DETECTOR_FRESH_H):
        return False
    return ok_at.astimezone(timezone.utc).date() > row_at.astimezone(timezone.utc).date()


def superseded(row: dict, detector_latest, now: datetime) -> bool:
    """True when this OPEN breach row is a NO_OUTPUT the detector has since stopped re-emitting."""
    if str(row.get("kind") or "") not in KINDS or row.get("state") != "OPEN":
        return False
    if row.get("authority") != "READ_ONLY_ADVISORY":  # only the detector's rows; heartbeat-watch rows clear themselves
        return False
    return detector_ran_since(detector_latest, row.get("detected_at"), now)
