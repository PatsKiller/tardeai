"""Nine-stage facts use explicit source evidence and never grant authority."""
from __future__ import annotations

import copy
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("tested_work_pipeline_flow_facts", Path(__file__).resolve().parents[1] / "scripts/lib/work_pipeline_flow_facts.py")
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)
NOW = datetime(2032, 4, 12, 15, tzinfo=timezone.utc)
AT, CREATED, GREEN = "2032-04-12T14:50:00Z", "2032-04-12T10:00:00Z", "2032-04-12T12:00:00Z"
HEAD, OTHER = "a" * 40, "b" * 40


def pr(**updates):
    return {"number": 2501, "head_sha": HEAD, "state": "open", "created_at": CREATED,
            "updated_at": AT, "draft": False,
            "ci": {"state": "green", "passed": 3, "total": 3, "head_sha": HEAD, "as_of": AT, "completed_at": GREEN},
            "review_required_count": 1, "review_required_source": "review_policy", "review_required_as_of": AT,
            **updates}


def bundle(**updates):
    return {"owner": {"value": {"session": "author", "vendor": "codex"}, "source": "claim_board", "as_of": AT},
            "timeline": [], "gaps": [], "live": {"value": False, "gap": "not_verified"},
            "review": {"state": "MERGE", "head_sha": HEAD, "source": "coordinator_ledger", "evidence_class": "reported_review_not_approval",
                       "records": [{"reviewer_session": "reviewer", "verdict": "MERGE", "observed_at": AT}]}, **updates}


def waiting(**updates):
    return {"complete": True, "pending_count": 0, "actionable_items": [], "actionable_count": 0, **updates}


def operator(**updates):
    return {"id": "policy:2501", "pr": 2501, "source_sha": HEAD, "next_actor": "operator",
            "source": "canonical_queue", "source_as_of": AT, **updates}


def project(p=None, b=None, w=None, **kwargs):
    item = {"id": "PR-2501", "pr_number": 2501, "stage": "in_batch"}
    b = bundle() if b is None else b
    coordination = {"by_pr": {2501: b}, "claims": [], "gaps": [],
                    "sources": {name: {"status": "OK", "as_of": AT} for name in M.REQUIRED_SOURCES}}
    original = copy.deepcopy(coordination)
    w = waiting() if w is None else w
    result = M.enrich([item], coordination, [pr() if p is None else p], w, NOW, census_as_of=AT, **kwargs)
    assert result["approvals"] is w
    assert coordination == original
    assert item["coordination"] is result["by_pr"][2501]
    return item["coordination"], result


@pytest.mark.parametrize("p,b,stage,actor", [
    (pr(draft=True), bundle(), "pr_open", "agent"),
    (pr(ci={"state": "pending", "head_sha": HEAD, "passed": 1, "total": 3, "as_of": AT}), bundle(), "checks", "agent"),
    (pr(), bundle(review={"state": "UNKNOWN", "head_sha": HEAD, "records": []}), "review", "coordinator"),
    (pr(), bundle(), "review", "coordinator"),
    (pr(state="merged", merged_at=AT), bundle(), "merged", "coordinator"),
    (pr(state="merged", merged_at=AT), bundle(live={"value": True, "source": "verified_receipt", "as_of": AT}), "live", "coordinator"),
])
def test_stage_matrix_never_infers_operator_from_green_or_legacy_batch(p, b, stage, actor):
    facts, _ = project(p, b)
    assert facts["current_stage"]["value"] == stage
    assert facts["next_actor"]["value"] == actor
    assert facts["created_at"]["value"] == CREATED


def test_exact_canonical_operator_member_after_reported_reviews_needs_operator():
    w = waiting(actionable_items=[operator()], actionable_count=1, pending_count=1)
    facts, result = project(w=w)
    assert facts["current_stage"]["value"] == "approval" and facts["next_actor"]["value"] == "operator"
    assert facts["stage_since"]["value"] is None
    assert facts["stage_since"]["gap"] == "transition_not_recorded"
    assert result["approvals"] is w


@pytest.mark.parametrize("changed", [{"source_sha": OTHER}, {"pr": 2502}, {"next_actor": "agent"},
                                      {"source_as_of": None}, {"source_as_of": "2032-04-13T00:00:00Z"}])
def test_wrong_head_actor_member_or_clock_never_means_operator(changed):
    facts, _ = project(w=waiting(actionable_items=[operator(**changed)]))
    assert facts["current_stage"]["value"] == "review"
    assert facts["next_actor"]["value"] == "coordinator"


@pytest.mark.parametrize("quota", [None, 0, True, "1"])
def test_unknown_or_invalid_review_quota_stays_with_coordinator(quota):
    facts, _ = project(pr(review_required_count=quota), w=waiting(actionable_items=[operator()]))
    assert facts["current_stage"]["value"] == "review"
    assert facts["review"]["required_count"] is None and facts["review"]["required_gap"]


