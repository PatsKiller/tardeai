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


def test_hotfix_landed_detects_skip_tolerant_yml():
    assert hotfix_landed("merge_conditions:\n  - check-skipped=cio-hardening\n") is True
    assert hotfix_landed("batch_size: 5\ncheck-success=*\n") is False
