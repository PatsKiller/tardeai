"""Source-intent schedule/proof boundaries; synthetic DTOs only, no host or business actions.

COVERS = ["scripts/lib/n8n_momentum_lifecycle.py"]
"""

from __future__ import annotations

import copy
from datetime import datetime

import pytest

from scripts.lib import n8n_momentum_lifecycle as lifecycle

SHA = "a" * 40
LANE = "fixture-business"
NOW = datetime.fromisoformat("2026-10-13T06:20:00-04:00")


def row(kind="cron", stage=None, expression="*/5 6-11 * * 1-5", **scheduler):
    result = {"lane_id": LANE, "state": "ACTIVE", "scheduler": {"kind": kind, "expression": expression, **scheduler}}
    if stage is not None:
        result["scheduler"]["stage"] = stage
    return result


def dispatch(mode="live", cron=None):
    return {
        "class": "report",
        "mode": mode,
        "cron": cron or ["*/5 6-11 * * 1-5"],
        "tz": "America/New_York",
        "wave": "W0",
        "priority": 1,
        "retry_policy": "none",
    }


def product(**changes):
    result = {
        "available": True,
        "run_id": "fixture-business-output",
        "run_date": "2026-10-13",
        "source_sha": SHA,
        "finished_at": "2026-10-13T06:10:00-04:00",
        "basis": "REAL_BUSINESS_OUTPUT",
        "business_status": "ok",
        "populations": {"scanned_total": 4, "classified_total": 3, "manual_total": 1},
        "population_contract": "scan_partition",
    }
    result.update(changes)
    return result


def run(**changes):
    result = {
        "lane_id": LANE,
        "slot_local": "20261013T0600",
        "run_id": "fixture-natural-1",
        "trigger_kind": "NATURAL_SCHEDULE",
        "state": "RUN_DONE",
        "exit_code": 0,
        "requested_at": "2026-10-13T06:00:01-04:00",
        "started_at": "2026-10-13T06:00:02-04:00",
        "finished_at": "2026-10-13T06:00:30-04:00",
        "receipt": {
            "run_id": "fixture-natural-1",
            "lane_id": LANE,
            "slot_local": "20261013T0600",
            "source_sha": SHA,
            "exit_code": 0,
        },
    }
    result.update(changes)
    return result


def evaluate(registry_row, *, snapshot=None, now=NOW, allowlist=None, window="trading_day", trading=None):
    candidate = {
        "enabled": True,
        "watch": [{"lane_id": LANE, "role": "WATCH_ONLY_PROTECTED", "window": window, "completion_allowance_s": 300}],
        "products": [{"id": "latest_scan_package", "max_age_s": 3600}],
    }
    admission = lifecycle.Admission({LANE: registry_row}, {}, allowlist or {}, None, SHA, {})
    inputs = {"runs": [], "products": {"latest_scan_package": product()}} if snapshot is None else snapshot
    return lifecycle.evaluate(
        candidate,
        inputs,
        admission,
        now=now,
        trading_day_fn=trading or (lambda d: d.weekday() < 5),
        session_fn=lambda d: "regular" if 9 <= d.hour < 16 else "premarket",
    )


def lane_findings(report):
    return [f for f in report["incidents"] if f["item"].startswith(LANE + ":")]


def test_cutover_keeps_the_same_source_schedule_without_inventing_installed_authority():
    legacy = evaluate(row())
    moved_row = row("n8n", "cutover", "dispatcher", cadence="*/5 6-11 * * 1-5")
    moved_row["dispatch"] = dispatch()
    moved = evaluate(moved_row)
    assert legacy["lanes"][0]["expected_due"] == moved["lanes"][0]["expected_due"] == 4
    assert set(legacy["lanes"][0]["slot_states"]) == set(moved["lanes"][0]["slot_states"])
    assert moved["lanes"][0]["scheduler_authority"] == "N8N_PRIMARY"
    assert moved["lanes"][0]["installed_scheduler_authority"] == "NOT_MEASURED"
    assert moved["lanes"][0]["business_acceptance"] == moved["natural_cutover_proof"] == "NOT_MEASURED"
    assert lane_findings(moved)[0]["item"] == LANE + ":EXPECTED_FIRE_WITHOUT_REQUEST"


def test_all_retired_slots_survive_cadence_slots_and_dispatch_corroboration():
    expressions = ["0 6 * * 1-5", "10 6 * * 1-5"]
    legacy = evaluate(row(expression=" + ".join(expressions)))
    moved_row = row("n8n", "cutover", "dispatcher", cadence=expressions[0], cadence_slots=expressions)
    moved_row["dispatch"] = dispatch(cron=expressions)
    moved = evaluate(moved_row)
    assert legacy["lanes"][0]["expected_due"] == moved["lanes"][0]["expected_due"] == 2
    assert set(moved["lanes"][0]["slot_states"]) == {"20261013T0600", "20261013T0610"}


