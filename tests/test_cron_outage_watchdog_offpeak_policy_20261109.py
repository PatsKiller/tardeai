"""LQ-20261107-1336 / INC-261109-jqqyvg: a fire the lane's own off-peak gate always skips is not a missed run.

due-diligence-questions fires every 20 minutes. From 20:00 ET on Sunday 2026-11-08 the dispatcher skipped each
run (receipt reason ``offpeak_skip``) because Sunday 20:00-23:00 ET is Monday 01:00-04:00 UTC, DeepSeek's billing
peak, and ``run_with_deepseek_offpeak.sh --scheduled`` never runs there. The watchdog measures scheduled SUCCESSES,
so two skipped fires read as two missing successes and it raised a P1 ("cron/lane outage") that no fixer could fix:
nothing was broken. A fire outside the declared gate's window is accounted for by policy and is now reported as
SKIPPED_BY_POLICY, never alerted; a fire the gate ALLOWS is still a miss, and a lane declaring no gate grades
exactly as before.

Fixture-only: pinned clocks, synthetic lanes and receipts. No DB, subprocess, provider, crontab or clock read.
COVERS = ["scripts/lib/cron_outage_watchdog.py", "scripts/cron_outage_watchdog.py"]
"""
from datetime import datetime, timedelta, timezone

from scripts import cron_outage_watchdog as wrapper
from scripts.lib.cron_outage_watchdog import allowlist_gate, evaluate, gate_allows_run

LANE_ID = "due-diligence-questions"
SENTINEL = object()


