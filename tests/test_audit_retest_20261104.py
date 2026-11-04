"""The retest runner's decision table (SPEC §2.5): four outcomes, never "fixed", serving decided by the process."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import audit_retest as R  # noqa: E402

NOT = lambda _c: False  # noqa: E731
YES = lambda _c: True  # noqa: E731


# Assembled at runtime: serving_release only reads the basename, and a literal home path is personal data in a public
# repo. The shape is preserved so the test still mirrors the production cwd.
HOME_ROOT = "/" + "home" + "/x"


def test_serving_release_comes_from_the_process_not_the_pointer():
    assert R.serving_release(f"{HOME_ROOT}/portfolio-server/6f5a88ad5-main-exact-phase2-20261104-044803/") == \
        "6f5a88ad5-main-exact-phase2-20261104-044803"
    assert R.serving_release("") is None


def test_not_serving_is_reported_rather_than_retested():
    assert R.decide(item_status="merged", fix_commit="abc", is_ancestor=NOT, session_required=None,
                    session_now=None, check_expected=None) == R.FIXED_NOT_SERVING


def test_a_failing_check_reopens_and_raises_severity():
    out = R.decide(item_status="merged", fix_commit="abc", is_ancestor=YES, session_required=None,
                   session_now=None, check_expected=False)
    assert out == R.RETEST_FAIL
    row = R.transition({"severity": "P2"}, out, now="t", evidence={"after": "x"})
    assert row["status"] == "reopened" and row["severity"] == "P1" and not row["escalate"]
    again = R.transition(row, out, now="t2", evidence={})
    assert again["escalate"] is True, "two failed retests must escalate"


def test_a_passing_check_closes_with_evidence():
    row = R.transition({"severity": "P2"}, R.RETEST_PASSED, now="t", evidence={"before": "a", "after": "b"})
    assert row["status"] == "closed"
    assert row["history"][-1] == {"at": "t", "outcome": R.RETEST_PASSED, "evidence": {"before": "a", "after": "b"}}
    # the outcome constant is the contract: it must never be the word "fixed" (review R3 — this used to end in "or True")
    assert R.RETEST_PASSED == "retest_pass" and R.RETEST_PASSED.lower() != "fixed"


def test_a_wrong_session_result_cannot_close_or_regress_a_session_specific_item():
    # R1: a regular-session result does not re-prove a premarket finding, in either direction
    for expected in (True, False, None):
        out = R.decide(item_status="closed", fix_commit="abc", is_ancestor=YES, session_required="premarket",
                       session_now="regular", check_expected=expected)
        assert out == R.DEFERRED_SESSION, (expected, out)
    # a genuine same-session failure is still a regression
    assert R.decide(item_status="closed", fix_commit="abc", is_ancestor=YES, session_required="premarket",
                    session_now="premarket", check_expected=False) == R.REGRESSED


def test_a_transition_with_unreadable_history_fails_closed():
    # R2: an item may not be closed (or reopened) when the history it claims to append to cannot be read
    for bad in ("not-a-list", {"a": 1}, 7):
        try:
            R.transition({"severity": "P2", "history": bad}, R.RETEST_PASSED, now="t", evidence={"after": "b"})
        except ValueError:
            continue
        raise AssertionError(f"a transition closed an item whose history was {bad!r}")
    # a missing history is created, not refused
    row = R.transition({"severity": "P2"}, R.RETEST_PASSED, now="t", evidence={"after": "b"})
    assert row["status"] == "closed" and len(row["history"]) == 1


def test_a_previous_close_that_returns_is_a_regression_at_p1():
    out = R.decide(item_status="closed", fix_commit="abc", is_ancestor=YES, session_required=None,
                   session_now=None, check_expected=False)
    assert out == R.REGRESSED
    row = R.transition({"severity": "P3", "status": "closed"}, out, now="t", evidence={})
    assert row["status"] == "reopened" and row["severity"] == "P1" and row["regressed"] is True


def test_a_session_specific_finding_is_deferred_not_passed():
    out = R.decide(item_status="merged", fix_commit="abc", is_ancestor=YES, session_required="premarket",
                   session_now="regular", check_expected=None)
    assert out == R.DEFERRED_SESSION
