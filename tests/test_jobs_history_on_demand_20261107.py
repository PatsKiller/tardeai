"""ANCHOR: JOBS_HISTORY_ON_DEMAND_20261107 — a lane with no wall-clock schedule can never be "late".

WORK-QUEUE 2026-11-07, items 8-10. Three ACTIVE registry rows — `advisory-desk-run-now`,
`analyst-prospectus-generate`, `aegis-brief-regenerate` — declare `scheduler.kind: "none"` and an
`on-demand:` expression, with `expected_cadence_hours: 24` (a freshness target for work that is *asked
for*, not a firing schedule). Each was graded `late / "Nothing recorded for 24 h × 1.5"` while the same
row reported `"No wall-clock schedule is declared for this job"` and `history_gap: "event-driven or
unscheduled: there is no run schedule to compare against"`.

Hermetic: synthetic lanes and clocks only, no database, no host state.
"""
from datetime import datetime, timedelta, timezone

from scripts.lib import jobs_history as J

NOW = datetime(2026, 11, 7, 3, 15, tzinfo=timezone.utc)


def _z(dt):
    return dt.astimezone(timezone.utc).isoformat()


def on_demand_lane(lane_id="synthetic-on-demand-lane", expression="on-demand:api-v3-advisory-run-now",
                   kind="none", state="ACTIVE"):
    return {"lane_id": lane_id, "state": state, "expected_cadence_hours": 24,
            "scheduler": {"kind": kind, "expression": expression, "stage": "shadow"},
            "output_signal": {"kind": "file_mtime", "path": f"data/runtime/{lane_id}_latest.json"}}


def systemd_lane(lane_id="synthetic-timer-lane", hours=0.25):
    return {"lane_id": lane_id, "state": "ACTIVE", "expected_cadence_hours": hours, "scheduler": {"kind": "systemd"},
            "output_signal": {"kind": "file_mtime", "path": f"data/runtime/{lane_id}.json"}}


def build(lanes, **inputs):
    inputs.setdefault("ledger_since", NOW - timedelta(days=10))
    inputs.setdefault("journal_since", NOW - timedelta(days=10))
    return J.build({"lanes": lanes}, inputs, now=NOW, trading_day=lambda d: d.weekday() < 5)


def row_of(result, lane_id):
    return next(r for r in result["rows"] if r["lane_id"] == lane_id)


def ledger_row(lane, start, *, mode="live", state="RUN_DONE", exit_code=0):
    return {"run_id": f"d:{lane}:{mode}:{start:%Y%m%dT%H%M}", "lane_id": lane, "mode": mode, "state": state,
            "requested_at": _z(start), "started_at": _z(start), "finished_at": _z(start + timedelta(seconds=30)),
            "exit_code": exit_code, "duration_s": 30}


def test_on_demand_output_never_makes_the_lane_late():
    lane = on_demand_lane()
    stale = NOW - timedelta(days=26)  # the live rows last produced on 2026-10-12
    row = row_of(build([lane], output_times={"synthetic-on-demand-lane": stale}), "synthetic-on-demand-lane")
    assert row["status"] != "late"
    assert row["status"] == "ok_unverified"  # an output file time is still never a proven run
    assert row["status_reason"] is None
    assert row["missed_count"] is None
    assert row["missed_gap"] == "No wall-clock schedule is declared for this job"


def test_on_demand_receipt_never_makes_the_lane_late():
    lane = on_demand_lane("synthetic-on-demand-receipt")
    last_asked = NOW - timedelta(days=26)  # the live rows were last run on 2026-10-12
    receipt = J.receipt_run({"started_at": _z(last_asked), "finished_at": _z(last_asked + timedelta(seconds=42)),
                             "ok_at": _z(last_asked + timedelta(seconds=42)), "exit": 0, "status": "ok"}, None)
    row = row_of(build([lane], receipts={lane["lane_id"]: receipt}), lane["lane_id"])
    assert row["history_sources"] == ["run receipt (last run only)"]
    assert row["status"] != "late", row["status_reason"]
    assert row["status"] == "ok"  # a successful receipt is still a proven run


def test_event_lane_with_no_readable_fires_is_not_late_either():
    lane = on_demand_lane("synthetic-event-lane", expression="openclaw-cron:0123456789abcdef", kind="event")
    row = row_of(build([lane], output_times={"synthetic-event-lane": NOW - timedelta(days=40)}), "synthetic-event-lane")
    assert row["status"] != "late"


def test_summary_counts_no_late_rows_for_on_demand_lanes():
    lanes = [on_demand_lane("synthetic-on-demand-a"), on_demand_lane("synthetic-on-demand-b")]
    stale = NOW - timedelta(days=26)
    out = build(lanes, output_times={lane["lane_id"]: stale for lane in lanes})
    assert out["summary"]["late"] == 0
    assert out["summary"]["ok_unverified"] == 2


def test_a_scheduled_lane_with_a_stale_clock_based_cadence_is_still_late():
    """The lateness rule itself must survive: a systemd lane has no expression, only expected_cadence_hours."""
    lane = systemd_lane(hours=0.25)
    row = row_of(build([lane], output_times={"synthetic-timer-lane": NOW - timedelta(hours=3)}), "synthetic-timer-lane")
    assert row["status"] == "late"
    assert row["status_reason"] == "Nothing recorded for 0.25 h × 1.5"


def test_on_demand_lane_with_a_failing_run_still_reports_failed():
    lane = on_demand_lane("synthetic-on-demand-failed")
    run = ledger_row(lane["lane_id"], NOW - timedelta(hours=2), state="RUN_FAILED", exit_code=1)
    row = row_of(build([lane], ledger_runs=[run]), lane["lane_id"])
    assert row["status"] == "failed"
