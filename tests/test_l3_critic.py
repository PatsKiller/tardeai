"""Unit tests for scripts/lib/independent_critic.py — provider separation + revise."""

from __future__ import annotations

from scripts.lib.independent_critic import apply_field_changes, run_independent_critic
from scripts.lib.judgment_schema import CRITIC_PROVIDER_COLLISION, QUARANTINED
from scripts.lib.l3_judgment_author import run_author
from scripts.lib.material_residual_gate import evaluate_material_residual_gate
from scripts.lib.model_policy import L3ModelPolicy, default_l3_policy
from tests.helpers.l3_fixtures import (
    OFFPEAK_SUMMER_ET,
    make_author_call_fn,
    make_author_json,
    make_critic_call_fn,
    make_grounded_input,
)


def _author():
    raw = make_grounded_input()
    gate = evaluate_material_residual_gate(raw, now=OFFPEAK_SUMMER_ET).to_dict()
    author = run_author(
        grounded=raw,
        gate=gate,
        call_fn=make_author_call_fn(make_author_json()),
        now=OFFPEAK_SUMMER_ET,
    )
    assert author["ok"] is True
    return raw, author


def test_same_provider_fails_closed_zero_calls():
    raw, author = _author()
    policy = L3ModelPolicy(
        author_provider="deepseek",
        author_model_id="deepseek-flash",
        critic_provider="deepseek",  # collision
        critic_model="deepseek-flash",
    )
    counter: list[int] = []
    out = run_independent_critic(
        grounded=raw,
        author=author,
        policy=policy,
        call_fn=make_critic_call_fn(counter=counter),
    )
    assert out["ok"] is False
    assert out["refusal_state"] == CRITIC_PROVIDER_COLLISION
    assert out["provider_calls"] == 0
    assert counter == []


def test_returned_same_provider_fails_closed():
    raw, author = _author()
    counter: list[int] = []
    out = run_independent_critic(
        grounded=raw,
        author=author,
        policy=default_l3_policy(),
        call_fn=make_critic_call_fn(
            force_returned_provider="deepseek",
            counter=counter,
        ),
    )
    assert out["ok"] is False
    assert out["refusal_state"] == CRITIC_PROVIDER_COLLISION
    assert len(counter) == 1  # call happened but critique not accepted


def test_revise_preserves_before_after_named_field():
    raw, author = _author()
    changes = [
        {
            "field": "confidence",
            "before": author["confidence"],
            "after": 0.41,
        }
    ]
    out = run_independent_critic(
        grounded=raw,
        author=author,
        call_fn=make_critic_call_fn(verdict="revise", field_changes=changes),
    )
    assert out["ok"] is True
    assert out["verdict"] == "revise"
    fc = out["field_changes"][0]
    assert fc["field"] == "confidence"
    assert fc["before"] == author["confidence"]
    assert fc["after"] == 0.41
    revised = apply_field_changes(author, out)
    assert revised["confidence"] == 0.41


def test_reject_and_abstain_paths_ok_flag():
    raw, author = _author()
    for verdict in ("reject", "abstain"):
        out = run_independent_critic(
            grounded=raw,
            author=author,
            call_fn=make_critic_call_fn(verdict=verdict),
        )
        assert out["ok"] is True
        assert out["verdict"] == verdict


def test_malformed_critic_quarantined():
    raw, author = _author()
    out = run_independent_critic(
        grounded=raw,
        author=author,
        call_fn=make_critic_call_fn(raw_content="NOT JSON {{{"),
    )
    assert out["ok"] is False
    assert out["refusal_state"] in {QUARANTINED, "SCHEMA_INVALID"}
