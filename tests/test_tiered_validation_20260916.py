"""Tiered validation: deterministic → free critic → operator-gated paid judge.

``CriticPanel`` shipped correct and had zero callers outside tests. These pin the
properties of its first production caller, and the third independence edge nothing had
ever enforced.

The guarantees, one test each:
  * tier 0 blocks BEFORE any critic is constructed — a deterministic failure costs nothing;
  * tier 1 lanes are free and independent, checked before a byte is sent;
  * PASS and REJECT across two lanes survive as a DISAGREEMENT and are never voted away;
  * tier 2 spends nothing unless the operator funds it (AGENTS.md §17);
  * a BLIND or uncalibrated lane cannot certify anything;
  * producer != reviewer != scorer — all three edges, in the contract AND in the runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.agent_runtime.contracts import (  # noqa: E402
    AgentDefinition,
    BudgetPolicy,
    DeploymentState,
    Environment,
    Review,
    ReviewVerdict,
    Score,
    assert_independent_roles,
    canonical_hash,
)
from scripts.agent_runtime.critics import CriticLane  # noqa: E402
from scripts.agent_runtime.journal import ShadowRunJournal  # noqa: E402
from scripts.agent_runtime.runtime import MvlRuntime  # noqa: E402
from scripts.agent_runtime.sentinel import inspect_ticket  # noqa: E402
from scripts.lib.tiered_validation import (  # noqa: E402
    FREE_TIER1_LANES,
    TIER2_FLAG,
    ProviderSeparationError,
    TierPolicy,
    run_known_bad_probe,
    validate,
)
from scripts.lib.validator_calibration import (  # noqa: E402
    SeededKnownBad,
    observations_from_counts,
    observe_known_bad,
)

# No COVERS: nothing in this path sends an operator alert.
COVERS = []

GROK = CriticLane("grok_free", "grok-oauth", "grok-3-mini", max_cost_usd=0.0)
CHATGPT = CriticLane("chatgpt_free", "chatgpt-oauth", "gpt-4o-mini", max_cost_usd=0.0)
TWO_FREE_LANES = (GROK, CHATGPT)
PRODUCER = "deepseek"


def deterministic(passing: bool = True):
    ticket = {
        "symbol": "SCHG",
        "state": "READY",
        "direction": "LONG",
        "input_hash": "b" * 64,
        "validation_hash": "a" * 64,
        "as_of": "2026-09-16T13:30:00+00:00",
        "mechanics": {"entry": 34.1, "stop": 33.6, "target": 35.5},
    }
    validation = {
        "state": "PASS" if passing else "FAIL",
        "proposal_allowed": passing,
        "hard_failures": [] if passing else ["fixture"],
    }
    from datetime import datetime, timezone

    return inspect_ticket(ticket, validation, now=datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc))


def reply(lane: CriticLane, verdict: str, refs=("lesson:integrity:v1",)):
    def provider(_request):
        return {
            "provider_family": lane.provider_family,
            "model": lane.model,
            "verdict": verdict,
            "findings": [f"{verdict} fixture"],
            "evidence_refs": list(refs),
            "cost_usd": 0.0,
        }

    return provider


def calibrated_ledger(*lane_ids: str):
    """Windows that pass the calibration floor, so a test can isolate one variable."""
    return {lane_id: list(observations_from_counts(lane_id, total=40, disagreements=9)) for lane_id in lane_ids}


# ------------------------------------------------------------------- tier 0


def test_a_deterministic_block_short_circuits_before_any_critic_is_called():
    calls: list[str] = []

    def spy(_request):
        calls.append("called")
        return {
            "provider_family": "grok-oauth",
            "model": "grok-3-mini",
            "verdict": "PASS",
            "evidence_refs": ["x"],
            "cost_usd": 0.0,
        }

    result = validate(
        {"task": "should never be sent"},
        deterministic(passing=False),
        providers={"grok_free": spy},
        producer_family=PRODUCER,
        policy=TierPolicy(tier1_lanes=(GROK,)),
    )

    assert calls == [], "a deterministic failure must not reach a reflective lane"
    assert result.state == "BLOCK_DETERMINISTIC"
    assert result.tier_reached == 0
    assert result.critic_calls == 0
    assert result.paid_calls == 0
    assert result.cost_usd == 0.0
    assert result.release_allowed is False


# ------------------------------------------------------------------- tier 1


def test_tier1_independence_is_checked_before_a_byte_is_sent():
    # A critic on the author's own provider is the author.
    with pytest.raises(ProviderSeparationError, match="producer's provider family"):
        validate(
            {"t": 1},
            deterministic(),
            providers={},
            producer_family="grok-oauth",
            policy=TierPolicy(tier1_lanes=(GROK,)),
        )

    # Two lanes on one provider are one opinion wearing two badges.
    twin = CriticLane("grok_twin", "grok-oauth", "grok-3-mini-2", max_cost_usd=0.0)
    with pytest.raises(ProviderSeparationError, match="duplicates provider family"):
        validate(
            {"t": 1},
            deterministic(),
            providers={},
            producer_family=PRODUCER,
            policy=TierPolicy(tier1_lanes=(GROK, twin)),
        )

    # Tier 1 is free by construction, not by intention.
    paid = CriticLane("paid_lane", "openai", "o3", max_cost_usd=0.02)
    with pytest.raises(ProviderSeparationError, match="non-zero budget"):
        validate(
            {"t": 1}, deterministic(), providers={}, producer_family=PRODUCER, policy=TierPolicy(tier1_lanes=(paid,))
        )


def test_the_shipped_default_lanes_are_free_and_separated_from_the_author():
    assert all(lane.max_cost_usd == 0.0 for lane in FREE_TIER1_LANES)
    result = validate(
        {"task": "critique"},
        deterministic(),
        providers={"grok_free": reply(GROK, "PASS")},
        producer_family=PRODUCER,
        calibration_ledger=calibrated_ledger("grok_free"),
    )
    assert result.cost_usd == 0.0
    assert result.paid_calls == 0
    assert result.state == "REFLECTIVE_PASS"


def test_a_forced_pass_and_reject_across_two_lanes_is_preserved_as_a_disagreement():
    result = validate(
        {"task": "critique"},
        deterministic(),
        providers={
            "grok_free": reply(GROK, "PASS"),
            "chatgpt_free": reply(CHATGPT, "REJECT"),
        },
        producer_family=PRODUCER,
        policy=TierPolicy(tier1_lanes=TWO_FREE_LANES),
        calibration_ledger=calibrated_ledger("grok_free", "chatgpt_free"),
    )

    assert result.state == "DISAGREEMENT"
    assert result.disagreements, "the disagreement tuple must be populated, not merely implied"
    assert "majority voting is prohibited" in result.disagreements[0]
    assert "operator" in result.operator_action.lower()
    assert result.critic_calls == 2
    assert result.cost_usd == 0.0


def test_a_disagreement_survives_even_when_the_lanes_are_not_yet_calibrated():
    """An argument between lanes is evidence they are alive; it must reach the operator."""
    result = validate(
        {"task": "critique"},
        deterministic(),
        providers={
            "grok_free": reply(GROK, "PASS"),
            "chatgpt_free": reply(CHATGPT, "REJECT"),
        },
        producer_family=PRODUCER,
        policy=TierPolicy(tier1_lanes=TWO_FREE_LANES),
        calibration_ledger={},  # nothing measured yet
    )
    assert result.state == "DISAGREEMENT"
    assert result.downgrade_reasons, "the uncalibrated lanes must still be named"


# ------------------------------------------------- calibration applied to the panel


def test_a_lane_that_passed_a_seeded_known_bad_cannot_certify_a_pass():
    probe = SeededKnownBad(probe_id="shadow-bad-003", payload={"defect": "quarantine_case"})
    blind_window = list(observations_from_counts("grok_free", total=40, disagreements=9))
    blind_window.append(observe_known_bad("grok_free", probe, "PASS"))

    result = validate(
        {"task": "critique"},
        deterministic(),
        providers={"grok_free": reply(GROK, "PASS")},
        producer_family=PRODUCER,
        policy=TierPolicy(tier1_lanes=(GROK,)),
        calibration_ledger={"grok_free": blind_window},
    )

    assert result.blind_lanes == ("grok_free",)
    assert result.state == "INSUFFICIENT_EVIDENCE"  # the PASS does not stand
    assert result.release_allowed is False
    assert result.calibration["grok_free"].window_voided is True
    assert any("BLIND" in reason for reason in result.downgrade_reasons)


def test_a_lane_that_has_never_disagreed_cannot_certify_a_pass():
    never_argues = list(observations_from_counts("grok_free", total=40, disagreements=0))
    result = validate(
        {"task": "critique"},
        deterministic(),
        providers={"grok_free": reply(GROK, "PASS")},
        producer_family=PRODUCER,
        policy=TierPolicy(tier1_lanes=(GROK,)),
        calibration_ledger={"grok_free": never_argues},
    )
    assert result.state == "INSUFFICIENT_EVIDENCE"
    assert result.blind_lanes == ()
    assert any("UNCALIBRATED" in reason for reason in result.downgrade_reasons)


def test_a_known_bad_probe_runs_through_the_same_panel_the_real_work_uses():
    probe = SeededKnownBad(probe_id="shadow-bad-004", payload={"defect": "quarantine_case"})

    blind = run_known_bad_probe(probe, (GROK,), {"grok_free": reply(GROK, "PASS")}, deterministic())
    assert blind[0].known_bad_passed is True
    assert blind[0].seeded_known_bad is True

    caught = run_known_bad_probe(probe, (GROK,), {"grok_free": reply(GROK, "REJECT")}, deterministic())
    assert caught[0].known_bad_passed is False
    assert caught[0].disagreed is True


# ------------------------------------------------------------------- tier 2


def test_tier2_is_disabled_by_default_and_spends_nothing():
    result = validate(
        {"task": "critique"},
        deterministic(),
        providers={"grok_free": reply(GROK, "ABSTAIN")},
        producer_family=PRODUCER,
        policy=TierPolicy(tier1_lanes=(GROK,)),
        calibration_ledger=calibrated_ledger("grok_free"),
    )
    assert result.state == "INSUFFICIENT_EVIDENCE"  # a tier-2 trigger state
    assert result.tier_reached == 1
    assert result.paid_calls == 0
    assert result.cost_usd == 0.0
    assert result.tier2_state.startswith("WITHHELD_OPERATOR_GATED")
    assert "§17" in result.tier2_state


def test_tier2_is_not_reached_at_all_when_the_free_tier_answered_cleanly():
    result = validate(
        {"task": "critique"},
        deterministic(),
        providers={"grok_free": reply(GROK, "PASS")},
        producer_family=PRODUCER,
        policy=TierPolicy(tier1_lanes=(GROK,)),
        calibration_ledger=calibrated_ledger("grok_free"),
    )
    assert result.state == "REFLECTIVE_PASS"
    assert result.tier2_state == "NOT_TRIGGERED"


def test_the_flag_alone_does_not_buy_a_paid_judge_and_a_misconfiguration_denies():
    enabled = TierPolicy.from_env({TIER2_FLAG: "1"}, tier1_lanes=(GROK,))
    assert enabled.tier2_enabled is True

    result = validate(
        {"task": "critique"},
        deterministic(),
        providers={"grok_free": reply(GROK, "ABSTAIN")},
        producer_family=PRODUCER,
        policy=enabled,
        calibration_ledger=calibrated_ledger("grok_free"),
        paid_judge=None,
    )
    assert result.tier2_state == "DENIED_NO_PAID_JUDGE_CONFIGURED"
    assert result.paid_calls == 0
    assert result.cost_usd == 0.0


def test_an_operator_funded_judge_is_consulted_only_on_a_trigger_state():
    calls: list[str] = []

    def judge(_request):
        calls.append("paid")
        return {"verdict": "CAUTION", "cost_usd": 0.0025}

    enabled = TierPolicy.from_env({TIER2_FLAG: "1"}, tier1_lanes=(GROK,))

    clean = validate(
        {"task": "critique"},
        deterministic(),
        providers={"grok_free": reply(GROK, "PASS")},
        producer_family=PRODUCER,
        policy=enabled,
        calibration_ledger=calibrated_ledger("grok_free"),
        paid_judge=judge,
    )
    assert calls == [], "a clean free-tier answer must not be re-bought"
    assert clean.paid_calls == 0

    triggered = validate(
        {"task": "critique"},
        deterministic(),
        providers={"grok_free": reply(GROK, "ABSTAIN")},
        producer_family=PRODUCER,
        policy=enabled,
        calibration_ledger=calibrated_ledger("grok_free"),
        paid_judge=judge,
    )
    assert calls == ["paid"]
    assert triggered.tier_reached == 2
    assert triggered.paid_calls == 1
    assert triggered.tier2_state == "ESCALATED:CAUTION"


def test_the_environment_default_is_off():
    assert TierPolicy.from_env({}).tier2_enabled is False
    assert TierPolicy.from_env({TIER2_FLAG: "0"}).tier2_enabled is False


# ------------------------------------- producer != reviewer != scorer, all three


def test_all_three_independence_edges_are_enforced():
    assert_independent_roles("producer", "reviewer", "scorer")  # the legal case

    with pytest.raises(ValueError, match="may not review its own"):
        assert_independent_roles("agent_a", "agent_a", "scorer")
    with pytest.raises(ValueError, match="may not score its own"):
        assert_independent_roles("agent_a", "reviewer", "agent_a")
    # The edge nothing enforced before 2026-09-16.
    with pytest.raises(ValueError, match="reviewer and scorer must be different"):
        assert_independent_roles("producer", "agent_b", "agent_b")


def test_a_score_whose_scorer_already_reviewed_the_artifact_is_refused():
    both = Score(
        score_id="score_1",
        artifact_id="art_1",
        producer_agent_id="sentinel",
        scorer_agent_id="iris",
        dimensions={"grounding": 1.0},
        reviewer_agent_id="iris",
    )
    with pytest.raises(ValueError, match="reviewer and scorer must be different"):
        both.validate()

    independent = Score(
        score_id="score_2",
        artifact_id="art_1",
        producer_agent_id="sentinel",
        scorer_agent_id="darwin",
        dimensions={"grounding": 1.0},
        reviewer_agent_id="iris",
    )
    independent.validate()  # producer != reviewer != scorer

    # The two older edges still hold.
    with pytest.raises(ValueError, match="may not score its own"):
        Score(
            score_id="s3",
            artifact_id="art_1",
            producer_agent_id="sentinel",
            scorer_agent_id="sentinel",
            dimensions={"g": 1.0},
        ).validate()
    with pytest.raises(ValueError, match="may not review its own"):
        Review(
            review_id="r1",
            artifact_id="art_1",
            producer_agent_id="sentinel",
            reviewer_agent_id="sentinel",
            verdict=ReviewVerdict.PASS,
            findings=(),
            artifact_hash="a" * 64,
        ).validate()


def _runtime(tmp_path: Path) -> MvlRuntime:
    definition = AgentDefinition(
        agent_id="sentinel",
        display_name="Sentinel",
        role="Decision-integrity reflective critic",
        version="test-v1",
        owner="test-owner",
        allowed_job_types=("watch_ticket_review",),
        allowed_tools=("kb.search", "ticket.read", "artifact.write"),
        denied_tools=("score.write",),
        retrieval_required=True,
        budget=BudgetPolicy(max_model_calls=2, max_tool_calls=3, max_cost_usd=0.0, deadline_seconds=60),
        deployment_state=DeploymentState.SHADOW,
        enabled=True,
    )
    return MvlRuntime(
        definition=definition,
        journal=ShadowRunJournal(tmp_path / "shadow-runs", Environment.SHADOW),
        retrieval_provider=lambda run_id, query: [
            {"ref": "lesson:stop-direction", "content": "A long stop must remain below entry."},
        ],
        model_provider=lambda run_id, request: {
            "verdict": "CAUTION",
            "request_hash": canonical_hash(request),
        },
    )


def _artifact(subject: MvlRuntime):
    run = subject.start(
        job_type="watch_ticket_review",
        objective="Challenge one deterministic Watch ticket without changing it.",
        input_payload={"symbol": "TEST", "ticket": {"entry": 10.0, "stop": 9.5}},
        validation_payload={"state": "PASS", "hash": "fixture-validation"},
    )
    subject.retrieve(run.run_id, "known contradictions for TEST")
    output = subject.reason(
        run.run_id,
        prompt_version="v1",
        provider_family="local",
        model="fixture",
        request_payload={"fixture": True},
    )
    artifact = subject.create_artifact(
        run.run_id,
        artifact_type="critique",
        payload=output,
        prompt_version="v1",
        provider_family="local",
        model="fixture",
    )
    return run, artifact


def test_the_runtime_refuses_a_scorer_that_already_reviewed_the_same_artifact(tmp_path: Path):
    subject = _runtime(tmp_path)
    run, artifact = _artifact(subject)
    subject.record_review(run.run_id, artifact, "iris", ReviewVerdict.CAUTION, ["checked"])

    with pytest.raises(ValueError, match="reviewer and scorer must be different"):
        subject.record_score(run.run_id, artifact, "iris", {"grounding": 1.0})


def test_an_independent_scorer_is_still_accepted(tmp_path: Path):
    """Positive control: the new edge must not break the loop it is protecting."""
    subject = _runtime(tmp_path)
    run, artifact = _artifact(subject)
    subject.record_review(run.run_id, artifact, "iris", ReviewVerdict.CAUTION, ["checked"])

    score = subject.record_score(run.run_id, artifact, "darwin", {"grounding": 1.0})

    assert score.scorer_agent_id == "darwin"
    assert score.reviewer_agent_id == "iris"
    subject.complete(run.run_id)
    assert subject.status(run.run_id)["status"] == "COMPLETED"
