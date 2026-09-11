"""Unit tests for AgentView@v1 L3 extensions — provenance A vs T."""

from __future__ import annotations

from scripts.lib.agent_view_v1 import persist_allowed, produce_agent_view_v1
from scripts.lib.l3_agent_view_synthesis import synthesize_agent_view
from scripts.lib.l3_judgment_author import run_author
from scripts.lib.independent_critic import run_independent_critic
from scripts.lib.material_residual_gate import evaluate_material_residual_gate
from tests.helpers.l3_fixtures import (
    OFFPEAK_SUMMER_ET,
    make_author_call_fn,
    make_author_json,
    make_critic_call_fn,
    make_grounded_input,
)


def test_class_a_requires_llm_provenance_and_non_zero_cost_class():
    view = produce_agent_view_v1(
        subject="SUBJ",
        summary="Model judgment with citations",
        citations=["mem-1"],
        confidence=0.7,
        source_sha="abc",
        stance="RECOMMEND",
        falsifier="Price breaks support",
        provenance_class="A",
        cost_class="zero",  # must be upgraded / fail critic
        llm_provenance={"author_provider": "deepseek", "author_model": "deepseek-flash"},
    )
    # produce upgrades zero→model when class A
    assert view.provenance_class == "A"
    assert view.cost_class != "zero"
    assert view.llm_provenance is not None
    assert view.critic_pass is True


def test_class_t_cannot_masquerade_with_llm_provenance():
    view = produce_agent_view_v1(
        subject="SUBJ",
        summary="template",
        citations=["s1"],
        confidence=0.6,
        source_sha="abc",
        provenance_class="T",
        llm_provenance={"author_provider": "deepseek"},
    )
    # llm_provenance with T is auto-promoted to A by produce_agent_view_v1
    assert view.provenance_class == "A"
    # Explicit T + llm after the fact fails critic_pass path:
    view.provenance_class = "T"
    from scripts.lib.agent_view_v1 import critic_pass

    failed = critic_pass(view)
    assert failed.critic_pass is False
    assert "class_T_with_llm_provenance" in failed.critic_notes


def test_template_default_remains_class_t_cost_zero():
    view = produce_agent_view_v1(
        subject="SUBJ",
        summary="quiet tape",
        citations=["s1"],
        confidence=0.6,
        source_sha="abc",
    )
    assert view.provenance_class == "T"
    assert view.cost_class == "zero"
    assert view.llm_provenance is None
    assert persist_allowed(view) is True


def test_l3_synthesis_emits_class_a_with_llm():
    raw = make_grounded_input()
    gate = evaluate_material_residual_gate(raw, now=OFFPEAK_SUMMER_ET).to_dict()
    author = run_author(
        grounded=raw,
        gate=gate,
        call_fn=make_author_call_fn(make_author_json()),
        now=OFFPEAK_SUMMER_ET,
        source_sha=raw["source_sha"],
    )
    critique = run_independent_critic(
        grounded=raw,
        author=author,
        call_fn=make_critic_call_fn(verdict="accept"),
    )
    view = synthesize_agent_view(
        author=author,
        critique=critique,
        grounded=raw,
        source_sha=raw["source_sha"],
    )
    assert view["provenance_class"] == "A"
    assert view["cost_class"] != "zero"
    assert view["provenance"]["llm"] is not None
    assert view["falsifier"]
    assert view["mbi_behavior"] == 0
    assert view["sizes_or_executes_trades"] is False
    assert view.get("behavioral_mutation_fields") is None
    assert view.get("portfolio_mutation_fields") is None
