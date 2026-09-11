"""Unit tests for L3 commitment synthesis — falsifier + critic gates."""

from __future__ import annotations

from scripts.lib.l3_agent_view_synthesis import synthesize_agent_view, synthesize_commitment
from scripts.lib.l3_judgment_pipeline import run_l3_judgment_pipeline
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


def _parts(*, falsifier: str = "Next print invalidates claim", verdict: str = "accept"):
    raw = make_grounded_input()
    gate = evaluate_material_residual_gate(raw, now=OFFPEAK_SUMMER_ET).to_dict()
    author = run_author(
        grounded=raw,
        gate=gate,
        call_fn=make_author_call_fn(make_author_json(falsifier=falsifier)),
        now=OFFPEAK_SUMMER_ET,
        source_sha=raw["source_sha"],
    )
    assert author["ok"]
    critique = run_independent_critic(
        grounded=raw,
        author=author,
        call_fn=make_critic_call_fn(verdict=verdict),
    )
    assert critique["ok"]
    view = synthesize_agent_view(
        author=author,
        critique=critique,
        grounded=raw,
        source_sha=raw["source_sha"],
    )
    return raw, author, critique, view


def test_missing_falsifier_blocks_commitment_explanation_may_exist():
    raw, author, critique, view = _parts(falsifier="valid falsifier")
    # Strip falsifier on revised author path.
    critique = dict(critique)
    critique["revised_author"] = dict(author)
    critique["revised_author"]["falsifier"] = ""
    view_no_f = dict(view)
    view_no_f["falsifier"] = ""
    cmt = synthesize_commitment(
        author=author,
        critique=critique,
        agent_view=view_no_f,
        grounded=raw,
        source_sha=raw["source_sha"],
    )
    assert cmt is None


def test_critic_reject_abstain_no_commitment():
    for verdict in ("reject", "abstain"):
        raw, author, critique, view = _parts(verdict=verdict)
        cmt = synthesize_commitment(
            author=author,
            critique=critique,
            agent_view=view,
            grounded=raw,
            source_sha=raw["source_sha"],
        )
        assert cmt is None


def test_accept_builds_commitment_with_required_fields():
    raw, author, critique, view = _parts(verdict="accept")
    cmt = synthesize_commitment(
        author=author,
        critique=critique,
        agent_view=view,
        grounded=raw,
        source_sha=raw["source_sha"],
        release="test-release",
    )
    assert cmt is not None
    assert cmt["falsifier"]
    assert cmt["judgment_id"]
    assert cmt["critique_id"]
    assert cmt["checkpoint_binding"]
    assert cmt["evidence_ids"]["memory_fact_ids"]
    assert "order" not in cmt
    assert "quantity" not in cmt
    assert "broker" not in cmt


def test_pipeline_reject_no_commitment_row():
    result = run_l3_judgment_pipeline(
        make_grounded_input(),
        author_call_fn=make_author_call_fn(),
        critic_call_fn=make_critic_call_fn(verdict="reject"),
        now=OFFPEAK_SUMMER_ET,
    )
    assert result.ok is True
    assert result.commitment is None
    kinds = [r.get("kind") for r in result.durable_rows]
    assert "explanation_without_commitment" in kinds
    assert "commitment" not in kinds
