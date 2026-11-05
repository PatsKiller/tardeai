"""ANCHOR: JOBS_HEALTH_CENSUS_STATE_20261102 — an unmeasured schedule says WHICH fact is missing.

Every systemd lane without a schedule used to read `schedule_not_declared`, which asserts the lane
declares nothing. That is false in six different situations and the operator can act on the
difference: the census was never written, it is stale, it did not cover the unit, the unit is not
installed, the unit is installed but stopped, the registry row is an expression rather than a unit
name, or the lane is a continuous service with no schedule by design.

Hermetic: fixture census documents under tmp_path, fixture registry rows, no systemctl and no
read of the live state root.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from scripts.lib import jobs_health as J

NOW = datetime(2026, 11, 1, 15, 30, tzinfo=timezone.utc)


def lane(name: str = "svc", expression: str = "tradeai-svc.timer", kind: str = "systemd") -> dict:
    return {"lane_id": name, "state": "ACTIVE",
            "scheduler": {"kind": kind, "expression": expression},
            "output_signal": {"kind": "file_mtime", "path": f"data/runtime/{name}.json"}}


def write_census(tmp_path, *, units=None, observed_at="2026-11-01T15:00:00Z", coverage="COMPLETE"):
    path = tmp_path / J.SYSTEMD_CENSUS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": "SystemdScheduleCensus@v1", "observed_at": observed_at, "units": units or {}}
    if coverage is not None:
        doc["coverage"] = coverage
    path.write_text(json.dumps(doc))
    return path


def row_for(tmp_path, lane_row, *, now=NOW):
    """Build one row from the census file on disk, exactly as the live caller does."""
    units, census = J._systemd_census(tmp_path, now)
    report = J.build({"lanes": [lane_row]}, {"events": [], "successes": {}, "collection_gaps": []}, [],
                     {}, now=now, trading_day=lambda d: True, host_schedule=units, census=census)
    return report["rows"][0], report


def test_a_census_that_was_never_written_is_not_a_lane_without_a_schedule(tmp_path):
    row, _ = row_for(tmp_path, lane())
    assert row["evidence_gap"] == "schedule_census_unavailable"
    assert row["schedule_measured"] is False
    assert "census has not been written" in row["cause"]


def test_a_stale_census_is_its_own_gap(tmp_path):
    write_census(tmp_path, observed_at="2026-11-01T12:00:00Z")   # 3h old, budget is 2h
    row, _ = row_for(tmp_path, lane())
    assert row["evidence_gap"] == "schedule_census_stale"


def test_exactly_at_the_budget_is_still_fresh(tmp_path):
    write_census(tmp_path, observed_at="2026-11-01T13:30:00Z")   # exactly 2h
    units, census = J._systemd_census(tmp_path, NOW)
    assert census["state"] == "fresh" and census["census"] == J.CENSUS_OK


def test_a_census_from_the_future_is_not_trusted(tmp_path):
    write_census(tmp_path, observed_at="2026-11-01T18:00:00Z")
    units, census = J._systemd_census(tmp_path, NOW)
    assert units == {} and census["census"] == J.CENSUS_STALE


def test_an_unreadable_census_is_unavailable_not_stale(tmp_path):
    path = tmp_path / J.SYSTEMD_CENSUS_REL
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    units, census = J._systemd_census(tmp_path, NOW)
    assert units == {} and census["census"] == J.CENSUS_MISSING
    row, _ = row_for(tmp_path, lane())
    assert row["evidence_gap"] == "schedule_census_unavailable"


def test_an_unmeasured_census_never_claims_the_unit_is_not_installed(tmp_path):
    write_census(tmp_path, units={}, coverage="UNMEASURED")
    row, _ = row_for(tmp_path, lane())
    assert row["evidence_gap"] == "schedule_census_incomplete"


def test_a_census_that_never_states_its_coverage_cannot_claim_the_unit_is_not_installed(tmp_path):
    # A fresh, parsed artifact with no coverage key is not a complete capture. Before this test it fell through to
    # schedule_unit_not_installed, whose reason asserts the host census is complete and lacks the unit — a definite
    # claim the artifact never supported (D51 review, 2026-11-02).
    write_census(tmp_path, units={}, coverage=None)
    row, _ = row_for(tmp_path, lane())
    assert row["evidence_gap"] == "schedule_census_incomplete"
    assert "unknown" in row["cause"]


def test_a_partial_census_that_misses_the_unit_is_incomplete_not_absent(tmp_path):
    write_census(tmp_path, units={"other.timer": {}}, coverage="PARTIAL")
    row, _ = row_for(tmp_path, lane())
    assert row["evidence_gap"] == "schedule_census_incomplete"


def test_a_partial_census_still_measures_the_units_it_did_cover(tmp_path):
    # One unobserved unit must not re-flag every healthy lane on the host.
    write_census(tmp_path, units={"tradeai-svc.timer": {
        "active_state": "active", "next_elapse": "2026-11-01T23:30:00Z",
        "last_trigger": "2026-11-01T13:00:00Z"}}, coverage="PARTIAL")
    row, _ = row_for(tmp_path, lane())
    assert row["schedule_measured"] is True
    assert row["next_due_at"] == "2026-11-01T23:30:00Z"


def test_a_census_path_that_cannot_be_opened_is_unavailable_not_empty(tmp_path):
    # A directory at the artifact path raises OSError on open; chmod would not defeat a root runner.
    path = tmp_path / J.SYSTEMD_CENSUS_REL
    path.parent.mkdir(parents=True)
    path.mkdir()
    units, census = J._systemd_census(tmp_path, NOW)
    assert units == {} and census["census"] == J.CENSUS_MISSING


def test_a_complete_census_that_misses_the_unit_says_not_installed(tmp_path):
    write_census(tmp_path, units={"other.timer": {}}, coverage="COMPLETE")
    row, _ = row_for(tmp_path, lane())
    assert row["evidence_gap"] == "schedule_unit_not_installed"


def test_a_not_installed_unit_is_a_row_not_a_missing_key(tmp_path):
    # `systemctl show` answers for a unit that does not exist: Id present, ActiveState=inactive,
    # SubState=dead, UnitFileState empty. Key absence would mean a malformed expression instead.
    write_census(tmp_path, units={"tradeai-svc.timer": {
        "active_state": "inactive", "sub_state": "dead", "unit_file_state": "",
        "next_elapse": None, "last_trigger": None}}, coverage="COMPLETE")
    row, _ = row_for(tmp_path, lane())
    assert row["evidence_gap"] == "schedule_unit_not_installed"
    assert row["schedule_measured"] is False


def test_an_uninspected_unit_is_not_reported_as_missing(tmp_path):
    # A protected unit is deliberately not inspected. The writer still records the row but cannot
    # fill UnitFileState, so the empty-string verdict ("the host says it is not installed") would be
    # a claim we have no evidence for.
    write_census(tmp_path, units={"tradeai-svc.timer": {
        "active_state": "inactive", "sub_state": "dead", "unit_file_state": None,
        "next_elapse": None, "last_trigger": None}}, coverage="PARTIAL")
    row, _ = row_for(tmp_path, lane())
    assert row["evidence_gap"] == "schedule_unit_uninspected"
    assert row["schedule_measured"] is False


def test_a_one_shot_timer_that_already_fired_stays_measured(tmp_path):
    # Inactive, but it fired and has no future elapse - that is a completed one-shot, not a dead unit.
    write_census(tmp_path, units={"tradeai-svc.timer": {
        "active_state": "inactive", "sub_state": "dead", "unit_file_state": "static",
        "next_elapse": None, "last_trigger": "2026-11-01T13:00:00Z"}}, coverage="COMPLETE")
    row, _ = row_for(tmp_path, lane())
    assert row["schedule_measured"] is True
    assert row["evidence_gap"] == "execution_not_measured"


def test_a_stopped_unit_with_a_lingering_elapse_is_not_measured(tmp_path):
    write_census(tmp_path, units={"tradeai-svc.timer": {
        "active_state": "inactive", "unit_file_state": "enabled",
        "next_elapse": "2026-11-01T23:30:00Z",
        "last_trigger": None}})
    row, _ = row_for(tmp_path, lane())
    assert row["schedule_measured"] is False
    assert row["next_due_at"] is None
    assert row["evidence_gap"] == "schedule_unit_not_active"


def test_an_active_unit_is_measured_and_its_missing_receipt_is_the_gap(tmp_path):
    write_census(tmp_path, units={"tradeai-svc.timer": {
        "active_state": "active", "next_elapse": "2026-11-01T23:30:00Z",
        "last_trigger": "2026-11-01T13:00:00Z"}})
    row, _ = row_for(tmp_path, lane())
    assert row["schedule_measured"] is True
    assert row["next_due_at"] == "2026-11-01T23:30:00Z"
    assert row["evidence_gap"] == "execution_not_measured"


def test_a_continuous_service_is_not_accused_of_declaring_nothing(tmp_path):
    write_census(tmp_path, units={}, coverage="COMPLETE")
    row, _ = row_for(tmp_path, lane(expression="tradeai-callback-poller.service"))
    assert row["evidence_gap"] == "schedule_continuous_service"


def test_an_expression_that_is_not_a_unit_name_is_named_as_such(tmp_path):
    write_census(tmp_path, units={}, coverage="COMPLETE")
    row, _ = row_for(tmp_path, lane(expression="tradeai-health-tick.timer (*:0/5)"))
    assert row["evidence_gap"] == "schedule_expression_not_a_unit"


def test_a_lane_that_declares_nothing_still_reads_schedule_not_declared(tmp_path):
    write_census(tmp_path, units={}, coverage="COMPLETE")
    row, _ = row_for(tmp_path, lane(kind="cron", expression=""))
    assert row["evidence_gap"] == "schedule_not_declared"


def test_census_causes_are_not_counted_as_a_missing_receipt(tmp_path):
    write_census(tmp_path, units={}, coverage="COMPLETE")
    _, report = row_for(tmp_path, lane())
    summary = report["summary"]
    assert summary["unknown"] == 1
    assert summary["unknown_schedule_unmeasurable"] == 1
    assert summary["unknown_execution_not_measured"] == 0
    # The four buckets still account for every unknown row.
    assert (summary["unknown_never_scheduled"] + summary["unknown_schedule_not_declared"]
            + summary["unknown_schedule_unmeasurable"]
            + summary["unknown_execution_not_measured"]) == summary["unknown"]
    assert "cannot measure the schedule" in summary["gap_reasons"]["not_measured"]
