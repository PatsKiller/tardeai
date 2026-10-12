"""Closure accounting and peer-write preservation using synthetic declarations."""

import pytest
import threading

from scripts import reconcile_migration_inventory as R


def reconcile(rows, *, blocked=None, completion=None, waves=None):
    return R.reconcile(
        rows,
        registry={"lanes": [{"lane_id": "lane", "state": "ACTIVE", "scheduler": {"kind": "cron"}}]},
        contracts={"contracts": []},
        allowlist={"blocked_reasons": blocked or {}},
        completion={"completion119": {"rows": completion or []}},
        waves=waves or {},
        codeonly=[],
        as_of="2026-10-12T03:00:00+00:00",
        source_sha="a" * 40,
        deployed_sha="b" * 40,
        inputs={"workbook": "fixture.xlsx#hash", "registry": "fixture-registry.json#hash"},
    )


def row(inv_id="cron:1", **kw):
    return {
        "inv_id": inv_id,
        "registry_row": "lane",
        "owner_stakeholder": "platform",
        "classification": "Requires Refactoring Before Migration",
        **kw,
    }


def test_historical_validation_cannot_complete_or_measure_readiness():
    result = reconcile([row(migration_status="Validated", validation_status="Natural-schedule proven")])
    item = result["items"][0]
    assert item["primary_work_status"] == "In Progress"
    assert item["production_readiness"] == "NOT_MEASURED"
    assert item["tested_sha"] == "NOT_MEASURED"
    assert result["summary"]["inventory_closure_pct"] == "NOT_MEASURED"
    assert result["summary"]["verified_completed_under_new_contract"] == 0
    assert result["drift"]


def test_partition_precedence_and_no_fake_zero_for_named_boundary():
    result = reconcile(
        [
            row(
                "1",
                work_deferral_decision={
                    "scope": "INVENTORY_CLOSURE",
                    "accepted": True,
                    "owner": "operator",
                    "decided_at": "2026-10-10T20:00:00-04:00",
                    "evidence": "fixture-decision.json",
                },
            ),
            row("2", owner_stakeholder="UNKNOWN"),
            row("3", migration_status="Shadow"),
            row("4"),
        ]
    )
    assert result["summary"]["primary_status_partition"] == {
        "Completed": 0,
        "In Progress": 1,
        "Blocked": 1,
        "Deferred": 1,
        "Not Started": 1,
    }
    # Undated planning prose is not an explicit deferral.
    assert (
        reconcile([row(consolidation_approval="Deferred proposal")])["items"][0]["primary_work_status"] == "Not Started"
    )


def test_source_blocker_beats_historical_work_annotation():
    result = reconcile([row(implemented="PR #999 Live")], blocked={"lane": "owner authority withheld"})
    assert result["items"][0]["primary_work_status"] == "Blocked"
    assert "owner authority withheld" in result["items"][0]["closure_blockers"]


def test_duplicate_inventory_ids_refused_and_many_scheduler_rows_retained():
    with pytest.raises(ValueError, match="unique"):
        reconcile([row(), row()])
    result = reconcile([row("cron:1"), row("timer:1"), row("n8n:1")])
    assert len(result["items"]) == 3
    assert result["summary"]["exact_registry_ids_represented"] == 1
    assert result["summary"]["canonical_business_process_denominator"] == "NOT_MEASURED"


def test_metadata_overlap_counted_once_without_acceptance():
    comp = [
        {
            "lane_id": "lane",
            "source_result": "SOURCE_CHANGED_ADMISSION_HELD",
            "detail_result": "IMPLEMENTED_SOURCE_ADMISSION_HELD",
            "remaining": ["review full closure"],
        }
    ]
    wave = {"wave1": {"W1": {"inv_ids": ["cron:1"]}}}
    result = reconcile([row()], completion=comp, waves=wave)
    assert result["summary"]["source_metadata_coverage"] == {
        "wave_targets": 1,
        "completion_targets": 1,
        "combined_targets": 1,
        "including_planning_targets": 1,
    }
    assert result["summary"]["accepted_refactor_pct"] == "NOT_MEASURED"
    assert result["items"][0]["refactor_status"] == "WORK_METADATA; ACCEPTANCE_NOT_MEASURED"