def at(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def lane(gate=SENTINEL, **changes):
    """The registry row of due-diligence-questions, verbatim in the fields this module reads."""
    row = {
        "lane_id": LANE_ID, "state": "ACTIVE", "expected_cadence_hours": 12.5,
        "scheduler": {"kind": "n8n", "expression": "dispatcher", "cadence": "*/20 * * * *",
                      "match": "scripts/due_diligence_questions.py --apply --route"},
        "dispatch": {"mode": "live", "cron": ["*/20 * * * *"], "tz": "America/New_York"},
        "output_signal": {"kind": "json_key", "key": "ok_at",
                          "path": "data/runtime/due-diligence-questions_last.json"},
    }
    if gate is not SENTINEL and gate is not None:
        row["watchdog_offpeak_gate"] = gate
    row.update(changes)
    return row


def assess(now, last_success, *, gate=SENTINEL, events=None):
    receipts = {LANE_ID: [{"validated_success": True, "at": last_success}]} if last_success else {}
    return evaluate({"lanes": [lane(gate)]}, events or [], receipts, now=at(now),
                    trading_day=lambda _at: True, registered_jobs=None)


def test_the_incident_slot_is_policy_skipped_not_a_missed_run():
    """Sunday 20:25 ET, last real run 19:41 ET: both elapsed fires are inside DeepSeek's peak."""
    result = assess("2026-11-09T01:25:00Z", "2026-11-09T00:41:29Z", gate="scheduled")
    row = result["rows"][0]
    assert row["status"] == "SKIPPED_BY_POLICY", row
    assert row["missed_fires"] == 0
    assert row["offpeak_gate"] == "scheduled"
    assert row["policy_skipped_fires"] == ["2026-11-09T01:00:00Z", "2026-11-09T01:20:00Z"]
    assert result["missed_lane_ids"] == []
    assert result["alert_required"] is False


def test_a_missed_fire_inside_the_gate_window_is_still_missed_runs():
    """Monday 10:30 ET: the gate allows every fire, so two missing successes stay a P1."""
    result = assess("2026-11-09T15:30:00Z", "2026-11-09T14:40:00Z", gate="scheduled")
    row = result["rows"][0]
    assert row["status"] == "MISSED_RUNS", row
    assert row["missed_fires"] == 2
    assert "policy_skipped_fires" not in row
    assert result["missed_lane_ids"] == [LANE_ID]


def test_a_skipped_fire_never_covers_a_real_miss_beside_it():
    """One allowed fire (Sun 19:40 ET) and one peak fire (Sun 20:00 ET): the allowed one is still a miss."""
    result = assess("2026-11-09T01:05:00Z", "2026-11-09T00:20:00Z", gate="scheduled")
    row = result["rows"][0]
    assert row["missed_fires"] == 1, row
    assert row["status"] == "OK"
    assert row["policy_skipped_fires"] == ["2026-11-09T01:00:00Z"]


def test_fires_after_the_peak_band_are_misses_again():
    """The peak ends at 04:00Z (Sun 23:00 ET); the next two fires are inside the gate's window."""
    result = assess("2026-11-09T04:25:00Z", "2026-11-09T03:40:00Z", gate="scheduled")
    row = result["rows"][0]
    assert row["status"] == "MISSED_RUNS", row
    assert row["missed_fires"] == 2
    assert "policy_skipped_fires" not in row


def test_a_lane_that_declares_no_gate_still_grades_missed_runs():
    """The exemption is the lane's own declared gate, never a global switch."""
    result = assess("2026-11-09T01:25:00Z", "2026-11-09T00:41:29Z", gate=None)
    row = result["rows"][0]
    assert row["status"] == "MISSED_RUNS", row
    assert row["missed_fires"] == 2
    assert "offpeak_gate" not in row


def test_the_official_gate_is_inverted_it_skips_inside_the_peak():
    """`official` allows a run everywhere EXCEPT DeepSeek's peak, so the same instants swap places."""
    result = assess("2026-11-09T01:05:00Z", "2026-11-09T00:20:00Z", gate="official")
    row = result["rows"][0]
    assert row["policy_skipped_fires"] == ["2026-11-09T01:00:00Z"], row
    assert row["missed_fires"] == 1


def test_the_bulk_gate_skips_a_peak_evening_but_allows_the_evening_hour_before_it():
    """`bulk` needs 10:00-21:00 ET AND no peak: Sun 19:40 ET is allowed, Sun 20:00 ET is peak."""
    assert gate_allows_run("bulk", at("2026-11-09T00:40:00Z")) is True
    assert gate_allows_run("bulk", at("2026-11-09T01:00:00Z")) is False


def test_gate_allows_run_is_none_when_there_is_no_gate_to_ask():
    assert gate_allows_run(None, at("2026-11-09T01:00:00Z")) is None
    assert gate_allows_run("nonsense", at("2026-11-09T01:00:00Z")) is None


def test_a_fire_covered_by_an_open_run_is_in_progress_not_policy_skipped():
    """A run started at 01:19Z covers the 01:20Z fire; only the 01:00Z fire is attributed to policy."""
    events = [{"ts": "2026-11-09T01:19:00Z", "event_type": "started", "mode": "business",
               "job_id": "ddq", "component": "ddq"}]
    result = evaluate({"lanes": [lane("scheduled", watchdog_wrapper_component="ddq")]}, events,
                      {LANE_ID: [{"validated_success": True, "at": "2026-11-09T00:41:29Z"}]},
                      now=at("2026-11-09T01:25:00Z"), trading_day=lambda _at: True, registered_jobs=None)
    row = result["rows"][0]
    assert row["in_progress_fires"] == 1, row
    assert row["policy_skipped_fires"] == ["2026-11-09T01:00:00Z"]
    assert row["missed_fires"] == 0


def test_a_lane_that_succeeded_through_the_band_gets_no_policy_row_at_all():
    """A success at 01:20:05Z leaves both elapsed fires at or before it: nothing is late, nothing to excuse."""
    result = assess("2026-11-09T01:25:00Z", "2026-11-09T01:20:05Z", gate="scheduled")
    row = result["rows"][0]
    assert row["status"] == "OK", row
    assert row["missed_fires"] == 0
    assert row["last_success_at"] == "2026-11-09T01:20:05Z"
    assert "policy_skipped_fires" not in row


def test_allowlist_gate_binds_only_the_lane_and_script_the_registry_names():
    allowlist = {"lanes": [
        {"lane_id": LANE_ID, "offpeak_gate": "scheduled",
         "command": ["env", "$PY", "scripts/due_diligence_questions.py", "--apply", "--route"]},
        {"lane_id": "another-lane", "offpeak_gate": "bulk",
         "command": ["$PY", "scripts/due_diligence_questions.py"]},
        {"lane_id": LANE_ID, "offpeak_gate": "not-a-gate", "command": ["$PY", "scripts/due_diligence_questions.py"]},
    ]}
    assert allowlist_gate(lane(), allowlist) == "scheduled"
    # Same lane id, different script: never bound (one lane's gate cannot excuse another's fires).
    assert allowlist_gate(lane(scheduler={"match": "scripts/other_lane.py"}), allowlist) is None
    assert allowlist_gate(lane(), None) is None
    assert allowlist_gate(lane(), {"lanes": []}) is None


def test_bind_components_attaches_the_declared_gate_and_leaves_other_lanes_alone():
    allowlist = {"lanes": [{"lane_id": LANE_ID, "offpeak_gate": "scheduled",
                            "command": ["$PY", "scripts/due_diligence_questions.py", "--apply"]}]}
    plain = {"lane_id": "no-entry", "scheduler": {"kind": "cron", "expression": "0 * * * *"}}
    bound = wrapper.bind_components({"lanes": [lane(), plain]}, {}, allowlist)
    first, second = bound["lanes"]
    assert first["watchdog_offpeak_gate"] == "scheduled"
    assert "watchdog_offpeak_gate" not in second


def test_bind_components_without_an_allowlist_binds_no_gate():
    bound = wrapper.bind_components({"lanes": [lane()]}, {}, None)
    assert "watchdog_offpeak_gate" not in bound["lanes"][0]
    assert wrapper.ALLOWLIST == "config/n8n_run_allowlist.json"


def test_the_peak_band_is_exactly_the_vendors_half_open_intervals():
    """Guard the dependency this excuse rests on: 01:00-04:00 and 06:00-10:00 UTC, half-open, weekdays."""
    from scripts.lib import deepseek_offpeak as offpeak

    peak_start = datetime(2026, 11, 9, 1, 0, tzinfo=timezone.utc)
    assert gate_allows_run("scheduled", peak_start) is False
    assert gate_allows_run("scheduled", peak_start + timedelta(hours=3)) is True
    assert offpeak.is_deepseek_peak_utc(peak_start) is True
    assert offpeak.is_deepseek_peak_utc(peak_start + timedelta(hours=3)) is False
