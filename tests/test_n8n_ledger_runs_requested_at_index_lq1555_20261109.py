"""LQ-20261107-1555: the releases-schedules n8n_today probe reads ``runs`` through an index, not a table scan.

ANCHOR: N8N_LEDGER_RUNS_REQUESTED_AT_INDEX_LQ1555_20261109

``scripts/lib/releases_schedules_view.read_ledger_today`` answers "what ran today" from
``runs.requested_at >= ET-midnight``. Before this index the first grouping (by mode and state) had no
requested_at predicate form it could use — the only requested_at index is ``(state, requested_at)`` and
the query names no state — so it was ``SCAN runs`` over the whole ledger: **4545 ms cold** on the live
637 MB / 87 932-row store, measured 2026-11-09 09:40 ET with ``posix_fadvise(DONTNEED)``. The route
gives every probe 4 s (``DEFAULT_TIMEOUT_S``), so the source came back TIMEOUT at 3987 ms and the page
rendered "Scheduled job health cannot be read".

Hermetic: a tmp_path ledger, no live store. The SQL below is the statement text from
``read_ledger_today`` (it is built inline there, so it is reproduced here; the last test pins the
function's numbers on a synthetic ledger so a behavioural drift is caught as well).
"""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.lib.n8n_coordination_ledger import CoordinationLedger
from scripts.lib.releases_schedules_view import read_ledger_today

SINCE = "2026-11-09T05:00:00+00:00"  # ET midnight for the fixed now() below (EST = UTC-5)
BY_MODE_STATE = "SELECT mode, state, COUNT(*) FROM runs WHERE requested_at >= ? GROUP BY mode, state"
BUSIEST_LANES = (
    "SELECT lane_id, COUNT(*), SUM(state IN ('RUN_FAILED','RUN_TIMEOUT','RUN_REFUSED')), "
    "SUM(state = 'RUN_SKIPPED_LOCK') FROM runs WHERE requested_at >= ? GROUP BY lane_id "
    "ORDER BY COUNT(*) DESC, lane_id LIMIT 10")


def _plan(conn, sql):
    return [str(r[-1]) for r in conn.execute("EXPLAIN QUERY PLAN " + sql, (SINCE,))]


def _table_scan_steps(step_list):
    """Steps that read the runs TABLE. ``SCAN runs USING INDEX x`` is an index scan, not a table scan."""
    return [s for s in step_list if s.startswith("SCAN runs") and "USING" not in s]


def test_a_writable_open_creates_the_runs_requested_at_index(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite3")
    cols = [r[2] for r in ledger._conn.execute("PRAGMA index_info(runs_requested_at)")]
    assert cols == ["requested_at", "lane_id", "mode", "state"]


def test_the_today_groupings_never_read_the_runs_table(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite3")
    by_mode = _plan(ledger._conn, BY_MODE_STATE)
    assert any("runs_requested_at" in step for step in by_mode), by_mode
    assert not _table_scan_steps(by_mode), by_mode
    busiest = _plan(ledger._conn, BUSIEST_LANES)
    assert not _table_scan_steps(busiest), busiest


def test_a_ledger_without_the_index_is_a_table_scan_and_gains_it_at_the_next_writable_open(tmp_path):
    """The fail-before shape: a pre-LQ-1555 store scans, and a read-only open never migrates."""
    path = tmp_path / "ledger.sqlite3"
    writer = CoordinationLedger(path)
    writer._conn.execute("DROP INDEX runs_requested_at")  # a store written by the code before this fix
    writer._conn.close()

    reader = CoordinationLedger(path, read_only=True)
    assert "runs_requested_at" not in {r[0] for r in reader._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}, "a read-only open must never migrate"
    assert _table_scan_steps(_plan(reader._conn, BY_MODE_STATE)), "without the index this was a full scan"
    reader._conn.close()

    assert not _table_scan_steps(_plan(CoordinationLedger(path)._conn, BY_MODE_STATE))


def test_the_projection_still_counts_the_ledger_exactly(tmp_path):
    """The index must not change a number: the same rows, filtered by ET-midnight, are counted."""
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite3")
    rows = [
        ("r1", "momentum", "live", "RUN_DONE", "2026-11-09T06:00:00+00:00"),
        ("r2", "momentum", "live", "RUN_DONE", "2026-11-09T07:00:00+00:00"),
        ("r3", "event-detector", "live", "RUN_FAILED", "2026-11-09T08:00:00+00:00"),
        ("r4", "event-detector", "live", "RUN_SKIPPED_LOCK", "2026-11-09T09:00:00+00:00"),
        # Yesterday in ET: excluded by the ET-midnight cutoff, not by a UTC date.
        ("r5", "momentum", "live", "RUN_DONE", "2026-11-08T23:00:00+00:00"),
    ]
    for run_id, lane, mode, state, at in rows:
        ledger._conn.execute(
            "INSERT INTO runs (run_id, lane_id, mode, state, requested_at) VALUES (?,?,?,?,?)",
            (run_id, lane, mode, state, at))
    ledger._conn.execute(
        "INSERT INTO dead_letters (slot_key, lane_id, dead_at) VALUES (?,?,?)",
        ("k1", "momentum", "2026-11-09T06:30:00+00:00"))

    value = read_ledger_today(tmp_path / "ledger.sqlite3",
                              datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc))["value"]

    assert value["total"] == 4, "only today's (ET) rows count"
    assert value["by_mode"] == {"live": 4}
    assert value["errors_total"] == 1
    assert value["skips_total"] == 1
    assert {row["lane"]: row["runs"] for row in value["busiest"]} == {"momentum": 2, "event-detector": 2}
    assert value["dead_letters"]["unreleased"] == 1
