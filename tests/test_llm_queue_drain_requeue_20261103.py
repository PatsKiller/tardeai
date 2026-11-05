"""LLM queue drain/requeue contract: the 20% trigger, idempotent retries, one incident per exhausted job, drained.

Operator 2026-11-02 addendum: at a 20% error rate requeue every failed job with a delay that grows each time,
until the queue is drained. Pure policy: these tests read config/llm_queue_drain.json only. Hermetic.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import llm_queue_drain_policy as dp  # noqa: E402

POLICY = dp.load_policy()


def offpeak(now):
    return False


def policy_with(**changes):
    """A copy of the shipped policy with drain_requeue keys overridden, to prove values come from config."""
    pol = copy.deepcopy(POLICY)
    pol["drain_requeue"].update(changes)
    return pol


def job(**changes):
    base = {"job_id": 42, "attempt": 1, "status": "failed", "root_cause": "HTTP 500"}
    base.update(changes)
    return base


# --- 1. failure-rate trigger -------------------------------------------------------------------------------


@pytest.mark.parametrize("total,failed", [(100, 20), (10, 2), (5, 1), (1, 1)])
def test_error_rate_at_threshold_triggers_drain(total, failed):
    assert dp.failure_rate(total, failed) >= POLICY["drain_requeue"]["failure_rate_threshold"]
    assert dp.drain_triggered(total, failed, POLICY) is True
    assert dp.rate_triggers_drain(dp.failure_rate(total, failed), POLICY) is True


@pytest.mark.parametrize("total,failed", [(100, 19), (100, 0), (1000, 199), (50, 9)])
def test_error_rate_below_threshold_does_not_trigger_drain(total, failed):
    assert dp.failure_rate(total, failed) < POLICY["drain_requeue"]["failure_rate_threshold"]
    assert dp.drain_triggered(total, failed, POLICY) is False
    assert dp.rate_triggers_drain(dp.failure_rate(total, failed), POLICY) is False


def test_zero_job_window_does_not_divide_by_zero():
    assert dp.failure_rate(0, 0) == 0.0
    assert dp.failure_rate(0, 7) == 0.0
    assert dp.drain_triggered(0, 0, POLICY) is False


def test_threshold_is_read_from_config_not_hardcoded():
    pol = policy_with(failure_rate_threshold=0.5)
    assert dp.drain_triggered(100, 20, pol) is False
    assert dp.drain_triggered(100, 50, pol) is True


# --- 2. requeue: never dropped, idempotent, growing config delay, existing provider order ------------------


def test_every_failed_job_is_requeued_with_the_configured_first_delay():
    jobs = [job(job_id=i, attempt=1) for i in range(1, 6)]
    plans = dp.requeue_batch(jobs, POLICY, is_deepseek_peak=offpeak)
    assert len(plans) == 5
    assert {plan["job_id"] for plan in plans} == {1, 2, 3, 4, 5}
    assert all(plan["action"] == "requeue" for plan in plans)
    assert all(plan["next_attempt"] == 2 for plan in plans)
    assert all(plan["delay_s"] == POLICY["drain_requeue"]["retry_delay_seconds"][0] for plan in plans)


def test_retry_delay_grows_per_attempt_and_comes_from_config():
    delays = POLICY["drain_requeue"]["retry_delay_seconds"]
    assert len(delays) >= 2
    assert [dp.retry_delay_s(attempt, POLICY) for attempt in range(1, len(delays) + 1)] == list(delays)
    assert all(a < b for a, b in zip(delays, delays[1:])), "the shipped delay schedule must grow"
    custom = policy_with(retry_delay_seconds=[7, 70])
    assert [dp.retry_delay_s(attempt, custom) for attempt in (1, 2, 3)] == [7, 70, 70]


def test_requeue_key_is_job_id_plus_attempt():
    assert dp.requeue_key(42, 1) == "42:1"
    assert dp.requeue_key(42, 2) == "42:2"
    assert dp.requeue_key(42, 1) != dp.requeue_key(42, 2)
    with pytest.raises(ValueError):
        dp.requeue_key(None, 1)


def test_requeueing_the_same_job_twice_creates_one_runnable_copy():
    failed = job(attempt=1)
    plans = dp.requeue_batch([failed, failed], POLICY, is_deepseek_peak=offpeak)
    assert len(plans) == 1
    assert plans[0]["key"] == dp.requeue_key(42, 1)
    again = dp.requeue_batch(
        [failed], POLICY, already_queued=[plan["key"] for plan in plans], is_deepseek_peak=offpeak
    )
    assert again == [], "an already-enqueued job must not be enqueued twice"


def test_a_later_attempt_is_a_new_requeue_not_a_duplicate():
    plans = dp.requeue_batch([job(attempt=1), job(attempt=2)], POLICY, is_deepseek_peak=offpeak)
    assert [plan["key"] for plan in plans] == ["42:1", "42:2"]
    assert [plan["next_attempt"] for plan in plans] == [2, 3]


def test_retry_reuses_the_configured_provider_order():
    plan = dp.requeue_plan(job(), POLICY, is_deepseek_peak=offpeak)
    assert plan["providers"] == POLICY["provider_order"]
    reordered = copy.deepcopy(POLICY)
    reordered["provider_order"] = ["chatgpt", "anthropic"]
    assert dp.requeue_plan(job(), reordered, is_deepseek_peak=offpeak)["providers"] == ["chatgpt", "anthropic"]


def test_retry_reuses_provider_chain_peak_handling():
    plan = dp.requeue_plan(job(), POLICY, is_deepseek_peak=lambda now: True)
    assert plan["providers"] == ["anthropic", "grok", "chatgpt"]


# --- 3. max attempts: one incident per job, work stays accounted for, requeued after the fix ---------------


def test_last_allowed_attempt_holds_and_becomes_one_incident():
    pol = policy_with(max_attempts=3)
    plans = dp.requeue_batch([job(attempt=3)], pol, is_deepseek_peak=offpeak)
    assert plans[0]["action"] == "hold"
    assert plans[0]["next_attempt"] is None
    assert plans[0]["incident_key"] == "job:42"
    held = dp.incidents(plans)
    assert len(held) == 1
    assert held[0]["incident_key"] == "job:42"
    assert held[0]["job_id"] == 42
    assert held[0]["root_cause"] == "HTTP 500"


def test_one_incident_per_job_not_one_per_attempt():
    pol = policy_with(max_attempts=3)
    plans = dp.requeue_batch(
        [job(attempt=3), job(attempt=4), job(attempt=5)], pol, is_deepseek_peak=offpeak
    )
    assert len(plans) == 3
    assert len(dp.incidents(plans)) == 1


def test_distinct_failed_jobs_get_distinct_incidents():
    pol = policy_with(max_attempts=3)
    plans = dp.requeue_batch([job(job_id=1, attempt=3), job(job_id=2, attempt=3)], pol, is_deepseek_peak=offpeak)
    assert {incident["incident_key"] for incident in dp.incidents(plans)} == {"job:1", "job:2"}


def test_incident_key_falls_back_to_root_cause_without_a_job_id():
    assert dp.incident_key(None, "model 400") == "root:model 400"


def test_max_attempts_comes_from_config():
    assert dp.requeue_plan(job(attempt=3), policy_with(max_attempts=5), is_deepseek_peak=offpeak)["action"] == "requeue"
    assert dp.requeue_plan(job(attempt=3), policy_with(max_attempts=2), is_deepseek_peak=offpeak)["action"] == "hold"


def test_exhausted_job_stays_failed_and_is_requeued_after_the_fix():
    pol = policy_with(max_attempts=3)
    held_job = job(attempt=3, status="failed")
    plans = dp.requeue_batch([held_job], pol, is_deepseek_peak=offpeak)
    assert plans[0]["action"] == "hold", "nothing is silently dropped from the accounting"

    state = dp.drain_state([held_job])
    assert state["failed"] == 1
    assert state["status"] != "drained"

    fixed = dp.requeue_plan(held_job, pol, after_fix=True, is_deepseek_peak=offpeak)
    assert fixed["action"] == "requeue"
    assert fixed["next_attempt"] == 1
    assert fixed["reset_attempt"] is True
    assert fixed["delay_s"] == pol["drain_requeue"]["retry_delay_seconds"][0]


def test_after_fix_requeue_is_idempotent():
    pol = policy_with(max_attempts=3)
    plan = dp.requeue_plan(job(attempt=3), pol, after_fix=True, is_deepseek_peak=offpeak)
    again = dp.requeue_batch(
        [job(attempt=3)], pol, after_fix=True, already_queued=[plan["key"]], is_deepseek_peak=offpeak
    )
    assert again == []


# --- 4. drain predicate: drained only when no failed job is left -------------------------------------------


def test_drain_state_labels_queued_retrying_drained():
    assert dp.drain_state([])["status"] == "drained"
    assert dp.drain_state([{"job_id": 1, "status": "pending"}])["status"] == "queued"
    assert dp.drain_state([{"job_id": 1, "status": "retrying"}])["status"] == "retrying"
    assert dp.drain_state([{"job_id": 1, "status": "done"}])["status"] == "drained"


def test_drain_state_counts():
    state = dp.drain_state(
        [
            {"job_id": 1, "status": "pending"},
            {"job_id": 2, "status": "running"},
            {"job_id": 3, "status": "retrying"},
            {"job_id": 4, "status": "failed"},
            {"job_id": 5, "status": "done"},
        ]
    )
    assert state["queued"] == 2
    assert state["retrying"] == 1
    assert state["failed"] == 1
    assert state["done"] == 1
    assert state["status"] == "retrying"


@pytest.mark.parametrize(
    "jobs",
    [
        [{"job_id": 1, "status": "failed", "held": True}],
        [{"job_id": 1, "status": "failed"}, {"job_id": 2, "status": "done"}],
        [{"job_id": 1, "status": "pending"}, {"job_id": 2, "status": "failed"}],
        [{"job_id": 1, "status": "held_failed"}],
        [{"job_id": 1, "status": "failed"}, {"job_id": 2, "status": "retrying"}],
    ],
)
def test_any_held_failed_job_is_never_drained(jobs):
    state = dp.drain_state(jobs)
    assert state["status"] != "drained"
    assert state["drained"] is False
    assert dp.is_drained(jobs) is False


def test_drained_only_when_nothing_failed_and_nothing_queued():
    assert dp.is_drained([]) is True
    assert dp.is_drained([{"job_id": 1, "status": "done"}, {"job_id": 2, "status": "cancelled"}]) is True
    assert dp.is_drained([{"job_id": 1, "status": "pending"}]) is False