def test_new_dispatcher_without_a_legacy_cadence_uses_validated_dispatch_cron():
    r = row("n8n", "canary", "dispatcher")
    r["dispatch"] = dispatch(cron=["0 6 * * 1-5", "10 6 * * 1-5"])
    actual = evaluate(r)["lanes"][0]
    assert actual["expected_due"] == 2 and actual["schedule_timezone"] == "America/New_York"
    assert actual["scheduler_authority"] == "N8N_SOURCE_INTENT"


@pytest.mark.parametrize(
    "scheduler,block,reason",
    [
        ({"cadence": "bad"}, dispatch(), "schedule_not_measured"),
        ({"cadence": "99 6 * * 1-5"}, dispatch(), "schedule_not_measured"),
        ({"cadence_slots": []}, dispatch(), "schedule_not_measured"),
        ({"cadence_slots": "0 6 * * 1-5"}, dispatch(), "schedule_not_measured"),
        ({"cadence": "10 6 * * 1-5", "cadence_slots": ["0 6 * * 1-5"]}, None, "schedule_cadence_drift"),
        ({"cadence": "0 6 * * 1-5"}, dispatch(), "schedule_cadence_drift"),
        ({}, {**dispatch(), "cron": ["99 6 * * 1-5"]}, "schedule_dispatch_drift"),
        ({"timezone": "No/OwnedZone"}, dispatch(), "schedule_timezone_not_measured"),
        ({"timezone": ""}, dispatch(), "schedule_timezone_not_measured"),
        ({"timezone": False}, dispatch(), "schedule_timezone_not_measured"),
        ({"timezone": "UTC"}, dispatch(), "schedule_timezone_drift"),
        ({}, None, "schedule_not_measured"),
    ],
)
def test_conflicting_or_unreadable_source_cadence_has_no_fabricated_denominator(scheduler, block, reason):
    r = row("n8n", "cutover", "dispatcher", **scheduler)
    if block is not None:
        r["dispatch"] = block
    report = evaluate(r)
    lane = report["lanes"][0]
    assert lane["expected_due"] is None and lane["observed_requested"] is None
    assert reason in lane["requirements_missing"]
    assert any(f["item"] == LANE + ":" + reason.upper() and f["severity"] == "P1" for f in lane_findings(report))


def test_declared_lane_timezone_defines_slots_without_relabelling_business_date():
    r = row(expression="0 6 * * 1-5", timezone="UTC")
    report = evaluate(r)
    lane = report["lanes"][0]
    assert lane["expected_due"] == 1 and lane["schedule_timezone"] == "UTC"
    assert set(lane["slot_states"]) == {"20261013T0600"}
    assert report["date"] == "2026-10-13"
    assert lane["installed_scheduler_authority"] == "NOT_MEASURED"


@pytest.mark.parametrize(
    "expression,now,slot",
    [
        ("30 1 * * *", datetime.fromisoformat("2026-11-01T07:10:00+00:00"), "20261101T0130"),
        ("30 2 * * *", datetime.fromisoformat("2026-03-08T08:00:00+00:00"), "20260308T0300"),
    ],
)
def test_dispatcher_uses_existing_dst_gap_fold_rules_without_extra_natural_fire(expression, now, slot):
    r = row("n8n", "cutover", "dispatcher", cadence=expression, timezone="America/New_York")
    lane = evaluate(r, now=now, window="all_days", trading=lambda d: False)["lanes"][0]
    assert lane["expected_due"] == 1 and set(lane["slot_states"]) == {slot}
    assert lane["slot_states"][slot] == "expected_fire_without_request"


@pytest.mark.parametrize("census,observed", [({}, None), ({"runs": []}, 0)])
def test_legacy_only_n8n_absence_is_a_visible_migration_gap_not_business_failure(census, observed):
    report = evaluate(row(), snapshot={**census, "products": {"latest_scan_package": product()}})
    lane = report["lanes"][0]
    assert lane["expected_due"] == 4 and lane["observed_requested"] == observed
    assert lane["scheduler_authority"] == "LEGACY_ONLY"
    assert lane["migration_requirements_missing"] == lane["requirements_missing"]
    assert lane["scheduler_requirements_missing"] == [] and lane_findings(report) == []
    assert lane["business_fire_status"] == lane["business_acceptance"] == "NOT_MEASURED"
    assert report["products"]["latest_scan_package"]["status"] == "PROVEN"
    assert report["acceptance"] == report["natural_cutover_proof"] == "NOT_MEASURED"


