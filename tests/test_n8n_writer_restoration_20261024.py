"""W8 read-only ownership/receipt proof; all observations have pinned clocks."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import n8n_writer_restoration as w
from scripts.lib.cron_outage_watchdog import evaluate
from scripts.lib.cron_schedule import fires_between

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
BINDING = {"manifest": "config/pipelines/premarket.json", "stage": "premarket",
           "step_id": "classifier", "lane_id": "premarket-data-pipeline"}
SHA = "a" * 64


def receipt(**changes):
    return {"schema": "LaneRunReceipt@v1", "lane_id": "classifier", "mode": "live",
            "status": "ok", "exit": 0, "ok_at": "2026-10-23T13:00:00Z",
            "finished_at": "2026-10-23T13:00:00Z", **changes}


def pipeline(**changes):
    return {"schema": "PipelineRun@v1", "pipeline": "premarket", "stage": "premarket",
            "manifest_sha256": SHA, "dry_run": False, "apply_requested": True,
            "executed_any": True, "receipt_complete": True, "overall_status": "ok",
            "started_at": "2026-10-23T09:45:00Z", "step_count": 1, "expected_step_count": 1,
            "steps": [{"schema": "PipelineStepReceipt@v1", "pipeline": "premarket", "stage": "premarket",
                       "id": "classifier", "status": "ok", "rc": 0, "dry_run": False,
                       "ts": "2026-10-23T09:46:00Z"}], **changes}


def source_fixture():
    catalog = {"schema": "N8nWriterRestoration@v1", "activation": "OPERATOR_ONLY", "writers": [{
        "key": "classifier", "lane_id": "classifier", "label": "Regime", "source": "scripts/classifier.py",
        "artifact": "regime_snapshots", "receipt": "data/runtime/classifier_last.json", "pipeline": BINDING}]}
    registry = {"lanes": [{"lane_id": "classifier", "state": "RETIRED", "expected_cadence_hours": 24,
                          "superseded_by": "premarket-data-pipeline",
                          "scheduler": {"kind": "cron", "expression": "35 6 * * 1-5"},
                          "output_signal": {"kind": "file_mtime", "path": "logs/regime.log"}},
                         {"lane_id": "premarket-data-pipeline", "state": "ACTIVE", "expected_cadence_hours": 24,
                          "scheduler": {"kind": "cron", "expression": "45 5 * * *"},
                          "output_signal": {"kind": "file_mtime", "path": "data/runtime/pipeline.json"}}]}
    manifests = {BINDING["manifest"]: {"sha256": SHA, "document": {"stages": {"premarket": {"steps": [
        {"id": "classifier", "dow": [1, 2, 3, 4, 5]}]}}}}}
    return catalog, registry, {"lanes": []}, {"contracts": []}, manifests


def test_absorbed_writer_uses_parent_schedule_without_mutating_or_rearming_registry():
    args = source_fixture()
    before = copy.deepcopy(args)
    result = w.audit(*args, now=NOW, receipts={"data/runtime/pipeline.json": pipeline()})
    row = result["rows"][0]
    assert row["registry_state"] == "RETIRED" and row["effective_writer_state"] == "ACTIVE"
    assert row["schedule_owner"] == "premarket-data-pipeline"
    assert row["current_cron"] == ["45 5 * * 1,2,3,4,5"]
    assert row["last_success_at"] == "2026-10-23T09:46:00Z"
    assert row["execution"]["attempt_status"] == "NOT_MEASURED"
    assert row["pipeline_execution"]["output_acceptance"] == "NOT_MEASURED"
    assert row["activation_allowed"] is False
    assert result["watchdog_registry"]["observation_only"] is True
    assert args == before


@pytest.mark.parametrize("change,reason", [
    ({"mode": "dry_run"}, "dry_or_unmeasured_mode_is_not_success"),
    ({"dry_run": True}, "dry_or_unmeasured_mode_is_not_success"),
    ({"exit": None}, "exit_code_not_measured"),
    ({"exit": False}, "exit_code_not_measured"),
    ({"lane_id": "wrong"}, "receipt_identity_mismatch"),
    ({"schema": "arbitrary"}, "receipt_schema_not_admitted"),
    ({"ok_at": "2026-10-23T12:59:00Z"}, "success_timestamp_not_bound_to_attempt"),
    ({"finished_at": "2026-10-23T15:00:00Z"}, "invalid_or_future_finished_at"),
    ({"finished_at": "2026-10-23T13:00:00"}, "invalid_or_future_finished_at"),
])
def test_nonproofs_cannot_green_a_writer(change, reason):
    result = w.receipt_success(receipt(**change), lane_id="classifier", now=NOW)
    assert result["last_success_at"] is None and result["reason"] == reason


def test_failed_attempt_preserves_historical_success_but_not_current_health():
    result = w.receipt_success(receipt(status="failed", exit=1, ok_at="2026-10-22T13:00:00Z"),
                               lane_id="classifier", now=NOW)
    assert result["attempt_status"] == "FAILED"
    assert result["last_success_at"] == "2026-10-22T13:00:00Z"


@pytest.mark.parametrize("status,rc", [("failed", 1), ("skipped_dow", 0), ("skipped_lock", 0),
                                      ("ok", False), ("ok", None)])
def test_aggregate_success_never_masks_unsuccessful_pipeline_leaf(status, rc):
    doc = pipeline()
    doc["steps"][0].update(status=status, rc=rc)
    result = w.pipeline_step_success(doc, BINDING, manifest_sha=SHA, now=NOW)
    assert result["last_success_at"] is None


@pytest.mark.parametrize("change", [{"dry_run": True}, {"receipt_complete": False},
    {"manifest_sha256": "b" * 64}, {"stage": "other"}, {"pipeline": "other"},
    {"step_count": 2}, {"expected_step_count": 2}, {"apply_requested": False}, {"executed_any": False}])
def test_pipeline_evidence_requires_bound_complete_real_run(change):
    assert w.pipeline_step_success(pipeline(**change), BINDING, manifest_sha=SHA,
                                    now=NOW)["last_success_at"] is None


def test_duplicate_and_future_step_receipts_are_unmeasured():
    doc = pipeline()
    doc["steps"] *= 2
    doc.update(step_count=2, expected_step_count=2)
    assert w.pipeline_step_success(doc, BINDING, manifest_sha=SHA, now=NOW)["last_success_at"] is None
    doc = pipeline()
    doc["steps"][0]["ts"] = "2026-10-24T09:45:00Z"
    assert w.pipeline_step_success(doc, BINDING, manifest_sha=SHA, now=NOW)["last_success_at"] is None


def test_missing_or_renamed_pipeline_binding_does_not_revive_retired_leaf_schedule():
    args = source_fixture()
    args[1]["lanes"][0]["superseded_by"] = "different"
    row = w.audit(*args, now=NOW)["rows"][0]
    assert row["schedule_owner"] is None and row["current_cron"] == []
    assert "pipeline_ownership_binding_not_measured" in row["admission_blockers"]


def test_paused_execution_lane_is_visible_and_never_becomes_watchdog_or_workflow_candidate():
    args = source_fixture()
    args[0]["writers"][0].pop("pipeline")
    args[0]["writers"][0].update(execution_boundary=True, blocked_by=["operator_resume_required"])
    args[1]["lanes"][0]["state"] = "PAUSED"
    result = w.audit(*args, now=NOW)
    assert result["rows"][0]["watchdog_status"] == "INACTIVE"
    assert result["watchdog_registry"]["lanes"] == []
    assert result["activation_allowed"] is False


def test_writer_virtual_observation_feeds_existing_missed_run_watchdog():
    args = source_fixture()
    doc = pipeline(started_at="2026-10-21T09:45:00Z")
    doc["steps"][0]["ts"] = "2026-10-21T09:46:00Z"
    result = w.audit(*args, now=NOW, receipts={"data/runtime/pipeline.json": doc})
    observed = evaluate(result["watchdog_registry"], [], result["watchdog_successes"],
                        now=NOW.replace(hour=9, minute=55), grace_seconds=120)
    assert observed["missed_lane_ids"] == ["classifier"]
    assert observed["rows"][0]["missed_fires"] == 2


def test_all_approved_writer_requirements_present_and_risk_schedule_is_session_exact():
    catalog = json.loads((ROOT / "config/n8n_writer_restoration.json").read_text())
    assert not w.validate_catalog(catalog)
    assert len(catalog["writers"]) == 20  # 17 W8 requirements plus W3's three existing lanes.
    assert all((ROOT / row["source"]).is_file() for row in catalog["writers"])
    risk = next(x for x in catalog["writers"] if x["key"] == "risk-management-refresh")
    start, end = NOW.replace(hour=12, minute=0), NOW.replace(hour=21, minute=0)
    fires = {f.at.strftime("%H:%M") for expr in risk["requested_cron"]
             for f in fires_between(expr, start, end, "America/New_York")}
    assert len(fires) == 28
    assert min(fires) == "09:30" and max(fires) == "16:10"
    assert "16:15" not in fires and "09:15" not in fires


def test_real_source_check_is_read_only_and_includes_all_continuing_writers():
    paths = [ROOT / "config" / x for x in ["lane_registry.json", "n8n_run_allowlist.json", "n8n_health_contracts.json"]]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report = subprocess.run([sys.executable, str(ROOT / "scripts/n8n_writer_restoration.py"),
                             "--now", "2026-10-23T14:00:00Z"], capture_output=True, text=True, check=True)
    doc = json.loads(report.stdout)
    assert set(doc["source_drift_lane_ids"]) == {"market-regime-classifier", "sync-dividend-data",
                                               "refresh-symbol-cards", "recommendation-intelligence-engine"}
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths} == before
    assert doc["activation_allowed"] is False


def test_naive_clock_and_invalid_catalog_fail_closed():
    with pytest.raises(ValueError, match="aware"):
        w.audit(*source_fixture(), now=NOW.replace(tzinfo=None))
    args = source_fixture()
    args[0]["activation"] = "AUTOMATIC"
    with pytest.raises(ValueError, match="operator_only"):
        w.audit(*args, now=NOW)


def test_health_proposals_are_valid_but_never_operative_or_forged_review():
    from scripts.lib.n8n_health_contracts import validate_contract
    catalog = json.loads((ROOT / "config/n8n_writer_restoration.json").read_text())
    proposal = w.health_proposals(catalog)
    assert proposal["operative"] is False and proposal["activation_allowed"] is False
    for contract in proposal["contracts"]:
        assert validate_contract(contract) == []
        assert contract["status"] == "DRAFT" and contract["operative"] is False
        assert contract["reviewer"] is None and contract["reviewed_at"] is None
        assert contract["baseline"]["timeout_s"] == "NOT_MEASURED"