def test_missing_quota_provenance_or_duplicate_self_review_does_not_complete_review():
    p = pr(review_required_source=None)
    assert project(p, w=waiting(actionable_items=[operator()]))[0]["next_actor"]["value"] == "coordinator"
    b = bundle()
    b["review"]["records"] *= 2
    facts, _ = project(pr(review_required_count=2), b, waiting(actionable_items=[operator()]))
    assert facts["review"]["reported_complete"] is False
    b["review"]["records"][0]["reviewer_session"] = "author"
    assert project(b=b, w=waiting(actionable_items=[operator()]))[0]["next_actor"]["value"] == "coordinator"


def test_blocked_stale_or_undated_reviews_cannot_move_to_operator():
    for review in ({"state": "BLOCK", "head_sha": HEAD, "records": []},
                   {**bundle()["review"], "head_sha": OTHER},
                   {**bundle()["review"], "gap": "invalid_timestamp"},
                   {**bundle()["review"], "records": [{"reviewer_session": "r", "verdict": "MERGE", "observed_at": None}]}):
        facts, _ = project(b=bundle(review=review), w=waiting(actionable_items=[operator()]))
        assert facts["current_stage"]["value"] == "review"


@pytest.mark.parametrize("ci", [{"state": "green", "head_sha": OTHER, "passed": 3, "total": 3, "as_of": AT},
                                 {"state": "green", "head_sha": HEAD, "total": 3, "as_of": AT},
                                 {"state": "green", "head_sha": HEAD, "passed": 3, "total": 3},
                                 {"state": "green", "head_sha": HEAD, "passed": 0, "total": 0, "as_of": AT}])
def test_green_word_without_measured_exact_head_checks_stays_checks(ci):
    facts, _ = project(pr(ci=ci))
    assert facts["current_stage"]["value"] == "checks"
    assert facts["ci"]["passed"] is None and facts["ci"]["gap"]


def test_transition_clocks_never_substitute_pr_update_or_snapshot_time():
    facts, _ = project(pr(ci={"state": "failing", "head_sha": HEAD, "passed": 2, "total": 3, "as_of": AT}))
    assert facts["stage_since"]["value"] is None
    assert facts["stuck"]["value"] is None
    assert project(pr(draft=True))[0]["stage_since"]["value"] == CREATED
    assert project()[0]["stage_since"]["value"] is None
    transition = {"kind": "stage_transition", "to_stage": "checks", "head_sha": HEAD, "as_of": GREEN, "source": "ledger"}
    assert project(pr(ci={"state": "pending"}), bundle(timeline=[transition]))[0]["stage_since"]["value"] == GREEN
    transition["head_sha"] = OTHER
    assert project(pr(ci={"state": "pending"}), bundle(timeline=[transition]))[0]["stage_since"]["value"] is None


@pytest.mark.parametrize("threshold", [None, 0, -1, True, float("nan")])
def test_stuck_requires_declared_positive_threshold_and_source_stage_clock(threshold):
    facts, _ = project(pr(draft=True), stuck_after_minutes=threshold)
    assert facts["stuck"]["value"] is None
    assert project(pr(draft=True), stuck_after_minutes=120)[0]["stuck"]["value"] is True


def test_non_pr_work_uses_claim_proof_and_only_typed_exact_publication():
    claims = [{"claim_id": "claim", "session": "worker", "head_sha": HEAD, "started_at": CREATED,
               "stages": {"building": GREEN}}]
    items = [{"id": "claim-only", "how": {"claim_ids": ["claim"]}, "stage": "building"}]
    c = {"claims": claims, "by_pr": {}, "sources": {}, "gaps": []}
    result = M.enrich(items, c, [], waiting(), NOW, census_as_of=AT)
    facts = result["by_item"]["claim-only"]
    assert facts["current_stage"]["value"] == "building" and facts["stage_since"]["value"] == GREEN
    assert facts["created_at"]["value"] == CREATED
    event = {"kind": "publication_observation", "state": "published", "head_sha": HEAD, "source": "publication_ledger", "as_of": AT}
    items[0]["coordination"]["timeline"] = [event]
    assert M.enrich(items, c, [], waiting(), NOW, census_as_of=AT)["by_item"]["claim-only"]["current_stage"]["value"] == "uploaded"
    event["head_sha"] = OTHER
    assert M.enrich(items, c, [], waiting(), NOW, census_as_of=AT)["by_item"]["claim-only"]["current_stage"]["value"] == "building"


def test_task_only_created_clock_and_missing_sources_preserve_unknown_totals():
    item = {"id": "task-only", "created_at": CREATED}
    c = {"by_pr": {}, "sources": {"plans": {"status": "UNAVAILABLE", "gap": "missing"}}, "gaps": []}
    result = M.enrich([item], c, [], waiting(complete=False), NOW)
    assert item["coordination"]["current_stage"]["value"] == "requested"
    assert item["coordination"]["stage_since"]["value"] == CREATED
    assert result["complete"] is False and result["status"] == "PARTIAL"
    assert {g["source"] for g in result["gaps"]} >= {"plans", "census", "operator_approvals"}


