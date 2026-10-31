"""A rejected source fact is a recorded gap, not a failed check (Ask-the-CIO breakers, 2026-10-30).

On 10-30 internal.thesis returned ``status: rejected`` for every tracked subject. The hourly check raised
SOURCE_CHECK_INCOMPLETE each time, three in a row opened the n8n breakers for cio-ask-lifecycle and
cio-ask-material-events, and the event ledger said only ``CHECK_FAILED:ValueError``. Synthetic fixtures only.
"""

from scripts.lib import cio_ask_lifecycle as life
from tests.test_cio_ask_hourly_20261026 import NOW, fixture, run


def _rows(*statuses):
    return [
        {"source": f"fixture.{i}", "subject": "Example Robotics", "status": s, "observed_at": life.stamp(NOW)}
        for i, s in enumerate(statuses)
    ]


def test_rejected_source_fact_does_not_fail_the_check(tmp_path):
    d = fixture(tmp_path)
    result = run(d, collect=lambda _: {"fingerprint": "same", "facts": [], "source_runs": _rows("ok", "rejected")})
    assert result["ok"], result["source_errors"]
    assert result["failed_count"] == 0 and result["checked_count"] == 1


def test_errored_source_still_fails_and_names_the_reason(tmp_path):
    d = fixture(tmp_path)
    result = run(d, collect=lambda _: {"fingerprint": "same", "facts": [], "source_runs": _rows("ok", "error")})
    assert not result["ok"] and result["failed_count"] == 1
    assert result["source_errors"] == ["thr_fixture:ValueError:SOURCE_CHECK_INCOMPLETE"]
    ended = [e for e in d.store.events() if e.get("kind") == "ask.check_finished"]
    assert ended[-1]["reason"] == "CHECK_FAILED:ValueError:SOURCE_CHECK_INCOMPLETE"


def test_free_text_exception_messages_never_reach_the_reason():
    assert life._check_failed_reason(ValueError("token abc123 for user@example")) == "CHECK_FAILED:ValueError"
    assert life._check_failed_reason(KeyError("x")) == "CHECK_FAILED:KeyError"
    assert life._check_failed_reason(ValueError("SOURCE_CHECK_INCOMPLETE")).endswith(":SOURCE_CHECK_INCOMPLETE")
