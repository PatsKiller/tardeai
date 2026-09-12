"""A run that cannot finish inside its own timeout must still report.

Live evidence, 2026-09-12:

    tradeai-free-first-circulation.service  TimeoutStartSec=900
    every run since 2026-09-08 killed with Result=timeout (93 consecutive)
    wall time grew Aug 23 2m42s -> Sep 7 14m40s, then pinned at 15m00

The receipt is written after circulate_universe() returns, so a SIGTERM at 900s
wrote NOTHING: the newest receipt on disk is from 2026-09-07T14:38:14Z and
logs/free_first_circulation.log holds only run-start banners. Four days of
total outage left no durable record of a single failure, which is also what let
timer_health keep reporting healthy.

Bounding the work is not enough on its own. A partial run that always starts at
the head of the list re-grinds the same symbols forever and never reaches the
tail -- the same head-of-line defect found in incubator_proposal_promoter on
2026-09-11. The cursor is what makes successive partial runs cover the universe.
"""

from __future__ import annotations

import json

import pytest

from scripts.lib import free_first_circulation as ffc


@pytest.fixture
def fake_profiles(monkeypatch):
    profiles = [{"symbol": f"SYM{i:02d}"} for i in range(10)]

    import scripts.lib.free_first_refresh as ffr

    monkeypatch.setattr(ffr, "load_profiles", lambda _root: list(profiles), raising=False)
    return profiles


def _stub_circulate(seconds_each=0.0, seen=None):
    def _c(root, profile, **_kw):
        if seen is not None:
            seen.append(profile["symbol"])
        if seconds_each:
            import time

            time.sleep(seconds_each)
        return {
            "symbol": profile["symbol"],
            "bucket": "Hermes_resolved",
            "decision": "NO_NEW_INFO",
            "paid_dispatch_entered": 0,
            "hermes_rows_examined": 1,
            "artifacts": 1,
            "rag_attempts": 0,
            "rag_items": 0,
            "searx_queries": 0,
            "librarian_assessments": 0,
        }

    return _c


def test_no_deadline_keeps_todays_behaviour(tmp_path, monkeypatch, fake_profiles):
    monkeypatch.setattr(ffc, "circulate_symbol", _stub_circulate())
    rep = ffc.circulate_universe(tmp_path)
    assert rep["total_symbols"] == 10
    assert rep["completion"] == "COMPLETE"
    assert rep["symbols_skipped_deadline"] == 0


def test_a_deadline_stops_the_run_and_says_so(tmp_path, monkeypatch, fake_profiles):
    seen: list[str] = []
    monkeypatch.setattr(ffc, "circulate_symbol", _stub_circulate(seconds_each=0.02, seen=seen))
    rep = ffc.circulate_universe(tmp_path, deadline_seconds=0.05)
    assert rep["completion"] == "PARTIAL_DEADLINE"
    assert 0 < rep["symbols_circulated"] < 10
    assert rep["symbols_skipped_deadline"] == 10 - rep["symbols_circulated"]
    assert rep["deadline_seconds"] == 0.05
    assert rep["elapsed_seconds"] > 0
    assert len(seen) == rep["symbols_circulated"]


def test_a_partial_run_is_never_reported_as_a_complete_one(tmp_path, monkeypatch, fake_profiles):
    """The counts must not read as a healthy small universe. `total_symbols`
    described the rows produced, so a truncated run looked like a complete run
    over fewer names."""
    monkeypatch.setattr(ffc, "circulate_symbol", _stub_circulate(seconds_each=0.02))
    rep = ffc.circulate_universe(tmp_path, deadline_seconds=0.05)
    assert rep["symbols_planned"] == 10
    assert rep["symbols_planned"] > rep["symbols_circulated"]
    assert rep["completion"] != "COMPLETE"


def test_successive_partial_runs_advance_through_the_universe(
    tmp_path, monkeypatch, fake_profiles
):
    """Without a cursor, every bounded run re-grinds the head of the list and
    the tail is never examined."""
    cursor = tmp_path / "cursor.json"
    first: list[str] = []
    monkeypatch.setattr(ffc, "circulate_symbol", _stub_circulate(seconds_each=0.02, seen=first))
    ffc.circulate_universe(tmp_path, deadline_seconds=0.05, cursor_path=cursor)

    second: list[str] = []
    monkeypatch.setattr(ffc, "circulate_symbol", _stub_circulate(seconds_each=0.02, seen=second))
    ffc.circulate_universe(tmp_path, deadline_seconds=0.05, cursor_path=cursor)

    assert first, "first run examined nothing"
    assert second, "second run examined nothing"
    assert second[0] != first[0], (
        f"second bounded run restarted at {second[0]!r}, the same head-of-line "
        "symbol as the first; the tail of the universe is never reached"
    )


def test_the_cursor_wraps_rather_than_running_off_the_end(tmp_path, monkeypatch, fake_profiles):
    cursor = tmp_path / "cursor.json"
    cursor.write_text(json.dumps({"next_index": 9999}))
    seen: list[str] = []
    monkeypatch.setattr(ffc, "circulate_symbol", _stub_circulate(seen=seen))
    rep = ffc.circulate_universe(tmp_path, cursor_path=cursor)
    assert rep["symbols_circulated"] == 10
    assert seen[0] == "SYM00"


def test_a_corrupt_cursor_does_not_stop_the_run(tmp_path, monkeypatch, fake_profiles):
    cursor = tmp_path / "cursor.json"
    cursor.write_text("{{{not json")
    monkeypatch.setattr(ffc, "circulate_symbol", _stub_circulate())
    rep = ffc.circulate_universe(tmp_path, cursor_path=cursor)
    assert rep["symbols_circulated"] == 10
    assert rep["cursor_reset_reason"] == "unreadable"


def test_a_deadline_that_expires_before_the_first_symbol_reports_zero_honestly(
    tmp_path, monkeypatch, fake_profiles
):
    """Zero circulated must be distinguishable from an empty universe."""
    monkeypatch.setattr(ffc, "circulate_symbol", _stub_circulate())
    rep = ffc.circulate_universe(tmp_path, deadline_seconds=-1.0)
    assert rep["symbols_circulated"] == 0
    assert rep["symbols_planned"] == 10
    assert rep["completion"] == "PARTIAL_DEADLINE"
    assert rep["total_symbols"] == 0
