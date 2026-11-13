"""Home Schedulers row reads lane_health_current honestly (LQ-20261107-2148).

The provider (``home_status_verdict.read_schedulers``) must (1) turn a missing table into UNKNOWN + NEEDS BACKEND,
(2) treat a present-but-empty table as UNKNOWN (no row is not "0 late"), (3) read only the rows of the NEWEST run, so a
retired lane's last row never counts, (4) use the lane's own rollup: a lane that cannot be measured leaves the row
UNKNOWN, never OK, (5) report WARN with a cause for a late/stale/failing lane, and (6) let a row older than its
threshold read STALE. Synthetic rows only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts import home_status_verdict as hsv
from scripts.lib import home_trade_ready as htr
from scripts.lib import lane_health as lh

NOW = datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc)


def _row(lane, state="OK", *, kind="n8n", measured=NOW - timedelta(minutes=3), run="run-new", value_class=None):
    full = {c: None for c in lh.COLUMNS}  # SELECT * returns every column, nullable ones as None
    return full | {"lane_id": lane, "scheduler_kind": kind, "state": state, "measured_at": measured, "run_id": run,
            "value_class": value_class, "owner": "ops", "cause_code": None if state == "OK" else "x",
            "cause": None if state == "OK" else f"{lane} {state}", "missed_count_24h": 0, "late_count_24h": 0,
            "failed_count_24h": 0, "expected_slots_24h": 1}


def _q(rows, present=True):
    def q(sql, params):
        if "to_regclass" in sql:
            return [{"present": present}]
        assert sql == lh.READ_CURRENT_SQL, sql
        return rows
    return q


def _field(rows, present=True, now=NOW):
    return htr.field_of(hsv.read_schedulers(_q(rows, present), now), now)


def test_missing_table_is_unknown_with_needs_backend():
    f = _field([], present=False)
    assert f["state"] == "UNKNOWN" and f["needs_backend"] is True


def test_present_but_empty_table_is_unknown_not_ok():
    f = _field([])
    assert f["state"] == "UNKNOWN" and f["needs_backend"] is False
    assert "no row" in (f.get("reason") or "")


def test_all_lanes_on_schedule_is_ok_with_the_row_age():
    f = _field([_row("a"), _row("b")])
    assert f["state"] == "OK" and f["value"] == 0 and f["as_of"] and f["age_s"] == 180


def test_an_unmeasurable_lane_leaves_the_row_unknown_never_ok():
    f = _field([_row("a"), _row("cron-lane", "NOT_MEASURED", kind="cron")])
    assert f["state"] == "UNKNOWN"


def test_a_late_lane_is_warn_with_the_cause_and_count():
    f = _field([_row("a"), _row("b", "LATE"), _row("c", "FAILING"), _row("d", "NOT_MEASURED", kind="cron")])
    assert f["state"] == "WARN" and f["value"] == 2
    assert "2 lane(s) LATE/STALE/FAILING" in f["cause"]


def test_a_retired_lanes_row_from_an_older_run_is_not_counted():
    # The reader's SQL selects the newest run only; prove the provider asks for exactly that statement.
    seen = []

    def q(sql, params):
        seen.append(sql)
        return [{"present": True}] if "to_regclass" in sql else [_row("a")]

    hsv.read_schedulers(q, NOW)
    assert lh.READ_CURRENT_SQL in seen and "run_id = (SELECT run_id" in lh.READ_CURRENT_SQL


def test_a_row_older_than_the_threshold_reads_stale():
    old = NOW - timedelta(seconds=hsv.SCHEDULERS_MAX_AGE_S + 600)
    f = _field([_row("a", measured=old)])
    assert f["state"] == "STALE"


def test_business_critical_filter_narrows_warn(monkeypatch):
    monkeypatch.setattr(lh, "load_config", lambda: {**lh.DEFAULTS, "business_critical_value_classes": ["Business Critical"]})
    rows = [_row("a", value_class="Business Critical"), _row("b", "LATE", value_class="Low")]
    assert _field(rows)["state"] == "OK"
    rows = [_row("a", "LATE", value_class="Business Critical")]
    assert _field(rows)["state"] == "WARN"
