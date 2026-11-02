"""Mergify Dequeued classifier + hotfix detector (hermetic)."""

from __future__ import annotations

import json

from scripts.lib.mergify_queue_monitor import (
    classify_dequeue,
    hotfix_landed,
    parse_mergify_payload,
)


SAMPLE_DEQUEUE = """\
<details>
<summary>Left the queue after 2 minutes</summary>

Reason: Checks failed on draft #2224

-*- Mergify Payload -*-
{"state": "dequeued", "dequeue_reason": {"code": "CHECKS_FAILED", "message": "Checks failed on draft #2224"}}
-*- Mergify Payload End -*-
</details>
"""


def test_parse_mergify_payload_extracts_checks_failed():
    payload = parse_mergify_payload(SAMPLE_DEQUEUE)
    assert payload is not None
    assert payload["state"] == "dequeued"
    assert payload["dequeue_reason"]["code"] == "CHECKS_FAILED"


def test_classify_draft_skip_waits_for_hotfix_when_checks_green():
    plan = classify_dequeue(
        reason_code="CHECKS_FAILED",
        body=SAMPLE_DEQUEUE,
        mergeable="MERGEABLE",
        checks={
            "cio-hardening": "SUCCESS",
            "agent-governance": "SUCCESS",
            "release-readiness": "SUCCESS",
            "ci-gate": "SUCCESS",
        },
        hotfix_on_main=False,
    )
    assert plan.classification == "DRAFT_SKIP_FALSE_FAIL"
    assert plan.action == "wait_hotfix"
    assert plan.requeue is False
    assert plan.wake_claim is True
    assert plan.page_p1 is True


def test_classify_draft_skip_auto_requeues_after_hotfix():
    plan = classify_dequeue(
        reason_code="CHECKS_FAILED",
        body=SAMPLE_DEQUEUE,
        mergeable="MERGEABLE",
        checks={
            "cio-hardening": "SUCCESS",
            "agent-governance": "SUCCESS",
            "release-readiness": "SUCCESS",
            "ci-gate": "SUCCESS",
        },
        hotfix_on_main=True,
    )
    assert plan.action == "auto_requeue"
    assert plan.requeue is True
    assert plan.page_p1 is False


def test_classify_real_ci_fail_does_not_requeue():
    plan = classify_dequeue(
        reason_code="CHECKS_FAILED",
        body=SAMPLE_DEQUEUE,
        mergeable="MERGEABLE",
        checks={"cio-hardening": "FAILURE", "ci-gate": "SUCCESS"},
        hotfix_on_main=True,
    )
    assert plan.classification == "REAL_CI_FAIL"
    assert plan.action == "real_ci_fail"
    assert plan.requeue is False
    assert plan.wake_claim is True


def test_classify_conflicts():
    plan = classify_dequeue(
        reason_code="CONFLICTS",
        body="Conflicts with base branch",
        mergeable="CONFLICTING",
        checks={},
        hotfix_on_main=True,
    )
    assert plan.classification == "CONFLICTS"
    assert plan.action == "conflict_rebase"
    assert plan.requeue is False
    assert "rebase" in plan.message.lower()


def test_classify_cleared_conflict_auto_requeues_after_hotfix():
    """Historical CONFLICTS dequeue + now MERGEABLE + green checks → resubmit, not dead end."""
    green = {
        "cio-hardening": "SUCCESS",
        "agent-governance": "SUCCESS",
        "release-readiness": "SUCCESS",
        "ci-gate": "SUCCESS",
    }
    waiting = classify_dequeue(
        reason_code="CONFLICTS",
        body="Conflicts with base branch",
        mergeable="MERGEABLE",
        checks=green,
        hotfix_on_main=False,
    )
    assert waiting.action == "wait_hotfix"
    assert waiting.requeue is False
    ready = classify_dequeue(
        reason_code="CONFLICTS",
        body="Conflicts with base branch",
        mergeable="MERGEABLE",
        checks=green,
        hotfix_on_main=True,
    )
    assert ready.classification == "CLEARED_READY"
    assert ready.action == "auto_requeue"
    assert ready.requeue is True


def test_hotfix_landed_detects_skip_tolerant_yml():
    assert hotfix_landed("merge_conditions:\n  - check-skipped=cio-hardening\n") is True
    assert hotfix_landed("batch_size: 5\ncheck-success=*\n") is False


def test_a_red_non_required_check_is_a_real_failure_not_a_requeue():
    """2026-11-01: a PR can be green on all four required checks and red on `secret-scan`.

    Requeueing that PR would put it straight back on the queue to fail again; the run that
    actually reported must win, and the dequeue must be classified as a real CI failure.
    """
    plan = classify_dequeue(
        reason_code="CHECKS_FAILED",
        body=SAMPLE_DEQUEUE,
        mergeable="MERGEABLE",
        checks={
            "cio-hardening": "SUCCESS",
            "agent-governance": "SUCCESS",
            "release-readiness": "SUCCESS",
            "ci-gate": "SUCCESS",
            "secret-scan": "FAILURE",
        },
        hotfix_on_main=False,
    )
    assert plan.classification == "REAL_CI_FAIL"
    assert plan.requeue is False
    assert "secret-scan" in str(plan.detail)


