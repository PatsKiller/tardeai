from __future__ import annotations

import dataclasses

import pytest

from scripts.agent_runtime.contracts import FORBIDDEN_TOOL_PREFIXES, DeploymentState
from scripts.agent_runtime.agents import base as base_mod
from scripts.agent_runtime.agents.base import (
    OutputKind,
    ShadowAgentSpec,
    Trigger,
    TriggerKind,
    assert_fleet_separation,
    assert_no_self_governance,
)
from scripts.agent_runtime.agents.definitions import (
    FLEET,
    INITIAL_SHADOW_AGENT_IDS,
    SECOND_WAVE_AGENT_IDS,
    THIRD_WAVE_AGENT_IDS,
    initial_agents,
    reviewer_scorer_matrix,
    second_wave_agents,
    spec,
)


def test_fleet_roster_matches_wave_partitions() -> None:
    # The fleet is exactly the union of the three authored waves. The enabled
    # INITIAL shadow set grew to include vigil (health) and the wave-3 CIO/wealth
    # advisors (alex/steph/morgan); ledger is wave-3 but disabled (DESIGNED).
    assert set(FLEET) == (
        set(INITIAL_SHADOW_AGENT_IDS)
        | set(SECOND_WAVE_AGENT_IDS)
        | set(THIRD_WAVE_AGENT_IDS)
    )
    assert set(INITIAL_SHADOW_AGENT_IDS) == {
        "sentinel", "darwin", "iris", "reflection", "argus",
        "vigil", "alex", "steph", "morgan",
    }
    assert set(SECOND_WAVE_AGENT_IDS) == {"maria", "vega", "risk_agent", "aegis"}
    assert set(THIRD_WAVE_AGENT_IDS) == {"steph", "ledger", "morgan"}


def test_whole_fleet_validates_and_separation_holds() -> None:
    assert_fleet_separation(FLEET)  # raises on any violation


def test_initial_agents_are_enabled_in_shadow() -> None:
    # INITIAL_SHADOW_AGENT_IDS is the enabled-SHADOW fleet: wave-1 INITIAL
    # (sentinel/darwin/iris/reflection/argus/vigil) plus wave-3 THIRD
    # (alex/steph/morgan). All must be enabled, SHADOW, and operable.
    for agent_id in INITIAL_SHADOW_AGENT_IDS:
        s = spec(agent_id)
        assert s.definition.enabled is True
        assert s.definition.deployment_state is DeploymentState.SHADOW
        assert s.is_operable_now is True
        assert s.wave in {"INITIAL", "THIRD"}


def test_second_wave_agents_are_disabled_and_designed_only() -> None:
    for agent_id in SECOND_WAVE_AGENT_IDS:
        s = spec(agent_id)
        assert s.definition.enabled is False
        assert s.definition.deployment_state is DeploymentState.DESIGNED
        assert s.is_operable_now is False
        assert s.wave == "SECOND"


def test_reviewer_and_scorer_are_always_different_agents() -> None:
    for agent_id, s in FLEET.items():
        assert s.reviewer_agent_id != agent_id, agent_id
        assert s.scorer_agent_id != agent_id, agent_id
        assert s.reviewer_agent_id in FLEET
        assert s.scorer_agent_id in FLEET


def test_reviewer_scorer_matrix_matches_specs() -> None:
    matrix = reviewer_scorer_matrix()
    assert matrix["sentinel"] == {"reviewer": "iris", "scorer": "darwin"}
    assert matrix["darwin"]["scorer"] == "sentinel"
    for agent_id, row in matrix.items():
        assert row["reviewer"] != agent_id
        assert row["scorer"] != agent_id


def test_every_agent_declares_triggers_and_outputs() -> None:
    for agent_id, s in FLEET.items():
        assert s.triggers, agent_id
        assert s.allowed_output_kinds, agent_id
        for trigger in s.triggers:
            assert isinstance(trigger.kind, TriggerKind)
            assert trigger.owned_by == "deterministic-scheduler"


def test_no_agent_holds_forbidden_or_self_governance_authority() -> None:
    for s in FLEET.values():
        # constitutional deny surface (contracts) + self-governance surface (base)
        assert_no_self_governance(s)
        # Prefix-match against the constitutional deny list. A bare substring
        # check would false-positive "data_broker.read" (a read tool) on "broker";
        # the deny list is prefix-scoped ("broker.", "order.", ...) for that reason.
        for tool in s.definition.allowed_tools:
            lowered = tool.lower()
            assert not any(
                lowered == prefix.rstrip(".") or lowered.startswith(prefix)
                for prefix in FORBIDDEN_TOOL_PREFIXES
            ), tool


def test_budgets_and_breakers_are_bounded() -> None:
    for s in FLEET.values():
        b = s.definition.budget
        assert b.max_model_calls >= 0
        assert b.max_tool_calls >= 1
        # Wave-3 advisors (alex/steph/morgan) and the migrated reflective critics
        # (sentinel/iris/reflection) carry a small paid allowance; deterministic
        # agents remain at 0.0.
        assert b.max_cost_usd >= 0.0
        assert 1 <= b.deadline_seconds <= 86_400
        assert s.circuit_breaker_trips_open_after >= 1
        assert s.stale_input_seconds >= 1


def test_darwin_is_a_deterministic_scorer_with_no_model_calls() -> None:
    d = spec("darwin")
    assert d.definition.budget.max_model_calls == 0
    assert d.definition.retrieval_required is False
    assert "score.write" in d.definition.allowed_tools


def test_allowlisting_a_forbidden_tool_is_rejected() -> None:
    good = spec("sentinel")
    bad = dataclasses.replace(
        good,
        definition=dataclasses.replace(
            good.definition,
            allowed_tools=good.definition.allowed_tools + ("broker.submit_order",),
        ),
    )
    with pytest.raises(ValueError):
        bad.validate()


def test_allowlisting_a_self_governance_tool_is_rejected() -> None:
    good = spec("iris")
    bad = dataclasses.replace(
        good,
        definition=dataclasses.replace(
            good.definition,
            allowed_tools=good.definition.allowed_tools + ("lesson.promote",),
        ),
    )
    with pytest.raises(ValueError):
        assert_no_self_governance(bad)


def test_spec_cannot_be_its_own_reviewer() -> None:
    good = spec("vega")
    bad = dataclasses.replace(good, reviewer_agent_id="vega")
    with pytest.raises(ValueError):
        bad.validate()


def test_trigger_cannot_be_owned_by_an_agent() -> None:
    with pytest.raises(ValueError):
        Trigger(TriggerKind.NIGHTLY_BATCH, "x", owned_by="agent").validate()


def test_operational_state_is_unreachable_through_a_definition() -> None:
    good = spec("sentinel")
    bad = dataclasses.replace(
        good,
        definition=dataclasses.replace(good.definition, deployment_state=DeploymentState.OPERATIONAL),
    )
    with pytest.raises(ValueError):
        assert_no_self_governance(bad)
