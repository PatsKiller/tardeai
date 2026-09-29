"""Closed sessions serve the last options snapshot. The regular session does not."""
from datetime import datetime, timedelta, timezone

from scripts import options_engine as oe


NOW = datetime(2026, 9, 29, 4, 41, tzinfo=timezone.utc)
OLD = {"generated_at": (NOW - timedelta(hours=4)).isoformat(), "proposals": []}
FRESH = {"generated_at": (NOW - timedelta(minutes=2)).isoformat(), "proposals": []}


def test_closed_session_serves_an_old_snapshot():
    assert oe.proposal_cache_serves(OLD, now=NOW, session="CLOSED") is True
    assert oe.proposal_cache_serves(OLD, now=NOW, session="AFTER_HOURS") is True
    assert oe.proposal_cache_serves(OLD, now=NOW, session="PRE_MARKET") is True
    assert oe.proposal_cache_serves(OLD, now=NOW, session="WEEKEND") is True


def test_regular_session_rebuilds_when_the_snapshot_is_past_ten_minutes():
    assert oe.proposal_cache_serves(OLD, now=NOW, session="REGULAR") is False
    assert oe.proposal_cache_serves(FRESH, now=NOW, session="REGULAR") is True


def test_unknown_session_keeps_the_ten_minute_rule():
    assert oe.proposal_cache_serves(OLD, now=NOW, session=None) is False
    assert oe.proposal_cache_serves(FRESH, now=NOW, session=None) is True


def test_force_always_rebuilds():
    assert oe.proposal_cache_serves(FRESH, now=NOW, session="CLOSED", force=True) is False
    assert oe.proposal_cache_serves({}, now=NOW, session="CLOSED") is False
