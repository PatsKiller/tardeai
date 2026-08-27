"""Turning outcomes into lessons without manufacturing confidence.

1,617 lessons exist and 1,467 have been applied, and not one references an
outcome — the system has been learning from the advisory knowledge base rather
than from its own recorded results.

The danger in connecting them is not missing a lesson. It is stamping a
confident one on evidence that cannot carry it, because downstream a false
generalisation is indistinguishable from a real one.
"""
from __future__ import annotations

from scripts.lib.cio_institutional_learning import MIN_LESSON_SAMPLES
from scripts.lib.outcome_to_lesson import (
    build_candidates,
    independent_groups,
    observation_key,
)


def _obs(outcome_id, symbol="SCHD", rec="TRIM", date="2026-08-26",
         horizon="1_session", change=0.314):
    return {
        "outcome_id": outcome_id,
        "decision_id": f"dec_{outcome_id}",
        "horizon": horizon,
        "realized_state": {"symbol": symbol, "recommendation": rec,
                           "change_pct": change, "decision_price_date": date},
    }


# ── the trap ───────────────────────────────────────────────────────────────

def test_one_event_observed_five_times_is_one_sample():
    """The exact shape of the first real data.

    Five distinct decision_ids, all SCHD/TRIM/2026-08-26/1_session/+0.314% —
    one event measured five times. Counting them as five hits
    MIN_LESSON_SAMPLES exactly and stamps the lesson SUPPORTED at n=5 when the
    effective n is 1.
    """
    obs = [_obs(f"o{i}") for i in range(5)]
    assert len(obs) == MIN_LESSON_SAMPLES, "the collision is exact, not incidental"

    groups = independent_groups(obs)
    assert len(groups) == 1, "same subject, date and horizon is one observation"

    candidate = build_candidates(obs)[0]
    assert candidate["independent_samples"] == 1
    assert candidate["total_observations"] == 5
    assert candidate["status"] != "SUPPORTED", "n=1 cannot support a lesson"
    assert candidate["status"] == "PROVISIONAL"


def test_the_uncounted_siblings_are_recorded_not_discarded():
    """Dropping them would hide that five records exist behind one sample."""
    candidate = build_candidates([_obs(f"o{i}") for i in range(5)])[0]
    assert len(candidate["correlated_outcome_ids"]) == 4


def test_genuinely_independent_observations_do_count():
    """Different decision dates are different events, and must accumulate."""
    obs = [_obs(f"o{i}", date=f"2026-08-{20+i}", change=-1.0) for i in range(5)]
    groups = independent_groups(obs)
    assert len(groups) == 5

    candidate = build_candidates(obs)[0]
    assert candidate["independent_samples"] == 5
    assert candidate["status"] == "SUPPORTED"


def test_the_same_security_decided_differently_is_two_observations():
    obs = [_obs("a", rec="TRIM"), _obs("b", rec="BUY")]
    assert len(independent_groups(obs)) == 2


# ── reading the move the right way round ───────────────────────────────────

def test_a_trim_followed_by_a_rise_is_a_counterexample_not_support():
    """A TRIM followed by the price going UP is the decision looking wrong.

    Scoring it as support would invert the lesson.
    """
    candidate = build_candidates([_obs("o1", rec="TRIM", change=+2.0)])[0]

    assert candidate["counterexamples"] == ["o1"]
    assert candidate["supporting_outcome_ids"] == []
    assert "did not hold" in candidate["statement"]


def test_a_trim_followed_by_a_fall_is_support():
    candidate = build_candidates([_obs("o1", rec="TRIM", change=-2.0)])[0]
    assert candidate["supporting_outcome_ids"] == ["o1"]
    assert "held" in candidate["statement"]


def test_a_buy_reads_the_opposite_way_from_a_trim():
    up = build_candidates([_obs("o1", rec="BUY", change=+2.0)])[0]
    down = build_candidates([_obs("o2", rec="BUY", change=-2.0)])[0]

    assert up["supporting_outcome_ids"] == ["o1"]
    assert down["counterexamples"] == ["o2"]


def test_a_recommendation_with_no_direction_produces_no_lesson():
    """HOLD and WAIT imply no direction; scoring them would invent a result."""
    assert build_candidates([_obs("o1", rec="HOLD")]) == []
    assert build_candidates([_obs("o2", rec="WAIT")]) == []
    assert build_candidates([_obs("o3", rec="HOLD_CASH")]) == []


def test_a_missing_change_is_not_scored():
    assert build_candidates([_obs("o1", change=None)]) == []


# ── honesty of the record ──────────────────────────────────────────────────

def test_candidates_never_claim_behavioural_influence():
    candidate = build_candidates([_obs("o1", change=-2.0)])[0]
    assert candidate["memory_behavior_influence"] == 0
    assert candidate["observational_only"] is True
    assert candidate["authority"] == "READ_ONLY_ADVISORY"


def test_the_key_is_what_makes_two_outcomes_the_same_event():
    a = observation_key(_obs("a"))
    b = observation_key(_obs("b"))
    assert a == b, "different outcome_ids, same event"
    assert observation_key(_obs("c", date="2026-08-25")) != a
    assert observation_key(_obs("d", horizon="5_sessions")) != a


# ── snapshot corrections found while wiring this lane ──────────────────────

def test_collector_evidence_is_duck_typed_not_isinstance_checked():
    """8 of 18 broker collectors were silently dead.

    `cio_portfolio` imports DomainEvidence as `lib.cio_domain_evidence`; the
    snapshot imports it as `scripts.lib.cio_domain_evidence`. Both succeed and
    they are two distinct class objects, so `isinstance` was False for every
    collector returning one — each reported "Unexpected collector return type:
    DomainEvidence" and died. The fallback then relabelled it "not yet
    collected", hiding the cause completely.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    src = (root / "scripts/lib/cio_financial_snapshot.py").read_text(encoding="utf-8")

    assert 'hasattr(result, "quality_state")' in src, (
        "the check must not depend on class identity across import paths")

    dual_import = (root / "scripts/lib/data_broker/cio_portfolio.py").read_text(encoding="utf-8")
    assert "from lib.cio_domain_evidence import" in dual_import, (
        "the dual-import that causes the clash is still present; if it is ever "
        "removed this guard can go too")


def test_the_fallback_never_overwrites_a_recorded_domain():
    """Checking only `gap_reason` was not enough.

    A collector that ERRORED carries `error_detail`, not `gap_reason`, so it was
    still overwritten and reported as never collected — which is exactly how the
    DomainEvidence clash above stayed invisible.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    src = (root / "scripts/lib/cio_financial_snapshot.py").read_text(encoding="utf-8")
    tail = src.rsplit("known_gaps = CIO_DOMAINS - supported\n", 1)[1][:600]

    assert "if domain in snapshot._domains:" in tail
    assert "continue" in tail
