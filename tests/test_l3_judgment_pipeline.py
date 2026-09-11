"""Integration-style unit tests for scripts/lib/l3_judgment_pipeline.py."""

from __future__ import annotations

import json

from scripts.lib.judgment_schema import (
    CAP_REFUSED,
    FREE_FIRST_PENDING,
    MODEL_MISMATCH,
    NO_MATERIAL_RESIDUAL,
    QUARANTINED,
    SCHEMA_INVALID,
    UNGROUNDED_REFUSED,
    WRONG_SUBJECT_REFUSED,
)
from scripts.lib.l3_judgment_cache import JudgmentCache
from scripts.lib.l3_judgment_pipeline import run_l3_judgment_pipeline
from tests.helpers.l3_fixtures import (
    FACT_A1,
    FACT_B1,
    OFFPEAK_SUMMER_ET,
    SUBJECT_A,
    SUBJECT_B,
    make_author_call_fn,
    make_author_json,
    make_critic_call_fn,
    make_fact,
    make_grounded_input,
)


def test_no_grounding_zero_provider_calls_durable_refusal():
    author_calls: list[int] = []
    critic_calls: list[int] = []
    result = run_l3_judgment_pipeline(
        make_grounded_input(grounded=False, facts=[]),
        author_call_fn=make_author_call_fn(counter=author_calls),
        critic_call_fn=make_critic_call_fn(counter=critic_calls),
        now=OFFPEAK_SUMMER_ET,
    )
    assert result.ok is False
    assert result.provider_calls == 0
    assert author_calls == [] and critic_calls == []
    assert result.output["status"] == "REFUSED"
    assert result.output["refusal_state"] == UNGROUNDED_REFUSED
    assert result.output["refusal_reason"] == "no_grounding"
    assert any(r.get("kind") == "refusal" for r in result.durable_rows)


def test_wrong_subject_memory_refused_zero_calls():
    author_calls: list[int] = []
    result = run_l3_judgment_pipeline(
        make_grounded_input(
            facts=[
                make_fact(
                    memory_fact_id=FACT_A1,
                    subject_guid=SUBJECT_B,
                    fact_text="leaked wrong subject",
                )
            ]
        ),
        author_call_fn=make_author_call_fn(counter=author_calls),
        critic_call_fn=make_critic_call_fn(),
        now=OFFPEAK_SUMMER_ET,
    )
    assert result.output["refusal_state"] == WRONG_SUBJECT_REFUSED
    assert result.provider_calls == 0
    assert author_calls == []


def test_free_first_not_exhausted_zero_calls():
    author_calls: list[int] = []
    result = run_l3_judgment_pipeline(
        make_grounded_input(free_first_exhausted=False),
        author_call_fn=make_author_call_fn(counter=author_calls),
        critic_call_fn=make_critic_call_fn(),
        now=OFFPEAK_SUMMER_ET,
    )
    assert result.output["refusal_state"] == FREE_FIRST_PENDING
    assert result.provider_calls == 0
    assert author_calls == []


def test_no_material_residual_zero_calls():
    author_calls: list[int] = []
    result = run_l3_judgment_pipeline(
        make_grounded_input(residual_present=False),
        author_call_fn=make_author_call_fn(counter=author_calls),
        critic_call_fn=make_critic_call_fn(),
        now=OFFPEAK_SUMMER_ET,
    )
    assert result.output["refusal_state"] == NO_MATERIAL_RESIDUAL
    assert result.output["refusal_reason"] == "no_material_question"
    assert result.provider_calls == 0
    assert author_calls == []


def test_budget_and_lane_caps_refuse():
    for kwargs, reason_frag in (
        ({"budget_remaining_usd": 0.0}, "budget"),
        ({"lane_calls_remaining": 0}, "lane_call"),
        ({"request_cap_remaining": 0}, "request_cap"),
    ):
        author_calls: list[int] = []
        result = run_l3_judgment_pipeline(
            make_grounded_input(),
            author_call_fn=make_author_call_fn(counter=author_calls),
            critic_call_fn=make_critic_call_fn(),
            now=OFFPEAK_SUMMER_ET,
            **kwargs,
        )
        assert result.output["refusal_state"] == CAP_REFUSED
        assert result.output["refusal_reason"] == "budget_cap"
        assert result.provider_calls == 0
        assert author_calls == []
        assert any(reason_frag in r for r in result.gate["reasons"])


