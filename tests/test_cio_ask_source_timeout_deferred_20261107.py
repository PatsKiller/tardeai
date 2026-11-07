"""A timed-out source defers the check; it does not fail the lane (2026-11-02 → 2026-11-07).

Live finding 2026-11-07: ``cio-ask-lifecycle`` last ran 2026-11-02T18:00Z and was never requested again. Its
receipt says ``consecutive_failures: 3`` and

    CHECK_FAILED:ValueError:SOURCE_CHECK_INCOMPLETE:internal.cio_record_research:timeout,news.articles:timeout

Two sources ran out of time, each hourly check raised SOURCE_CHECK_INCOMPLETE, three in a row opened the n8n
breaker for the lane, and Ask-the-CIO stopped tracking anything — the same shape as the 2026-10-30 ``rejected``
incident, which was fixed by widening the answered statuses. This one is a *transient* status, so the answer is
not to call it an answer (nothing is recorded as no_change) but to defer the check to the next slot without
charging the lane a failure. Synthetic fixtures only.
"""

from datetime import timedelta

from scripts.lib import cio_ask_lifecycle as life
from tests.test_cio_ask_hourly_20261026 import NOW, TID, fixture, run


def _rows(*statuses):
    return [
        {"source": f"fixture.{i}", "subject": "Example Robotics", "status": s, "observed_at": life.stamp(NOW)}
        for i, s in enumerate(statuses)
    ]


def _finished(d):
    return [e for e in d.store.events() if e.get("kind") == "ask.check_finished"]


def test_a_timeout_defers_the_check_instead_of_failing_the_lane(tmp_path):
    d = fixture(tmp_path)
    result = run(
        d,
        collect=lambda _: {
            "fingerprint": "same",
            "facts": [],
            "source_runs": _rows("ok", "ok", "timeout"),
        },
    )
    assert result["ok"], result["source_errors"]
    assert result["failed_count"] == 0
    assert result["deferred_count"] == 1
    assert result["checked_count"] == 0, "a check that concluded nothing is not a check"
    assert result["source_errors"] == []


def test_the_deferral_names_the_timed_out_source_and_retries_next_slot(tmp_path):
    d = fixture(tmp_path)
    run(d, collect=lambda _: {"fingerprint": "same", "facts": [], "source_runs": _rows("ok", "timeout")})
    end = _finished(d)[-1]
    assert end["outcome"] == "deferred" and end["state"] == "deferred"
    assert end["reason"] == "CHECK_DEFERRED:ValueError:SOURCE_CHECK_INCOMPLETE:fixture.1:timeout"
    assert end["next_eligible_at"] == life.stamp(NOW + timedelta(hours=1))
    assert end["checked_at"] is None, "a deferred check must not stamp itself as having checked"


def test_the_thread_stays_trackable_after_a_deferral(tmp_path):
    """It must not read as failed (which both quarantines the thread and opens the lane's breaker)."""
    d = fixture(tmp_path)
    run(d, collect=lambda _: {"fingerprint": "same", "facts": [], "source_runs": _rows("timeout")})
    projected = life.project_lifecycle(d.store.thread(TID), d.store.events(thread_id=TID), now=NOW)
    assert projected["state"] != "failed"
    assert projected["last_check_outcome"] in ("deferred", None)


def test_a_mixed_timeout_and_error_still_fails(tmp_path):
    """Only timeouts are transient: a source that is genuinely broken is never deferred away."""
    d = fixture(tmp_path)
    result = run(
        d,
        collect=lambda _: {
            "fingerprint": "same",
            "facts": [],
            "source_runs": _rows("ok", "timeout", "error"),
        },
    )
    assert not result["ok"]
    assert result["failed_count"] == 1 and result["deferred_count"] == 0
    assert result["source_errors"] == [
        "thr_fixture:ValueError:SOURCE_CHECK_INCOMPLETE:fixture.1:timeout,fixture.2:error"
    ]


def test_a_source_that_never_stops_timing_out_is_reported_after_the_budget(tmp_path):
    """Deferral is bounded: a provider that times out every hour is an outage, not latency.

    The lane must stop being green about it — but it fails once per budget, not every hour, so three
    consecutive failures (the n8n breaker) cannot be reached by one slow provider.
    """
    d = fixture(tmp_path)
    d.config["lifecycle"]["max_consecutive_source_deferrals"] = 2
    timed_out = lambda _: {"fingerprint": "same", "facts": [], "source_runs": _rows("timeout")}

    assert run(d, now=NOW, collect=timed_out)["deferred_count"] == 1
    assert run(d, now=NOW + timedelta(hours=1), collect=timed_out)["deferred_count"] == 1
    third = run(d, now=NOW + timedelta(hours=2), collect=timed_out)
    assert not third["ok"]
    assert third["failed_count"] == 1 and third["deferred_count"] == 0
    assert third["source_errors"] == ["thr_fixture:ValueError:SOURCE_TIMEOUT_LIMIT:fixture.0:timeout"]
    assert _finished(d)[-1]["outcome"] == "failed"
    assert _finished(d)[-1]["reason"].startswith("CHECK_FAILED:ValueError:SOURCE_TIMEOUT_LIMIT")


def test_a_healthy_check_resets_the_deferral_budget(tmp_path):
    """One concluded check means the source is answering again; the next timeout starts a fresh budget."""
    d = fixture(tmp_path)
    d.config["lifecycle"]["max_consecutive_source_deferrals"] = 1
    timed_out = lambda _: {"fingerprint": "same", "facts": [], "source_runs": _rows("timeout")}

    assert run(d, now=NOW, collect=timed_out)["deferred_count"] == 1
    healthy = run(d, now=NOW + timedelta(hours=1))
    assert healthy["ok"] and healthy["no_change_count"] == 1
    again = run(d, now=NOW + timedelta(hours=2), collect=timed_out)
    assert again["ok"] and again["deferred_count"] == 1, "the budget must not carry over a concluded check"
