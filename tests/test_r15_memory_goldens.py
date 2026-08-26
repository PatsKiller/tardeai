"""100 cognition-timeline goldens: versions, rejection, supersession."""
from __future__ import annotations

import pytest

from scripts.lib.cio_curation_run import (
    apply_material_version,
    build_curation_run,
    cognition_timeline,
    persist_challenger,
    persist_curation_run,
    supersede,
)
from scripts.lib.hermes_curation_summary import KIND_BASELINE, KIND_MATERIAL
from tests.r15_goldens import memory_goldens

pytestmark = pytest.mark.tier0
CASES = memory_goldens()


def _run(tmp_path, *, accepted: bool, material: bool, symbol="NVDA", version_hint=0, extra_hash="x"):
    run = build_curation_run(
        security_guid="sec-nvda",
        symbol=symbol,
        task_type="research_curation",
        prior_curation_id=None if version_hint == 0 else f"sec-nvda:v{version_hint}",
        prior_curation_version=version_hint,
        evidence_delta_hash=extra_hash,
        input_evidence_refs=["e1"] if accepted else [],
        prompt_version="p1",
        process_id="hermes_external_research",
        requested_policy="FAST",
        executed_policy="FAST",
        model_id="deepseek-v4-flash",
        schema_valid=accepted,
        critique_verdict="ACCEPT" if accepted else "REJECT",
        accepted=accepted,
        material_change=material,
        classification="MATERIAL" if material and accepted else "NO_NEW_INFO",
    )
    stored = persist_curation_run(tmp_path, run)
    return stored["run"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_memory_temporal_golden(case: dict, tmp_path) -> None:
    previous = None
    last = None
    rejected = 0
    hash_n = 0
    for event in case["events"]:
        hash_n += 1
        if event == "baseline":
            run = _run(tmp_path, accepted=True, material=False, extra_hash=f"b{hash_n}")
            last = apply_material_version(run=run, previous=previous, support_guids=["e1"], what_changed="BASELINE")
            previous = last["summary"]
            assert last["summary"]["kind"] == KIND_BASELINE
            assert last["summary"]["version"] == 0
        elif event == "material":
            run = _run(tmp_path, accepted=True, material=True, version_hint=int((previous or {}).get("version") or 0), extra_hash=f"m{hash_n}")
            last = apply_material_version(run=run, previous=previous, support_guids=["e1", "e2"], what_changed="new 10-K")
            previous = last["summary"]
            persist_curation_run(tmp_path, last, retry=True)
        elif event == "no_new_info":
            run = _run(tmp_path, accepted=True, material=False, version_hint=int((previous or {}).get("version") or 0), extra_hash=f"n{hash_n}")
            last = apply_material_version(run=run, previous=previous, support_guids=["e1"], what_changed="NO_NEW_INFO")
            assert last["fake_progress"] is False
            assert last["summary"]["version"] == (previous or {}).get("version")
        elif event == "rejected":
            run = _run(tmp_path, accepted=False, material=True, extra_hash=f"r{hash_n}")
            last = apply_material_version(run=run, previous=previous, support_guids=[], what_changed="bad")
            persist_curation_run(tmp_path, last, retry=True)
            rejected += 1
            assert last["current_belief"] is False
            assert last["retained_in_audit"] is True
    assert last["summary"]["version"] == case["expect_version"]
    if case.get("expect_kind"):
        assert last["summary"]["kind"] == case["expect_kind"]
    if case.get("rejected_retained"):
        tl = cognition_timeline(tmp_path, security_guid="sec-nvda")
        assert tl["rejected_retained"] >= 1
        assert tl["rejected_is_current_belief"] is False
    if case.get("prior_deleted") is False:
        prior = {"curation_run_id": "old", "accepted": True}
        nxt = {"curation_run_id": "new", "accepted": True}
        row = supersede(prior, nxt)
        assert row["prior_deleted"] is False
        assert row["successor_current_belief"] is True
    challenger = persist_challenger(tmp_path, build_curation_run(
        security_guid="sec-nvda", symbol="NVDA", task_type="research_curation",
        prior_curation_id=None, prior_curation_version=0, evidence_delta_hash=f"c{case['id']}",
        input_evidence_refs=["e1"], prompt_version="p1", process_id="oauth",
        requested_policy="CHALLENGER", executed_policy="CHALLENGER", model_id="oauth",
        accepted=True, material_change=False,
    ), parent_run_id="parent")
    assert challenger["flattened_into_parent"] is False