def test_model_mismatch_refusal():
    result = run_l3_judgment_pipeline(
        make_grounded_input(),
        author_call_fn=make_author_call_fn(returned_model="deepseek-chat"),
        critic_call_fn=make_critic_call_fn(),
        now=OFFPEAK_SUMMER_ET,
    )
    assert result.ok is False
    assert result.output["refusal_state"] == MODEL_MISMATCH
    assert result.output["refusal_reason"] == "model_mismatch"
    assert result.commitment is None
    assert result.provider_calls == 1


def test_malformed_author_quarantined():
    def bad_author(**_kw):
        class Resp:
            ok = True
            content = "NOT-JSON{{{{"
            requested_model_id = "deepseek-flash"
            returned_model = "deepseek-flash"
            error_class = None
            error_message = None
            latency_ms = 1
            cost_usd = 0.0

        return Resp()

    result = run_l3_judgment_pipeline(
        make_grounded_input(),
        author_call_fn=bad_author,
        critic_call_fn=make_critic_call_fn(),
        now=OFFPEAK_SUMMER_ET,
    )
    assert result.ok is False
    assert result.output["refusal_state"] in {SCHEMA_INVALID, QUARANTINED}
    assert result.provider_calls == 1


def test_happy_path_judged_with_commitment():
    result = run_l3_judgment_pipeline(
        make_grounded_input(),
        author_call_fn=make_author_call_fn(),
        critic_call_fn=make_critic_call_fn(verdict="accept"),
        now=OFFPEAK_SUMMER_ET,
        source_sha="aa43a8c9e61e963030fa15009c975f1de88da85a",
    )
    assert result.ok is True
    assert result.output["status"] == "JUDGED"
    assert result.output["provenance_class"] == "A"
    assert result.agent_view is not None
    assert result.agent_view["falsifier"]
    assert result.commitment is not None
    assert result.commitment["falsifier"]
    assert result.provider_calls >= 2
    # No broker / order / quantity surfaces
    blob = json.dumps(result.output)
    for banned in ("place_order", '"quantity"', '"broker"', "stop_loss"):
        assert banned not in blob


def test_variable_stance_across_materially_different_inputs():
    bullish = make_grounded_input(
        subject_guid=SUBJECT_A,
        symbol="AAA",
        question_text="Is AAA strengthening?",
        facts=[
            make_fact(
                memory_fact_id=FACT_A1,
                subject_guid=SUBJECT_A,
                fact_text="AAA beat estimates; guidance raised; margins expanding.",
            )
        ],
    )
    bearish = make_grounded_input(
        subject_guid=SUBJECT_B,
        symbol="BBB",
        question_text="Is BBB deteriorating?",
        facts=[
            make_fact(
                memory_fact_id=FACT_B1,
                subject_guid=SUBJECT_B,
                fact_text="BBB missed; guidance cut; customer churn rising.",
            )
        ],
        correlation_id="corr-l3-test-bear",
    )
    r_bull = run_l3_judgment_pipeline(
        bullish,
        author_call_fn=make_author_call_fn(make_author_json(stance="BULLISH", claim="AAA strengthening on guidance")),
        critic_call_fn=make_critic_call_fn(verdict="accept"),
        now=OFFPEAK_SUMMER_ET,
    )
    r_bear = run_l3_judgment_pipeline(
        bearish,
        author_call_fn=make_author_call_fn(
            make_author_json(
                subject_guid=SUBJECT_B,
                stance="BEARISH",
                claim="BBB deteriorating on guidance cut",
                memory_fact_ids=[FACT_B1],
            )
        ),
        critic_call_fn=make_critic_call_fn(verdict="accept"),
        now=OFFPEAK_SUMMER_ET,
    )
    assert r_bull.ok and r_bear.ok
    stance_a = r_bull.author["stance"]
    stance_b = r_bear.author["stance"]
    assert stance_a != stance_b
    assert stance_a == "BULLISH"
    assert stance_b == "BEARISH"
    # AgentView mapped stances also differ (RECOMMEND vs DISPUTE)
    assert r_bull.agent_view["stance"] != r_bear.agent_view["stance"]