def test_real_stale_business_output_still_alerts_while_legacy_migration_proof_is_missing():
    report = evaluate(
        row(),
        snapshot={"runs": [], "products": {"latest_scan_package": product(finished_at="2026-10-12T06:10:00-04:00")}},
    )
    assert report["products"]["latest_scan_package"]["status"] == "UNPROVEN"
    assert any(
        f["item"] == "latest_scan_package:OUTPUT_STALE_OR_UNATTRIBUTED" and f["severity"] == "P1"
        for f in report["incidents"]
    )
    assert report["lanes"][0]["migration_requirements_missing"] == ["expected_fire_without_request"]


@pytest.mark.parametrize("stage,mode", [("shadow", "dry_run"), ("canary", "live")])
def test_admitted_parallel_n8n_scheduler_absence_alerts_without_claiming_fallback_business_dead(stage, mode):
    r = row(stage=stage)
    r["dispatch"] = dispatch(mode)
    report = evaluate(r, allowlist={LANE: {"dry_run_arg": ["--dry-run"], "live_arg": []}})
    lane = report["lanes"][0]
    assert lane["scheduler_authority"] == f"N8N_{stage.upper()}_WITH_LEGACY_FALLBACK"
    assert lane["migration_requirements_missing"] == []
    assert lane["scheduler_requirements_missing"] == ["expected_fire_without_request"]
    assert lane_findings(report)[0]["severity"] == "P1"
    assert lane["business_fire_status"] == "NOT_MEASURED"
    assert report["products"]["latest_scan_package"]["status"] == "PROVEN"


def test_unavailable_dispatch_mode_cannot_be_silently_classified_legacy_only():
    r = row(stage="canary")
    r["dispatch"] = dispatch()
    report = evaluate(r, allowlist={LANE: {"live_arg": None}})
    assert report["lanes"][0]["scheduler_authority"] == "NOT_MEASURED"
    assert lane_findings(report)[0]["item"] == LANE + ":EXPECTED_FIRE_WITHOUT_REQUEST"


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"trigger_kind": "MANUAL_CANARY"}, "manual_or_unknown_trigger"),
        ({"state": "RUN_SKIPPED_LOCK"}, "lock_skipped"),
        ({"state": "RUN_REFUSED"}, "run_not_completed"),
        ({"started_at": None}, "durable_chain_incomplete"),
        ({"receipt": {**run()["receipt"], "source_sha": "b" * 40}}, "receipt_sha_or_verdict_mismatch"),
        ({"receipt": {**run()["receipt"], "lane_id": "other"}}, "receipt_slot_or_lane_mismatch"),
    ],
)
def test_actual_invalid_receipts_keep_strict_p1_even_for_legacy_only(change, reason):
    report = evaluate(row(expression="0 6 * * 1-5"), snapshot={"runs": [run(**change)]})
    assert report["lanes"][0]["slot_states"]["20261013T0600"] == reason
    assert report["lanes"][0]["migration_requirements_missing"] == []
    assert any(f["item"] == LANE + ":" + reason.upper() and f["severity"] == "P1" for f in lane_findings(report))
    assert report["natural_cutover_proof"] == "NOT_MEASURED"


def test_duplicate_completed_runs_still_need_independent_effect_proof():
    second = copy.deepcopy(run())
    second["run_id"] = second["receipt"]["run_id"] = "fixture-natural-2"
    report = evaluate(row(expression="0 6 * * 1-5"), snapshot={"runs": [run(), second]})
    assert report["lanes"][0]["slot_states"]["20261013T0600"] == "duplicate_completed_run_effects_not_proven"
    assert lane_findings(report)[0]["item"] == LANE + ":DUPLICATE_COMPLETED_RUN_EFFECTS_NOT_PROVEN"


def test_unknown_scheduler_kind_retains_strict_missing_request_finding():
    r = row()
    r["scheduler"].pop("kind")
    report = evaluate(r)
    assert report["lanes"][0]["scheduler_authority"] == "NOT_MEASURED"
    assert lane_findings(report)[0]["item"] == LANE + ":EXPECTED_FIRE_WITHOUT_REQUEST"


def test_weekend_business_schedule_has_no_fabricated_expected_request():
    report = evaluate(row(), now=datetime.fromisoformat("2026-10-17T06:20:00-04:00"))
    assert report["lanes"][0]["expected_due"] == report["lanes"][0]["observed_requested"] == 0
    assert report["lanes"][0]["requirements_missing"] == [] and lane_findings(report) == []
    assert report["products"]["latest_scan_package"]["status"] == "NOT_APPLICABLE"
