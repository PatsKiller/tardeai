"""Remediation verdicts decided by re-checking, not by exit code.

The durable record on 2026-08-27 held 3,669 `ok: true` rows, every one of them a
statement about `proc.returncode == 0`. These tests are written at the behaviour
level — they exercise the classifier on real finding shapes and assert on the
verdict it returns. A test that only greps source text is how PR #543 shipped
broken; asserting `"returncode" not in src` would pass against code that still
lies, so none of that is done here.
"""
from __future__ import annotations

from scripts.lib.health_remediation_outcome import (
    CAUSE_EFFECT_NOT_OBSERVED,
    CAUSE_UNDIAGNOSED,
    CAUSE_UPSTREAM_UNAVAILABLE,
    CAUSE_WROTE_UNREAD_COPY,
    CLEARED,
    FAILED,
    INEFFECTIVE,
    WORSENED,
    classify,
    diagnose,
    escalation_payload,
    should_stop_retrying,
)

# The 2026-08-26 repricer incident, as the health agent saw it: a stale-output
# finding, a fix that exits 0, and a condition that does not move because the
# fix wrote a copy the reader never reads.
RT = "portfolio_repricer_stale"

REPRICER_BEFORE = {
    "category": "data_freshness",
    "type": "portfolio_repricer_stale",
    "severity": "critical",
    "message": "portfolio repricer output stale",
    "age_hours": 24.0,
}


def _still(**over):
    f = dict(REPRICER_BEFORE)
    f.update(over)
    return f


# ── the incident this exists to catch ──────────────────────────────────────

def test_the_repricer_incident_is_ineffective_not_success():
    """Exit 0, condition unchanged. The old code logged ok: True here."""
    v = classify(finding_type="portfolio_repricer_stale", before=REPRICER_BEFORE,
                 after_findings=[_still()], exit_code=0)

    assert v["outcome"] == INEFFECTIVE
    assert v["ok"] is False, "exit 0 must never by itself mean the condition cleared"
    assert v["verified_by_recheck"] is True


def test_the_repricer_incident_escalates_within_two_attempts():
    """The acceptance criterion: <=2 attempts, with WROTE_UNREAD_COPY."""
    v = classify(finding_type="portfolio_repricer_stale", before=REPRICER_BEFORE,
                 after_findings=[_still()], exit_code=0)

    # attempt 1 — record, do not yet stop
    stop, _ = should_stop_retrying(v, ineffective_streak=1, breaker=2)
    assert stop is False

    # attempt 2 — breaker trips
    stop, reason = should_stop_retrying(v, ineffective_streak=2, breaker=2)
    assert stop is True
    assert "breaker_2" in reason

    cause = diagnose(v, evidence={
        "wrote_path": "/home/johnclaw/trade-ai-v12-rebuild/.../holdings.json",
        "read_path": "/home/johnclaw/trade-ai-releases/persistent-state/.../holdings.json",
    })
    assert cause == CAUSE_WROTE_UNREAD_COPY


def test_ok_true_is_never_logged_for_a_condition_that_still_fires():
    """Across every non-CLEARED verdict, `ok` must be False."""
    cases = [
        classify(finding_type=RT, before=REPRICER_BEFORE, after_findings=[_still()], exit_code=0),
        classify(finding_type=RT, before=REPRICER_BEFORE, after_findings=[_still(age_hours=48.0)], exit_code=0),
        classify(finding_type=RT, before=REPRICER_BEFORE, after_findings=[], exit_code=1),
        classify(finding_type=RT, before=REPRICER_BEFORE, after_findings=[], exit_code=None, timed_out=True),
        classify(finding_type=RT, before=REPRICER_BEFORE, after_findings=[], exit_code=69),
    ]
    assert all(c["ok"] is False for c in cases)
    assert [c["outcome"] for c in cases] == [INEFFECTIVE, WORSENED, FAILED, FAILED, FAILED]


# ── the four outcomes ──────────────────────────────────────────────────────

def test_cleared_requires_the_finding_to_be_gone():
    v = classify(finding_type="portfolio_repricer_stale", before=REPRICER_BEFORE,
                 after_findings=[], exit_code=0)
    assert v["outcome"] == CLEARED
    assert v["ok"] is True
    assert v["still_firing"] is False


def test_a_different_finding_still_firing_does_not_block_cleared():
    """Only the originating finding decides. An unrelated one is not evidence."""
    v = classify(finding_type="portfolio_repricer_stale", before=REPRICER_BEFORE,
                 after_findings=[{"type": "something_else", "severity": "critical"}],
                 exit_code=0)
    assert v["outcome"] == CLEARED


def test_worsened_on_rising_severity():
    before = dict(REPRICER_BEFORE, severity="warning")
    v = classify(finding_type="portfolio_repricer_stale", before=before,
                 after_findings=[_still(severity="critical")], exit_code=0)
    assert v["outcome"] == WORSENED


