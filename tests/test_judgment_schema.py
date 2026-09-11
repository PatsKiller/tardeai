"""Unit tests for scripts/lib/judgment_schema.py — L3 schemas and refusals."""

from __future__ import annotations

import pytest

from scripts.lib.judgment_schema import (
    AUTHORITY,
    MBI_BEHAVIOR,
    MODEL_MISMATCH,
    NO_MATERIAL_RESIDUAL,
    QUARANTINED,
    UNGROUNDED_REFUSED,
    JudgmentSchemaError,
    build_refusal_output,
    validate_author_judgment,
    validate_critique,
    validate_grounded_input,
)
from tests.helpers.l3_fixtures import (
    FACT_A1,
    SUBJECT_A,
    SUBJECT_B,
    make_author_json,
    make_fact,
    make_grounded_input,
)


def test_validate_grounded_input_accepts_valid():
    g = validate_grounded_input(make_grounded_input())
    assert g["schema"] == "GroundedJudgmentInput@v1"
    assert g["_wrong_subject_fact_ids"] == []


def test_wrong_subject_fact_ids_flagged():
    g = validate_grounded_input(
        make_grounded_input(
            facts=[
                make_fact(
                    memory_fact_id=FACT_A1,
                    subject_guid=SUBJECT_B,
                    fact_text="wrong subject memory",
                )
            ]
        )
    )
    assert FACT_A1 in g["_wrong_subject_fact_ids"]


def test_cliff_applied_forbidden():
    raw = make_grounded_input()
    raw["retrieval"]["cliff_applied"] = True
    with pytest.raises(JudgmentSchemaError, match="cliff_applied_forbidden"):
        validate_grounded_input(raw)


def test_author_invented_number_without_evidence_refused():
    grounded = make_grounded_input()
    payload = make_author_json(claim="Revenue grew 42% without citation")
    payload["evidence_source_ids"] = []
    # Fill required envelope fields for direct schema validate.
    envelope = {
        **payload,
        "judgment_id": "jdg_test",
        "subject_guid": SUBJECT_A,
        "question": "q",
        "provider": "deepseek",
        "requested_model": "deepseek-flash",
        "returned_model": "deepseek-flash",
        "prompt_template_version": "l3_judgment_author@v1",
        "input_digest": "sha256:x",
        "output_digest": "sha256:y",
        "cache_key": "k",
        "cache_hit": False,
        "cost_usd": 0.0,
        "latency_ms": 1,
        "source_sha": "aa43a8c9e61e963030fa15009c975f1de88da85a",
        "release": "",
        "epoch_id": "epoch",
        "trigger": "scheduled",
        "schema_version": "L3AuthorJudgment@v1",
    }
    with pytest.raises(JudgmentSchemaError) as ei:
        validate_author_judgment(envelope, grounded=grounded)
    msg = str(ei.value)
    assert "invented_number_uncited" in msg or "missing_evidence_source_ids" in msg


def test_author_missing_evidence_id_refused():
    grounded = make_grounded_input()
    payload = make_author_json(memory_fact_ids=["ffffffff-ffff-4fff-8fff-ffffffffffff"])
    envelope = {
        **payload,
        "judgment_id": "jdg_test",
        "subject_guid": SUBJECT_A,
        "question": "q",
        "provider": "deepseek",
        "requested_model": "deepseek-flash",
        "returned_model": "deepseek-flash",
        "prompt_template_version": "l3_judgment_author@v1",
        "input_digest": "sha256:x",
        "output_digest": "sha256:y",
        "cache_key": "k",
        "cache_hit": False,
        "cost_usd": 0.0,
        "latency_ms": 1,
        "source_sha": "aa43a8c9e61e963030fa15009c975f1de88da85a",
        "release": "",
        "epoch_id": "epoch",
        "trigger": "scheduled",
        "schema_version": "L3AuthorJudgment@v1",
    }
    with pytest.raises(JudgmentSchemaError, match="uncited_memory_fact"):
        validate_author_judgment(envelope, grounded=grounded)


