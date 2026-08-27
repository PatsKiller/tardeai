"""Tests for the CIO snapshot staleness marker (audit finding M5).

docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md: _get_snapshot()'s cache-first
fast paths read cio_snapshot.json directly with no staleness check at all,
while the live-collect fallback enforces max_age_s=60 — so the CIO desk
could silently render an arbitrarily stale cached position view with no
staleness marker propagated downstream. _stamp_freshness() closes that gap.

Pure where possible: _stamp_freshness takes a dict and an optional Path, no
DB or live broker call needed to exercise its logic directly.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.cio_desk_synthesis import _stamp_freshness, STALE_SNAPSHOT_AGE_S  # noqa: E402


def test_fresh_collect_source_has_zero_age_and_not_stale():
    snap = _stamp_freshness({"domains": {}}, source="fresh_collect")
    fresh = snap["_freshness"]
    assert fresh["source"] == "fresh_collect"
    assert fresh["age_s"] == 0.0
    assert fresh["stale"] is False


def test_recent_file_is_not_stale(tmp_path):
    p = tmp_path / "cio_snapshot.json"
    p.write_text("{}")
    snap = _stamp_freshness({"domains": {}}, source="cached_file", snap_path=p)
    fresh = snap["_freshness"]
    assert fresh["source"] == "cached_file"
    assert fresh["age_s"] < 5
    assert fresh["stale"] is False


def test_old_file_is_stale(tmp_path):
    """The actual gap this audit found: a cached file well past the 60s bar
    the live-collect fallback enforces must now be marked stale."""
    p = tmp_path / "cio_snapshot.json"
    p.write_text("{}")
    old = time.time() - (STALE_SNAPSHOT_AGE_S + 120)
    import os
    os.utime(p, (old, old))
    snap = _stamp_freshness({"domains": {}}, source="cached_file", snap_path=p)
    fresh = snap["_freshness"]
    assert fresh["age_s"] > STALE_SNAPSHOT_AGE_S
    assert fresh["stale"] is True


def test_boundary_age_matches_the_same_60s_bar_as_live_collect():
    """Consistency check: the marker's threshold must match max_age_s=60,
    the bar the live-collect fallback already enforces elsewhere in this
    file — a different threshold here would make 'stale' mean two things."""
    assert STALE_SNAPSHOT_AGE_S == 60


def test_missing_file_marks_stale_with_no_age():
    """A snap_path that can't be stat()'d (deleted between exists() check
    and stamp, permission error, etc.) must fail closed to stale=True, not
    silently claim freshness it can't verify."""
    snap = _stamp_freshness({"domains": {}}, source="cached_file",
                            snap_path=Path("/nonexistent/cio_snapshot.json"))
    fresh = snap["_freshness"]
    assert fresh["age_s"] is None
    assert fresh["stale"] is True


def test_non_dict_input_is_returned_unchanged():
    """_stamp_freshness must never raise on an unexpected type — every
    _get_snapshot() return path funnels through it."""
    assert _stamp_freshness([], source="x") == []
    assert _stamp_freshness(None, source="x") is None


def test_live_collect_60s_bar_source_is_not_marked_stale_by_default():
    """The final fallback (get_cio_snapshot(max_age_s=60)) already enforces
    its own freshness contract internally — stamped as not-stale by
    definition of that contract, not because this function re-verified it."""
    snap = _stamp_freshness({"domains": {}}, source="live_collect_60s_bar")
    assert snap["_freshness"]["stale"] is False


def test_get_snapshot_output_always_carries_a_freshness_marker():
    """Live smoke test: whatever _get_snapshot() actually returns in this
    environment right now, every return path must carry _freshness — no
    silent unmarked path should remain reachable."""
    from lib.cio_desk_synthesis import _get_snapshot
    snap = _get_snapshot()
    if snap:  # an empty {} (total collection failure) has nothing to stamp
        assert "_freshness" in snap, (
            "a _get_snapshot() return path is missing the freshness stamp "
            "this fix is supposed to guarantee on every non-empty result")