def test_a_running_check_waits_instead_of_paging_a_false_failure():
    """Regression the reviewer reproduced: {"shard 0": ""} became REAL_CI_FAIL + a P1 page."""
    plan = classify_dequeue(
        reason_code="CHECKS_FAILED",
        body=SAMPLE_DEQUEUE,
        mergeable="MERGEABLE",
        checks={"shard 0": [""], "cio-hardening": ["PENDING"]},
        hotfix_on_main=False,
    )
    assert plan.classification == "WAIT"
    assert plan.page_p1 is False and plan.requeue is False


def test_a_finished_failure_after_a_skipped_run_still_blocks():
    plan = classify_dequeue(
        reason_code="CHECKS_FAILED",
        body=SAMPLE_DEQUEUE,
        mergeable="MERGEABLE",
        checks={"secret-scan": ["SKIPPED", "FAILURE"], "cio-hardening": ["SUCCESS"]},
        hotfix_on_main=False,
    )
    assert plan.classification == "REAL_CI_FAIL"
    assert plan.requeue is False


# ---------------------------------------------------------------- review round 1 (#2486)
def _rollup(name, conclusion=None, *, state=None, workflow=None, status="COMPLETED"):
    row = {"name": name, "status": status, "conclusion": conclusion}
    if state is not None:
        row = {"context": name, "state": state, "startedAt": "2026-11-02T03:00:00Z"}
    if workflow:
        row["workflowName"] = workflow
    return row


def _plan(rollup, *, checks=None, mergeable="MERGEABLE", reason="CHECKS_FAILED", body=""):
    from scripts.lib.mergify_queue_monitor import classify_dequeue

    return classify_dequeue(reason_code=reason, body=body, mergeable=mergeable,
                            rollup=rollup, hotfix_on_main=True, checks=checks)


def test_a_failed_check_beside_a_running_one_is_red_not_waited():
    plan = _plan([_rollup("cio-hardening", "FAILURE"),
                  _rollup("shard 0", status="IN_PROGRESS", conclusion=None)])
    assert plan.classification == "REAL_CI_FAIL"
    assert plan.requeue is False


def test_the_same_job_name_in_two_workflows_with_one_red_is_red():
    plan = _plan([_rollup("shard 0", "FAILURE", workflow="cio-full-suite-sharded"),
                  _rollup("shard 0", "SUCCESS", workflow="other-workflow")])
    assert plan.classification == "REAL_CI_FAIL"


def test_a_red_status_context_is_red():
    plan = _plan([_rollup("legacy/ci", state="FAILURE")])
    assert plan.classification == "REAL_CI_FAIL"


def test_an_unreadable_head_holds_and_never_requeues():
    plan = _plan(None)
    assert plan.classification == "UNMEASURED"
    assert plan.requeue is False and plan.page_p1 is False


def test_mergify_own_checks_are_never_graded():
    plan = _plan([_rollup("Mergify Merge Queue", "NEUTRAL"),
                  _rollup("Rule: Queue default", status="IN_PROGRESS"),
                  _rollup("Summary", "SUCCESS"),
                  _rollup("cio-hardening", "SUCCESS")])
    assert plan.classification != "REAL_CI_FAIL"
    assert plan.classification != "WAIT"


def test_wait_posts_no_comment_and_pages_once_after_the_limit(tmp_path, monkeypatch):
    import scripts.lib.mergify_queue_monitor as mqm

    monkeypatch.setattr(mqm, "fetch_main_mergify_yml", lambda repo=None: "")
    monkeypatch.setattr(mqm, "fetch_open_operator_merge_prs", lambda repo=None: [
        {"number": 7, "labels": [{"name": "operator-merge"}], "mergeable": "MERGEABLE"}])
    monkeypatch.setattr(mqm, "fetch_latest_dequeue_comment",
                        lambda pr, repo=None: ("", {"state": "dequeued", "dequeue_reason": {"code": "CHECKS_FAILED"}}))
    monkeypatch.setattr(mqm, "fetch_head_check_rollup",
                        lambda pr, repo=None: [_rollup("shard 0", status="IN_PROGRESS", conclusion=None)])
    comments = []
    monkeypatch.setattr(mqm, "post_pr_comment", lambda pr, body, repo=None: comments.append(body) or True)
    pages = []
    import scripts.delivery_failure_alerts as dfa
    monkeypatch.setattr(dfa, "page_p1", lambda **kw: pages.append(kw))

    first = mqm.run_once(dry_run=False, root=tmp_path)
    assert first["actions"][0].get("waiting") is True
    assert comments == []  # WAIT never comments

    # age the wait clock past the configured limit: exactly one page, still no comment
    ledger = json.loads((tmp_path / "mergify_wait_since.json").read_text())
    ledger["7"] = "2026-11-02T00:00:00Z"
    (tmp_path / "mergify_wait_since.json").write_text(json.dumps(ledger))
    second = mqm.run_once(dry_run=False, root=tmp_path)
    assert second["actions"][0].get("paged_stuck") is True
    assert len(pages) == 1
    assert comments == []