def test_unmapped_parent_and_inherited_owner_cannot_be_manufactured():
    result = reconcile(
        [row(registry_row="NONE", owner_stakeholder="UNKNOWN (parent owner platform)", x_parent="timer:parent")]
    )
    item = result["items"][0]
    assert item["canonical_process_id"] == "UNMAPPED:cron:1"
    assert item["primary_work_status"] == "Blocked"
    assert result["crosswalk"][0]["parent"] == "timer:parent"
    assert not result["crosswalk"][0]["registry_lane_id"]


def test_unknown_classification_keeps_refactor_requirement_applicable():
    for value in (None, "UNKNOWN", "Not yet adjudicated"):
        result = reconcile([row(classification=value)])
        req = next(r for r in result["requirements"] if r["requirement"] == "refactor")
        assert req["status"] == "NOT_MEASURED"
        assert result["items"][0]["primary_work_status"] == "Blocked"


def test_scoped_or_undated_consolidation_deferral_is_not_full_work_deferral():
    for value in (
        "Deferred — Deferred proposal; no owner/date/decision",
        "Deferred — Deferred 2026-10-10 operator: out of C1",
    ):
        result = reconcile([row(consolidation_approval=value)])
        assert result["items"][0]["primary_work_status"] == "Not Started"
        assert result["items"][0]["scoped_consolidation_deferral"] == value


def test_exact_registry_id_is_coverage_not_accepted_business_crosswalk():
    result = reconcile([row()])
    requirements = {r["requirement"]: r for r in result["requirements"]}
    assert requirements["registry_declaration"]["status"] == "PROVEN"
    assert requirements["mapping"]["status"] == "NOT_MEASURED"


def test_retained_scheduler_still_requires_production_proof():
    result = reconcile([row(classification="Retain as Existing Cron Job")])
    requirements = {r["requirement"]: r for r in result["requirements"]}
    assert requirements["cutover"]["status"] == "NOT_APPLICABLE_WITH_REASON"
    assert requirements["outputs"]["status"] == "NOT_MEASURED"
    assert requirements["monitoring"]["status"] == "NOT_MEASURED"
    assert result["items"][0]["production_readiness"] == "NOT_MEASURED"


def test_publication_refuses_peer_write_and_preserves_old_bytes(tmp_path):
    workbook = tmp_path / "inventory.xlsx"
    candidate = tmp_path / "candidate.xlsx"
    workbook.write_bytes(b"original")
    candidate.write_bytes(b"candidate")
    digest = R.sha256(b"original")
    workbook.write_bytes(b"peer-write")
    with pytest.raises(ValueError, match="changed"):
        R.publish_candidate(workbook, candidate, expected_sha=digest, original_bytes=b"original")
    assert workbook.read_bytes() == b"peer-write"
    assert not list(tmp_path.glob("*.pre-reconciliation-*"))
    workbook.write_bytes(b"original")
    receipt = R.publish_candidate(workbook, candidate, expected_sha=digest, original_bytes=b"original")
    assert workbook.read_bytes() == b"candidate"
    assert list(tmp_path.glob("*.pre-reconciliation-*"))[0].read_bytes() == b"original"
    assert receipt["after_sha256"] == R.sha256(b"candidate")


def test_competing_writer_cannot_enter_final_replace_window(tmp_path, monkeypatch):
    workbook, candidate = tmp_path / "inventory.xlsx", tmp_path / "candidate.xlsx"
    workbook.write_bytes(b"original")
    candidate.write_bytes(b"candidate")
    outcomes = []
    replace = R.os.replace

    def competitor():
        try:
            with R.writer_lock(workbook):
                workbook.write_bytes(b"peer-write")
                outcomes.append("overwritten")
        except BlockingIOError:
            outcomes.append("serialized")

    def racing_replace(src, dst):
        thread = threading.Thread(target=competitor)
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
        return replace(src, dst)

    monkeypatch.setattr(R.os, "replace", racing_replace)
    R.publish_candidate(workbook, candidate, expected_sha=R.sha256(b"original"), original_bytes=b"original")
    assert outcomes == ["serialized"]
    assert workbook.read_bytes() == b"candidate"