def test_same_provider_critic_fails_closed():
    from scripts.lib.model_policy import L3ModelPolicy

    policy = L3ModelPolicy(
        author_provider="deepseek",
        author_model_id="deepseek-flash",
        critic_provider="deepseek",
        critic_model="deepseek-flash",
    )
    critic_calls: list[int] = []
    result = run_l3_judgment_pipeline(
        make_grounded_input(),
        policy=policy,
        author_call_fn=make_author_call_fn(),
        critic_call_fn=make_critic_call_fn(counter=critic_calls),
        now=OFFPEAK_SUMMER_ET,
    )
    assert result.ok is False
    assert result.commitment is None
    assert critic_calls == []  # collision before call
    assert result.critique is not None
    assert result.critique.get("provider_calls") == 0


def test_critic_revise_named_field_preserved():
    result = run_l3_judgment_pipeline(
        make_grounded_input(),
        author_call_fn=make_author_call_fn(make_author_json(confidence=0.8)),
        critic_call_fn=make_critic_call_fn(
            verdict="revise",
            field_changes=[{"field": "confidence", "before": 0.8, "after": 0.55}],
        ),
        now=OFFPEAK_SUMMER_ET,
    )
    assert result.ok is True
    assert result.critique["verdict"] == "revise"
    ch = result.critique["field_changes"][0]
    assert ch["field"] == "confidence"
    assert ch["before"] == 0.8
    assert ch["after"] == 0.55
    assert result.output["critic"]["verdict"] == "changed"
    assert result.output["critic"]["field_named"] == "confidence"


def test_provider_timeout_retry_idempotent_judgment_rows():
    durable: list = []
    author_fn = make_author_call_fn()
    critic_fn = make_critic_call_fn()
    r1 = run_l3_judgment_pipeline(
        make_grounded_input(),
        author_call_fn=author_fn,
        critic_call_fn=critic_fn,
        now=OFFPEAK_SUMMER_ET,
        persist_rows=durable,
    )
    assert r1.ok
    jid = r1.author["judgment_id"]
    # Simulate retry with same durable list / same judgment_id
    r2 = run_l3_judgment_pipeline(
        make_grounded_input(),
        author_call_fn=author_fn,
        critic_call_fn=critic_fn,
        now=OFFPEAK_SUMMER_ET,
        persist_rows=durable,
    )
    assert r2.ok
    assert r2.author["judgment_id"] == jid
    judgment_rows = [
        r
        for r in durable
        if r.get("kind") == "judgment" and (r.get("body") or {}).get("author", {}).get("judgment_id") == jid
    ]
    assert len(judgment_rows) == 1


def test_cache_hit_in_pipeline_reduces_author_calls():
    cache = JudgmentCache()
    author_calls: list[int] = []
    fn = make_author_call_fn(counter=author_calls)
    r1 = run_l3_judgment_pipeline(
        make_grounded_input(),
        cache=cache,
        author_call_fn=fn,
        critic_call_fn=make_critic_call_fn(),
        now=OFFPEAK_SUMMER_ET,
    )
    r2 = run_l3_judgment_pipeline(
        make_grounded_input(),
        cache=cache,
        author_call_fn=fn,
        critic_call_fn=make_critic_call_fn(),
        now=OFFPEAK_SUMMER_ET,
    )
    assert r1.ok and r2.ok
    assert r1.author["cache_hit"] is False
    assert r2.author["cache_hit"] is True
    assert len(author_calls) == 1
    assert r2.author["provider_calls"] == 0
