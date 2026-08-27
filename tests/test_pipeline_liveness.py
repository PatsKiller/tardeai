"""PipelineLiveness@v1 — the monitor that would have caught a 17-day outage.

The CIO evidence gate blocked 54 of 55 runs for 17 continuous days and nothing
raised an alarm. Every block was recorded; no monitor watched the record. What
these tests pin is the one distinction that makes such a monitor useful: silence
with no work attempted is quiet, silence *despite* work is a fault.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.lib.pipeline_liveness import (
    LIVE,
    QUIET,
    STARVED,
    UNKNOWN,
    Lane,
    _parse_ts,
    evaluate,
)


def _lane(produced: int, attempted: int, *, min_expected: int = 1) -> Lane:
    return Lane(
        name="probe",
        window_hours=24,
        min_expected=min_expected,
        describe="test lane",
        probe=lambda since: (produced, attempted, "memory"),
    )


def test_work_in_nothing_out_is_a_fault_not_silence():
    """The 17-day shape: 55 runs entered the lane, 1 came out."""
    report = evaluate([_lane(produced=0, attempted=55)])
    assert report.lanes[0]["status"] == STARVED
    assert report.findings, "a starved lane must surface as a finding"


def test_no_work_and_no_output_is_quiet_not_a_fault():
    """A weekend with nothing to do must not page anyone.

    Without this distinction the monitor cries wolf on every idle window and
    gets muted — which is the same outcome as having no monitor.
    """
    report = evaluate([_lane(produced=0, attempted=0)])
    assert report.lanes[0]["status"] == QUIET
    assert not report.findings


def test_a_producing_lane_is_live():
    report = evaluate([_lane(produced=3, attempted=3)])
    assert report.lanes[0]["status"] == LIVE
    assert not report.findings


def test_a_lane_below_its_floor_while_working_is_starved():
    report = evaluate([_lane(produced=0, attempted=10, min_expected=5)])
    assert report.lanes[0]["status"] == STARVED


def test_a_broken_probe_is_unknown_never_healthy():
    """An unreadable source must never be reported as fine.

    Treating a failed probe as LIVE would recreate the exact blindness: the
    monitor says healthy because it cannot see.
    """
    def explode(since):
        raise OSError("store unreadable")

    lane = Lane(name="broken", window_hours=24, min_expected=1,
                describe="unreadable", probe=explode)
    report = evaluate([lane])

    assert report.lanes[0]["status"] == UNKNOWN
    assert report.findings, "an unreadable lane must be a finding, not silence"


def test_report_is_advisory_and_takes_no_action():
    result = evaluate([_lane(produced=1, attempted=1)]).to_dict()
    assert result["authority"] == "READ_ONLY_ADVISORY"
    assert result["financial_action"] is False


def test_unparseable_timestamps_are_none_never_now():
    """Defaulting a bad timestamp to now makes every stale record look fresh."""
    assert _parse_ts("not a timestamp") is None
    assert _parse_ts(None) is None
    assert _parse_ts("") is None

    # The ET format the repricer writes, which fromisoformat cannot read.
    parsed = _parse_ts("2026-08-27 14:45:02 ET")
    assert parsed is not None and parsed.tzinfo is not None

    aware = _parse_ts("2026-08-27T18:45:02+00:00")
    assert aware == datetime(2026, 8, 27, 18, 45, 2, tzinfo=timezone.utc)


def test_naive_timestamps_are_read_as_utc_not_local():
    parsed = _parse_ts("2026-08-27T18:45:02")
    assert parsed is not None and parsed.tzinfo == timezone.utc


def test_window_excludes_older_records():
    """A lane that produced last month is not producing now."""
    seen = {}

    def probe(since):
        seen["since"] = since
        return (0, 0, "memory")

    lane = Lane(name="w", window_hours=4, min_expected=1, describe="d", probe=probe)
    evaluate([lane], now=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc))

    assert seen["since"] == datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)
    assert seen["since"] == datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc) - timedelta(hours=4)