def test_author_broker_language_refused():
    grounded = make_grounded_input()
    payload = make_author_json(claim="place_order for 100 shares via broker")
    envelope = {
        **payload,
        "judgment_id": "jdg_test",
        "subject_guid": SUBJECT_A,
        "question": "q",
        "provider": "deepseek",
        "requested_model": "deepseek-flash",
        "returned_model": "deepseek-flash",
        "prompt_template_version": "l3_judgment_author@v1",
        "input_digest": "sha256:x",
        "output_digest": "sha256:y",
        "cache_key": "k",
        "cache_hit": False,
        "cost_usd": 0.0,
        "latency_ms": 1,
        "source_sha": "aa43a8c9e61e963030fa15009c975f1de88da85a",
        "release": "",
        "epoch_id": "epoch",
        "trigger": "scheduled",
        "schema_version": "L3AuthorJudgment@v1",
    }
    with pytest.raises(JudgmentSchemaError, match="broker_or_mutation_language"):
        validate_author_judgment(envelope, grounded=grounded)


def test_author_non_json_refused():
    with pytest.raises(JudgmentSchemaError, match="non_json"):
        validate_author_judgment("not-json{", grounded=make_grounded_input())


def test_critique_same_provider_refused():
    with pytest.raises(JudgmentSchemaError, match="author_critic_same_provider"):
        validate_critique(
            {
                "critique_id": "c1",
                "verdict": "accept",
                "contradictions": [],
                "unsupported_claims": [],
                "field_changes": [],
                "provider": "deepseek",
                "model_returned": "deepseek-flash",
                "cost_usd": 0.0,
                "latency_ms": 1,
                "author_provider": "deepseek",
                "independence_proof": {},
            },
            author_provider="deepseek",
        )


def test_critique_revise_requires_before_after():
    with pytest.raises(JudgmentSchemaError, match="revise_without_named_field|field_change"):
        validate_critique(
            {
                "critique_id": "c1",
                "verdict": "revise",
                "contradictions": [],
                "unsupported_claims": [],
                "field_changes": [],
                "provider": "grok",
                "model_returned": "grok-3-mini",
                "cost_usd": 0.0,
                "latency_ms": 1,
                "author_provider": "deepseek",
                "independence_proof": {},
            },
            author_provider="deepseek",
        )


def test_build_refusal_ungrounded_maps_no_grounding():
    out = build_refusal_output(
        grounded=make_grounded_input(grounded=False, facts=[]),
        gate_state=UNGROUNDED_REFUSED,
        reasons=["grounded_false_or_empty_memory"],
        provider_calls=0,
    )
    assert out["status"] == "REFUSED"
    assert out["refusal_reason"] == "no_grounding"
    assert out["refusal_state"] == UNGROUNDED_REFUSED
    assert out["provider_calls"] == 0
    assert out["author"] is None
    assert out["commitment"] is None
    assert out["mbi_behavior"] == MBI_BEHAVIOR
    assert out["authority"] == AUTHORITY
    assert out["provenance_class"] == "T"


def test_build_refusal_no_material_and_model_mismatch():
    nm = build_refusal_output(
        grounded=make_grounded_input(residual_present=False),
        gate_state=NO_MATERIAL_RESIDUAL,
        provider_calls=0,
    )
    assert nm["refusal_reason"] == "no_material_question"
    mm = build_refusal_output(
        grounded=make_grounded_input(),
        gate_state=MODEL_MISMATCH,
        provider_calls=1,
    )
    assert mm["refusal_reason"] == "model_mismatch"
    q = build_refusal_output(
        grounded=make_grounded_input(),
        gate_state=QUARANTINED,
        provider_calls=1,
    )
    assert q["refusal_reason"] == "schema_invalid"
