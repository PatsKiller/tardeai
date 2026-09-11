"""Unit tests for scripts/lib/l3_judgment_cache.py — subject isolation + invalidation."""

from __future__ import annotations

import pytest

from scripts.lib.l3_judgment_cache import (
    CacheEntry,
    JudgmentCache,
    build_cache_key,
    evidence_revision_token,
)
from scripts.lib.l3_judgment_author import run_author
from scripts.lib.material_residual_gate import evaluate_material_residual_gate
from tests.helpers.l3_fixtures import (
    FACT_A1,
    FACT_B1,
    OFFPEAK_SUMMER_ET,
    SUBJECT_A,
    SUBJECT_B,
    make_author_call_fn,
    make_author_json,
    make_fact,
    make_grounded_input,
)


def _gate_and_grounded(**kwargs):
    raw = make_grounded_input(**kwargs)
    gate = evaluate_material_residual_gate(raw, now=OFFPEAK_SUMMER_ET)
    assert gate.proceed
    return raw, gate.to_dict()


def test_cache_hit_zero_provider_calls():
    cache = JudgmentCache()
    raw, gate = _gate_and_grounded()
    counter: list[int] = []
    author_fn = make_author_call_fn(counter=counter)
    first = run_author(grounded=raw, gate=gate, cache=cache, call_fn=author_fn, now=OFFPEAK_SUMMER_ET)
    assert first["ok"] is True
    assert first["cache_hit"] is False
    assert len(counter) == 1

    second = run_author(grounded=raw, gate=gate, cache=cache, call_fn=author_fn, now=OFFPEAK_SUMMER_ET)
    assert second["ok"] is True
    assert second["cache_hit"] is True
    assert second["provider_calls"] == 0
    assert len(counter) == 1  # no second provider call


def test_evidence_change_invalidates_cache():
    cache = JudgmentCache()
    raw, gate = _gate_and_grounded()
    run_author(
        grounded=raw,
        gate=gate,
        cache=cache,
        call_fn=make_author_call_fn(),
        now=OFFPEAK_SUMMER_ET,
    )
    # Change fact digest → new evidence revision → miss
    raw2 = make_grounded_input(
        facts=[
            make_fact(
                memory_fact_id=FACT_A1,
                subject_guid=SUBJECT_A,
                fact_text="UPDATED filing detail",
            )
        ]
    )
    raw2["memory_facts"][0]["fact_digest"] = "sha256:changed-evidence"
    gate2 = evaluate_material_residual_gate(raw2, now=OFFPEAK_SUMMER_ET).to_dict()
    counter: list[int] = []
    hit = run_author(
        grounded=raw2,
        gate=gate2,
        cache=cache,
        call_fn=make_author_call_fn(counter=counter),
        now=OFFPEAK_SUMMER_ET,
    )
    assert hit["cache_hit"] is False
    assert len(counter) == 1


def test_cross_subject_isolation():
    cache = JudgmentCache()
    raw_a, gate_a = _gate_and_grounded(subject_guid=SUBJECT_A, symbol="AAA")
    run_author(
        grounded=raw_a,
        gate=gate_a,
        cache=cache,
        call_fn=make_author_call_fn(make_author_json(subject_guid=SUBJECT_A)),
        now=OFFPEAK_SUMMER_ET,
    )
    raw_b = make_grounded_input(
        subject_guid=SUBJECT_B,
        symbol="BBB",
        facts=[
            make_fact(
                memory_fact_id=FACT_B1,
                subject_guid=SUBJECT_B,
                fact_text="BBB deteriorating margins",
            )
        ],
        question_text="Does BBB thesis still hold?",
    )
    gate_b = evaluate_material_residual_gate(raw_b, now=OFFPEAK_SUMMER_ET).to_dict()
    key_a = build_cache_key(
        subject_guid=SUBJECT_A,
        material_question=gate_a["material_question"],
        grounded=raw_a,
        memory_fact_ids=gate_a["selected_memory_fact_ids"],
    )
    # Direct get with B's subject against A's key must miss.
    evid = evidence_revision_token(raw_a, gate_a["selected_memory_fact_ids"])
    assert cache.get(key_a, subject_guid=SUBJECT_B, evidence_revision=evid) is None

    counter: list[int] = []
    b = run_author(
        grounded=raw_b,
        gate=gate_b,
        cache=cache,
        call_fn=make_author_call_fn(
            make_author_json(subject_guid=SUBJECT_B, memory_fact_ids=[FACT_B1]),
            counter=counter,
        ),
        now=OFFPEAK_SUMMER_ET,
    )
    assert b["cache_hit"] is False
    assert len(counter) == 1
    assert b["subject_guid"] == SUBJECT_B


def test_put_refuses_cross_subject_spoof():
    cache = JudgmentCache()
    with pytest.raises(ValueError, match="cross_subject"):
        cache.put(
            CacheEntry(
                cache_key=f"l3cache:{SUBJECT_A}:deadbeef",
                subject_guid=SUBJECT_B,
                created_at="2026-09-11T00:00:00Z",
                evidence_revision="rev",
                author_judgment={},
                provider="deepseek",
                requested_model="deepseek-flash",
                returned_model="deepseek-flash",
            )
        )