def test_complete_sources_and_canonical_members_share_identity_without_mutation():
    facts, result = project()
    assert result["complete"] is True and result["status"] == "OK"
    assert facts["ci"]["passed"] == facts["ci"]["total"] == 3
    assert facts["ci"]["head_sha"] == HEAD
    assert facts["review"]["required_count"] == 1
    with pytest.raises(ValueError, match="aware"):
        M.enrich([], {}, [], waiting(), NOW.replace(tzinfo=None))



def test_known_quota_with_declared_source_gap_does_not_complete_review():
    facts, _ = project(pr(review_required_gap="policy_source_partial"), w=waiting(actionable_items=[operator()]))
    assert facts["current_stage"]["value"] == "review"
    assert facts["review"]["required_count"] is None
    assert facts["review"]["required_gap"] == "policy_source_partial"



def test_complete_flag_without_canonical_member_count_is_not_complete():
    for w in (waiting(actionable_items=None), waiting(actionable_count=99), waiting(actionable_count=False)):
        assert project(w=w)[1]["complete"] is False


def test_completed_live_item_is_not_stuck():
    facts, _ = project(b=bundle(live={"value": True, "source": "verified_receipt", "as_of": CREATED}))
    assert facts["current_stage"]["value"] == "live"
    assert facts["stuck"]["value"] is False



def test_review_clock_requires_explicit_source_event_and_latest_reentry_wins():
    first = {"kind": "stage_transition", "to_stage": "review", "head_sha": HEAD, "as_of": GREEN, "source": "ledger"}
    second = {**first, "as_of": AT}
    facts, _ = project(b=bundle(timeline=[first, second]))
    assert facts["stage_since"]["value"] == AT
    assert project(b=bundle(timeline=[{**first, "source": None}]))[0]["stage_since"]["value"] is None


def test_checks_phase_clock_is_explicit_and_bound_to_current_run_head():
    ci = {"state": "pending", "head_sha": HEAD, "passed": 1, "total": 3, "as_of": AT, "started_at": GREEN}
    facts, _ = project(pr(ci=ci))
    assert facts["stage_since"]["value"] == GREEN
    assert facts["stage_since"]["basis"] == "checks_run_started"
    ci["head_sha"] = OTHER
    assert project(pr(ci=ci))[0]["stage_since"]["value"] is None


def test_two_independent_reported_reviews_satisfy_supplied_quota():
    b = bundle()
    b["review"]["records"].append({"reviewer_session": "second-reviewer", "verdict": "MERGE", "observed_at": AT})
    facts, _ = project(pr(review_required_count=2), b, waiting(actionable_items=[operator()]))
    assert facts["review"]["reported_complete"] is True
    assert facts["current_stage"]["value"] == "approval"



def test_unassigned_requested_draft_and_checks_route_to_coordinator_for_assignment():
    for p in (pr(draft=True), pr(ci={"state": "pending"})):
        facts, _ = project(p, bundle(owner={"value": None}))
        assert facts["next_actor"]["value"] == "coordinator"
        assert "Assign an engineer" in facts["next_action"]["value"]
    item = {"id": "unassigned-task", "created_at": CREATED}
    result = M.enrich([item], {}, [], waiting(), NOW, census_as_of=AT)
    assert result["by_item"]["unassigned-task"]["next_actor"]["value"] == "coordinator"


def test_current_worklog_next_step_is_preserved_without_promoting_its_operator_prefix():
    note = {"value": "Operator: inspect the prepared evidence packet", "source": "claim_worklog", "as_of": GREEN, "gap": None}
    for p in (pr(draft=True), pr(ci={"state": "pending"})):
        facts, _ = project(p, bundle(next_action=note))
        assert facts["next_action"] == note
        assert facts["next_actor"]["value"] == "agent"
    stale = {**note, "gap": "worklog_incomplete"}
    assert project(pr(draft=True), bundle(next_action=stale))[0]["next_action"] != stale
    for p, b in ((pr(state="merged", merged_at=AT), bundle(next_action=note)),
                 (pr(), bundle(next_action=note, live={"value": True, "source": "verified_receipt", "as_of": AT}))):
        assert project(p, b)[0]["next_action"] != note


def test_exact_approval_action_and_building_publication_producer_gap():
    member = operator(next_action="Read the exact policy change and record its approval line.")
    facts, _ = project(w=waiting(actionable_items=[member], actionable_count=1, pending_count=1))
    assert facts["next_action"]["value"] == member["next_action"]
    assert facts["next_action"]["source"] == member["source"]
    assert facts["next_action"]["as_of"] == AT
    item = {"id": "building", "stage": "building", "how": {"claim_ids": ["c"]}}
    c = {"claims": [{"claim_id": "c", "session": "worker", "started_at": CREATED, "stages": {"building": GREEN}}]}
    result = M.enrich([item], c, [], waiting(), NOW, census_as_of=AT)
    assert {"source": "publication_ledger", "reason": "publication_not_observed"} in result["by_item"]["building"]["gaps"]
