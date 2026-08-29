"""Wave 2 slices 19 / 20 / 21 — research failure truth and replay policy.

19  histogram over the trailing window, classified, with `is_worker_bug`.
20  an execution-language failure is never requeued.
21  a truncated failure is retryable at most once per plan per day.

READ_ONLY_ADVISORY. MBI=0. Nothing here requeues, retries or raises a cap.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.cio_research_fail_policy import (
    COST_CAP,
    EXECUTION_LANGUAGE,
    PROVIDER_ERROR,
    SCHEMA_INVALID,
    TIMEOUT,
    TRUNCATED,
    build_fail_histogram,
    classify_failure,
    replay_decision,
)

NOW = datetime(2026, 8, 29, 2, 0, tzinfo=timezone.utc)

# Verbatim shapes from the CURRENT ledger.
E_429 = ('bridge HTTP 429: {"error": {"code": "COST_CAP_EXCEEDED", "message": '
         '"Cost cap would be exceeded: {\'allow\': False, \'reason\': \'COST_CAP_EXCEEDED\'}"}}')
E_500_RESERVATION = ('bridge HTTP 500: {"error": {"code": "RESERVATION_FAILED", "message": '
                     '"COST_CAP_EXCEEDED: daily request cap", "status": 500}}')
E_EXEC = "execution language not allowed in research output: The advisory on DIV says trim"
E_TRUNC = 'model JSON truncated/incomplete: {"as_of":"2026-08-14T03:10:44Z","answers":[{'
E_PROVIDER = ('bridge HTTP 500: {"error": {"code": "PROVIDER_ERROR", "message": '
              '"RealProvider failure: RuntimeError", "status": 500}}')


# ── 19: classification ───────────────────────────────────────────────────────

@pytest.mark.parametrize("error,expected", [
    (E_429, COST_CAP),
    (E_500_RESERVATION, COST_CAP),
    (E_EXEC, EXECUTION_LANGUAGE),
    (E_TRUNC, TRUNCATED),
    (E_PROVIDER, PROVIDER_ERROR),
    ("questions_required", SCHEMA_INVALID),
    ("confidence_out_of_range", SCHEMA_INVALID),
    ("timed out", TIMEOUT),
])
def test_failure_classes(error, expected):
    assert classify_failure(error)["class"] == expected


def test_reservation_failed_is_the_cost_cap_wearing_a_500():
    """The 500 that is not a server fault — the whole point of the classifier."""
    info = classify_failure(E_500_RESERVATION)
    assert info["class"] == COST_CAP
    assert info["code"] == "RESERVATION_FAILED"   # the code alone would mislead
    assert info["is_worker_bug"] is False
    assert info["retryable"] is False
    assert "not a worker bug" in info["note"]


def test_no_failure_class_is_ever_a_worker_bug():
    for error in (E_429, E_500_RESERVATION, E_EXEC, E_TRUNC, E_PROVIDER, "timed out", "??"):
        assert classify_failure(error)["is_worker_bug"] is False


def test_classify_never_raises_on_junk():
    for junk in (None, "", 0, {"a": 1}, []):
        assert classify_failure(junk)["class"]


# ── 19: histogram ────────────────────────────────────────────────────────────

def _row(error, days_ago, plan_id="plan_1"):
    return {
        "event": "HERMES_RESEARCH_FAILED",
        "error": error,
        "plan_id": plan_id,
        "updated_ts": (NOW - timedelta(days=days_ago)).isoformat(),
    }


def test_histogram_counts_only_the_window_and_says_what_it_dropped():
    rows = [_row(E_429, 1), _row(E_EXEC, 2), _row(E_TRUNC, 3), _row(E_429, 30)]
    rows.append({"event": "HERMES_RESEARCH_FAILED", "error": E_429})   # undated
    h = build_fail_histogram(rows, window_days=7, now=NOW)
    assert h["failures_total_all_time"] == 5
    assert h["failures_in_window"] == 3
    assert h["undated_rows"] == 1
    assert h["by_class"] == {COST_CAP: 1, EXECUTION_LANGUAGE: 1, TRUNCATED: 1}


def test_histogram_separates_retryable_from_non_retryable():
    rows = [_row(E_429, 1), _row(E_500_RESERVATION, 1), _row(E_EXEC, 1), _row(E_TRUNC, 1)]
    h = build_fail_histogram(rows, window_days=7, now=NOW)
    assert h["retryable_n"] == 1            # only the truncated one
    assert h["non_retryable_n"] == 3
    assert h["worker_bug_n"] == 0


def test_histogram_counts_distinct_plans_per_class():
    rows = [_row(E_429, 1, "p1"), _row(E_429, 1, "p1"), _row(E_429, 1, "p2")]
    h = build_fail_histogram(rows, window_days=7, now=NOW)
    assert h["by_class"][COST_CAP] == 3
    assert h["by_class_policy"][COST_CAP]["distinct_plans"] == 2


def test_empty_ledger_is_zeros_not_a_crash():
    h = build_fail_histogram([], window_days=7, now=NOW)
    assert h["failures_in_window"] == 0
    assert h["by_class"] == {}
    assert h["retryable_n"] == 0


# ── 20: execution language is never requeued ─────────────────────────────────

def test_execution_language_is_never_requeued():
    d = replay_decision(prior_failures=[_row(E_EXEC, 1)], plan_id="p1", now=NOW)
    assert d["allow_enqueue"] is False
    assert d["reason"] == "execution_language_non_retryable"
    assert d["is_worker_bug"] is False


def test_execution_language_blocks_even_alongside_a_retryable_failure():
    """One correctly-refused output poisons the plan; a truncation cannot unblock it."""
    d = replay_decision(
        prior_failures=[_row(E_TRUNC, 3), _row(E_EXEC, 1)], plan_id="p1", now=NOW,
    )
    assert d["allow_enqueue"] is False
    assert d["reason"] == "execution_language_non_retryable"


def test_execution_language_block_never_raises_a_cap():
    d = replay_decision(prior_failures=[_row(E_EXEC, 1)], plan_id="p1", now=NOW)
    assert d["raises_cost_cap"] is False


# ── 21: truncated replay is capped at 1 per plan per day ─────────────────────

def test_truncated_allows_one_replay_when_the_failure_was_not_today():
    d = replay_decision(prior_failures=[_row(E_TRUNC, 3)], plan_id="p1", now=NOW)
    assert d["allow_enqueue"] is True
    assert d["reason"] == "retryable_within_cap"


def test_truncated_second_attempt_same_day_is_capped():
    d = replay_decision(prior_failures=[_row(E_TRUNC, 0)], plan_id="p1", now=NOW)
    assert d["allow_enqueue"] is False
    assert d["reason"] == "truncated_replay_cap_reached"
    assert d["failures_today"] == 1
    assert d["max_per_plan_per_day"] == 1


def test_cost_cap_only_history_waits_for_the_window():
    d = replay_decision(prior_failures=[_row(E_429, 1), _row(E_500_RESERVATION, 2)],
                        plan_id="p1", now=NOW)
    assert d["allow_enqueue"] is False
    assert d["reason"] == "cost_cap_wait_for_window"
    assert d["is_worker_bug"] is False


def test_no_prior_failure_is_allowed():
    d = replay_decision(prior_failures=[], plan_id="p1", now=NOW)
    assert d["allow_enqueue"] is True
    assert d["reason"] == "no_prior_failure"


# ── enqueue wiring ───────────────────────────────────────────────────────────

REQUEST = {
    "plan_id": "p1",
    "symbol": "SCHD",
    "situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
    "questions": [{"id": "q1", "text": "What changed in the SCHD concentration?"}],
}


def _enqueue(priors, **kw):
    from scripts.lib.hermes_research_queue import enqueue_research_request

    saved: list[dict] = []
    return enqueue_research_request(
        dict(REQUEST),
        find_in_flight_by_fingerprint=lambda fp: None,
        save_request=saved.append,
        update_request=lambda *a, **k: None,
        new_research_id=lambda: "res_new",
        list_prior_failures=lambda pid: priors,
        now=NOW,
        **kw,
    ), saved


def test_enqueue_is_blocked_and_nothing_is_saved_after_execution_language():
    res, saved = _enqueue([_row(E_EXEC, 1)])
    assert res.created is False
    assert res.reason == "blocked_non_retryable"
    assert res.status == "blocked"
    assert res.log_event["block_reason"] == "execution_language_non_retryable"
    assert res.log_event["is_worker_bug"] is False
    assert saved == []          # no request row written, no paid call queued


def test_enqueue_still_works_with_no_prior_failures():
    res, saved = _enqueue([])
    assert res.created is True
    assert res.reason == "created"
    assert len(saved) == 1


def test_enqueue_gate_is_opt_in_and_does_not_change_existing_callers():
    from scripts.lib.hermes_research_queue import enqueue_research_request

    saved: list[dict] = []
    res = enqueue_research_request(
        dict(REQUEST),
        find_in_flight_by_fingerprint=lambda fp: None,
        save_request=saved.append,
        update_request=lambda *a, **k: None,
        new_research_id=lambda: "res_new",
        now=NOW,
    )
    assert res.created is True
    assert len(saved) == 1


def test_enqueue_gate_fails_soft_when_the_ledger_read_throws():
    """An unreadable failure ledger must not block legitimate work."""
    from scripts.lib.hermes_research_queue import enqueue_research_request

    def _boom(plan_id):
        raise OSError("ledger unreadable")

    saved: list[dict] = []
    res = enqueue_research_request(
        dict(REQUEST),
        find_in_flight_by_fingerprint=lambda fp: None,
        save_request=saved.append,
        update_request=lambda *a, **k: None,
        new_research_id=lambda: "res_new",
        list_prior_failures=_boom,
        now=NOW,
    )
    assert res.created is True
    assert len(saved) == 1
