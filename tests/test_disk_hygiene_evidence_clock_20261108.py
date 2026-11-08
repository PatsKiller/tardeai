"""DISK_HYGIENE_EVIDENCE_CLOCK_20261108 — LQ-20261107-1211: a retried evidence capture must not leave the apply clock behind it."""
from datetime import datetime, timedelta, timezone

import pytest

from scripts import disk_hygiene as DH
from scripts.lib import disk_hygiene_retention as SR

T0 = datetime(2026, 11, 8, 20, 17, 17, tzinfo=timezone.utc)
KEYS = ("cron", "units", "processes", "coordination", "prs", "pointers")


def _doc(at):
    sources = {}
    for k in KEYS:
        data = "" if k == "cron" else ({"references": [], "live_claims": [], "live_worklogs": []}
                                      if k == "coordination" else [])
        sources[k] = {"complete": True, "captured_at": at.isoformat(), "data": data, "sha256": SR.digest(data)}
    return {"schema": SR.SCHEMA, "offline": False, "sources": sources}


def test_future_stamped_capture_is_stale_at_the_earlier_now():
    with pytest.raises(ValueError, match="evidence_stale:cron"):
        SR.evidence_context(_doc(T0 + timedelta(seconds=150)), T0)


def test_not_before_capture_lifts_now_to_the_retry_time():
    at = T0 + timedelta(seconds=150)
    lifted = DH._not_before_capture(T0, _doc(at))
    assert lifted == at
    SR.evidence_context(_doc(at), lifted)  # no longer stale


def test_not_before_capture_never_moves_back_and_keeps_the_age_bound():
    old = _doc(T0 - timedelta(hours=3))
    assert DH._not_before_capture(T0, old) == T0
    with pytest.raises(ValueError, match="evidence_stale:cron"):
        SR.evidence_context(old, T0)
    assert DH._not_before_capture(T0, None) == T0
    assert DH._not_before_capture(T0, {"sources": {"cron": {"captured_at": "junk"}}}) == T0


def test_coordination_scan_bound_covers_today_and_still_fails_closed():
    # On the fold line the bounds are LQ-41's COORD_MAX_* (150430bbc), already above LQ-1211's 256 MiB.
    assert DH.COORD_MAX_TOTAL_BYTES >= 200 * 1024**2  # live records were 158 MiB on 2026-11-08
    assert DH.COORD_MAX_TOTAL_BYTES < 1024**3  # still a finite, fail-closed bound
    assert DH.COORD_MAX_FILE_BYTES == 64 * 1024**2  # the per-file bound is unchanged on this line