def test_worsened_on_rising_metric_at_equal_severity():
    v = classify(finding_type="portfolio_repricer_stale", before=REPRICER_BEFORE,
                 after_findings=[_still(age_hours=36.0)], exit_code=0)
    assert v["outcome"] == WORSENED
    assert v["metric_before"] == 24.0 and v["metric_after"] == 36.0


def test_an_improving_metric_that_has_not_cleared_is_ineffective_not_worsened():
    v = classify(finding_type="portfolio_repricer_stale", before=REPRICER_BEFORE,
                 after_findings=[_still(age_hours=2.0)], exit_code=0)
    assert v["outcome"] == INEFFECTIVE


def test_failed_when_the_command_did_not_run():
    for kw in ({"exit_code": 1}, {"exit_code": None, "timed_out": True},
               {"exit_code": None, "raised": True}):
        v = classify(finding_type=RT, before=REPRICER_BEFORE, after_findings=[], **kw)
        assert v["outcome"] == FAILED, kw


def test_a_failed_command_is_not_credited_even_if_the_condition_cleared():
    """Something else may have fixed it. Crediting the fix teaches a false lesson."""
    v = classify(finding_type=RT, before=REPRICER_BEFORE, after_findings=[], exit_code=1)
    assert v["outcome"] == FAILED
    assert v["ok"] is False


def test_flock_contention_is_failed_not_success():
    """Nothing was attempted; that is not a fix."""
    for code in (69, 99):
        v = classify(finding_type=RT, before=REPRICER_BEFORE, after_findings=[_still()],
                     exit_code=code)
        assert v["outcome"] == FAILED and v["ok"] is False


# ── stopping ───────────────────────────────────────────────────────────────

def test_worsened_stops_immediately_regardless_of_streak():
    """Retrying a fix that is making it worse compounds the damage."""
    v = classify(finding_type=RT, before=dict(REPRICER_BEFORE, severity="warning"),
                 after_findings=[_still(severity="critical")], exit_code=0)
    stop, reason = should_stop_retrying(v, ineffective_streak=0, breaker=2)
    assert stop is True
    assert reason == "worsened_on_first_observation"


def test_cleared_never_stops_retrying():
    v = classify(finding_type=RT, before=REPRICER_BEFORE, after_findings=[], exit_code=0)
    assert should_stop_retrying(v, ineffective_streak=99, breaker=2)[0] is False


# ── typed root causes ──────────────────────────────────────────────────────

def test_root_cause_is_typed_and_never_guessed():
    v = classify(finding_type=RT, before=REPRICER_BEFORE, after_findings=[_still()], exit_code=0)

    assert diagnose(v, evidence={"upstream_unavailable": True}) == CAUSE_UPSTREAM_UNAVAILABLE
    assert diagnose(v, evidence={}) == CAUSE_EFFECT_NOT_OBSERVED
    # A cleared verdict has no root cause to report.
    cleared = classify(finding_type=RT, before=REPRICER_BEFORE, after_findings=[], exit_code=0)
    assert diagnose(cleared) == ""


def test_an_undiagnosable_failure_says_undiagnosed_not_unknown():
    """`unknown` was 10% of the live diagnosis vocabulary and reads like a finding."""
    v = classify(finding_type=RT, before=REPRICER_BEFORE, after_findings=[_still()], exit_code=None)
    v["exit_code"] = None
    assert diagnose(v, evidence={}) == CAUSE_UNDIAGNOSED


# ── the escalation an operator can act on ───────────────────────────────────

def test_escalation_carries_diagnosis_trend_and_the_failing_command():
    v = classify(finding_type="portfolio_repricer_stale", before=REPRICER_BEFORE,
                 after_findings=[_still(age_hours=36.0)], exit_code=0)
    stop, reason = should_stop_retrying(v, ineffective_streak=0, breaker=2)
    payload = escalation_payload(
        v, root_cause=CAUSE_WROTE_UNREAD_COPY,
        command="python3 scripts/portfolio_repricer.py", reason=reason)

    assert payload["root_cause"] == CAUSE_WROTE_UNREAD_COPY
    assert payload["command_that_did_not_help"] == "python3 scripts/portfolio_repricer.py"
    assert "24.0 -> 36.0" in payload["metric_trend"] and "worse" in payload["metric_trend"]
    assert payload["needs_operator"] is True
    assert payload["outcome"] == WORSENED


def test_escalation_is_honest_when_no_metric_exists_to_trend():
    before = {"type": "t", "severity": "warning", "message": "no numeric metric"}
    v = classify(finding_type="t", before=before,
                 after_findings=[dict(before)], exit_code=0)
    payload = escalation_payload(v, root_cause=CAUSE_EFFECT_NOT_OBSERVED,
                                 command="cmd", reason="r")
    assert payload["metric_trend"] == "no comparable metric on this finding"


def test_the_verdict_never_claims_authority():
    v = classify(finding_type=RT, before=REPRICER_BEFORE, after_findings=[], exit_code=0)
    assert v["authority"] == "READ_ONLY_ADVISORY"
