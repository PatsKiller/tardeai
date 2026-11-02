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
