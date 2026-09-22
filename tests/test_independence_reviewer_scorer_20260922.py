"""reviewer != scorer — from both sides of the contract, and in both insertion orders.

Two independence edges were enforced from the beginning: ``Review.validate`` refuses
producer == reviewer, ``Score.validate`` refuses producer == scorer. The third edge,
reviewer != scorer, was added on 2026-09-16 (``assert_independent_roles``, plus a
durable-row check in ``record_score``) and is pinned by
tests/test_tiered_validation_20260916.py. It closed the case that matters most —
one agent supplying both examinations, so two verdicts from one agent counted as
two independent verdicts.

It closed it from ONE side, and in ONE order. Measured 2026-09-22, before this file:

  * ``Score`` carried an optional ``reviewer_agent_id`` and checked the edge when it
    was supplied. ``Review`` carried no ``scorer_agent_id`` at all, so a Review built
    by an agent that had already scored the artifact validated cleanly. The contract
    gave two different answers to one question depending on which record you built.

  * ``record_score`` asked the durable ``agent_reviews`` rows whether the incoming
    scorer had already reviewed. Nothing asked the durable ``agent_scores`` rows
    whether the incoming reviewer had already scored. So the ORDER of insertion
    decided the verdict: review-then-score was refused, score-then-review was
    accepted — same agent, same artifact, both roles. An independence rule whose
    answer depends on insertion order is not an independence rule; it is a race the
    caller can win by reordering two lines.

Both are closed here. Each test below goes red if its check is deleted, and the
legal-pair tests go red if a check over-fires — a rule that refuses everything is
not evidence of independence either.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.agent_runtime.contracts import (  # noqa: E402
    Artifact,
    BudgetPolicy,
    Environment,
    Review,
    ReviewVerdict,
    RunEnvelope,
    Score,
    canonical_hash,
)
from scripts.agent_runtime.persistence import (  # noqa: E402
    InMemoryPersistence,
    PersistenceError,
    PostgresPersistence,
    derive_id,
)

H = "a" * 64
PAYLOAD = {"finding": "x"}
PRODUCER = "sentinel"


def _clock_factory():
    import itertools

    counter = itertools.count()
    return lambda: f"2026-09-22T00:00:{next(counter):02d}.000000+00:00"


def _seeded_store() -> InMemoryPersistence:
    """A run with one persisted artifact, ready for a review and a score."""
    store = InMemoryPersistence(clock=_clock_factory())
    store.create_run(
        RunEnvelope(
            run_id="run_a",
            agent_id=PRODUCER,
            agent_version="1.0.0",
            job_type="research",
            environment=Environment.LAB,
            objective="assess",
            input_hash=H,
            validation_hash=H,
        ),
        BudgetPolicy(),
    )
    store.record_artifact(
        Artifact(
            artifact_id="art_1",
            run_id="run_a",
            producer_agent_id=PRODUCER,
            artifact_type="analysis",
            payload=PAYLOAD,
            input_hash=H,
            validation_hash=H,
            retrieval_refs=("kb:1",),
            prompt_version="p1",
            provider_family="local",
            model="m1",
        )
    )
    return store


def _review(reviewer: str, rid: str = "rev_1", **kw) -> Review:
    return Review(
        review_id=derive_id(rid),
        artifact_id="art_1",
        producer_agent_id=PRODUCER,
        reviewer_agent_id=reviewer,
        verdict=ReviewVerdict.PASS,
        findings=(),
        artifact_hash=canonical_hash(PAYLOAD),
        **kw,
    )


def _score(scorer: str, sid: str = "score_1", **kw) -> Score:
    return Score(
        score_id=derive_id(sid),
        artifact_id="art_1",
        producer_agent_id=PRODUCER,
        scorer_agent_id=scorer,
        dimensions={"grounding": 0.5},
        **kw,
    )


# ----------------------------------------------------- the contract, both sides


def test_a_review_by_the_agent_that_scored_it_is_refused():
    """The edge the contract could not see from the reviewing side.

    Delete the ``scorer_agent_id`` branch in ``Review.validate`` and this fails.
    """
    with pytest.raises(ValueError, match="reviewer and scorer must be different"):
        _review("iris", scorer_agent_id="iris").validate()


def test_the_contract_gives_the_same_answer_from_either_side():
    """Same agent, same artifact, both roles — refused whichever record is built.

    Before this, the Score side raised and the Review side returned cleanly, so
    which of two equivalent call sites you happened to write decided whether the
    collision was caught.
    """
    with pytest.raises(ValueError, match="reviewer and scorer must be different"):
        _score("iris", reviewer_agent_id="iris").validate()
    with pytest.raises(ValueError, match="reviewer and scorer must be different"):
        _review("iris", scorer_agent_id="iris").validate()


def test_an_independent_trio_still_validates_from_either_side():
    """Control: a rule that refuses every pair proves nothing about independence.

    If either check over-fires, this goes red — which is what makes the two tests
    above evidence rather than a guarantee that the constructor raises.
    """
    _review("iris", scorer_agent_id="darwin").validate()
    _score("darwin", reviewer_agent_id="iris").validate()


def test_the_two_original_edges_are_not_traded_away():
    """The third edge must be added to the first two, not substituted for them."""
    with pytest.raises(ValueError, match="may not review its own"):
        _review(PRODUCER).validate()
    with pytest.raises(ValueError, match="may not score its own"):
        _score(PRODUCER).validate()


def test_the_new_field_is_optional_so_existing_callers_are_unaffected():
    """A required field would have made every current Review construction a TypeError.

    ``runtime.record_review`` and ``packet_d_shadow_acceptance`` both build Reviews
    without a scorer, because at review time no score exists yet. The durable check
    below is what covers them; the contract field is for callers that know both.
    """
    _review("iris").validate()  # no scorer_agent_id supplied
    assert Review.__dataclass_fields__["scorer_agent_id"].default is None


# ------------------------------------------------- the durable rows, both orders


def test_scoring_then_reviewing_with_one_agent_is_refused():
    """The order that used to be accepted.

    Delete the ``agent_scores`` lookup in ``record_review`` and this fails — the
    store accepts darwin as reviewer of an artifact darwin already scored.
    """
    store = _seeded_store()
    store.record_score(_score("darwin"))
    with pytest.raises(PersistenceError, match="reviewer and scorer must be different"):
        store.record_review(_review("darwin"))


def test_reviewing_then_scoring_with_one_agent_is_still_refused():
    """The order that was already covered, kept under test so it cannot regress."""
    store = _seeded_store()
    store.record_review(_review("darwin"))
    with pytest.raises(PersistenceError, match="reviewer and scorer must be different"):
        store.record_score(_score("darwin"))


def test_the_verdict_no_longer_depends_on_the_order():
    """The actual defect, stated as one property.

    Two stores, same three agents, opposite insertion orders, one outcome. This is
    the test that would have been red on 2026-09-21 and is the reason the other two
    exist as separate cases.
    """
    outcomes = []
    for first in ("score", "review"):
        store = _seeded_store()
        try:
            if first == "score":
                store.record_score(_score("darwin"))
                store.record_review(_review("darwin"))
            else:
                store.record_review(_review("darwin"))
                store.record_score(_score("darwin"))
            outcomes.append("ACCEPTED")
        except PersistenceError:
            outcomes.append("REFUSED")
    assert outcomes == ["REFUSED", "REFUSED"], (
        f"insertion order changed the independence verdict: {outcomes}"
    )


def test_an_independent_pair_is_accepted_in_either_order():
    """Control: the store must still record real independent examinations.

    Without this, both refusals above would also be satisfied by a store that
    rejected every review-and-score pair, which would break the runtime rather
    than govern it.
    """
    store = _seeded_store()
    store.record_score(_score("darwin"))
    store.record_review(_review("iris"))
    reconstructed = store.reconstruct("run_a")
    assert len(reconstructed.scores) == 1
    assert len(reconstructed.reviews) == 1

    other = _seeded_store()
    other.record_review(_review("iris"))
    other.record_score(_score("darwin"))
    assert len(other.reconstruct("run_a").scores) == 1


def test_the_rule_is_not_backend_specific():
    """Both backends must answer identically, so the rule lives on the shared base.

    A check implemented on InMemoryPersistence alone would hold every test in this
    file green while production — which runs Postgres — kept the hole.
    """
    assert PostgresPersistence.record_review is InMemoryPersistence.record_review
    assert PostgresPersistence.record_score is InMemoryPersistence.record_score
