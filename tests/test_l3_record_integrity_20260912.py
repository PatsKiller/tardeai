"""Negative controls for L3 durable judgment record integrity.

Every test here reproduces a defect observed in PRODUCTION wake evidence on
2026-09-11 (state root /home/johnclaw/trade-ai-state/persistent_wake/state).
Each must FAIL against the pre-fix source; that is the point of the file.

Observed evidence, five organic JUDGED wakes 15:00Z-19:00Z:

    cost_usd      0.0     on every record, for real 2.3-3.8s paid calls
    prompt_digest null    on every record
    release       ''      on every record
    judgment_id   jdg_97ab0292bcd3339e76c474c2  on ALL FIVE, while
                  output_digest differed on all five, and views.jsonl holds
                  two views an hour apart with confidence 0.72 and 0.60,
                  different falsifiers, different critique_ids -- and that
                  one shared judgment_id.
    cache_key     different on all five, so the cache never hit and every
                  hourly wake paid for a fresh call, even though
                  input_digest was IDENTICAL on all five.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from scripts.lib.l3_judgment_author import build_author_prompt, run_author
from scripts.lib.l3_judgment_cache import evidence_revision_token
from scripts.lib.model_policy import default_l3_policy
from tests.helpers.l3_fixtures import (
    FACT_A1,
    SUBJECT_A,
    make_author_json,
    make_fact,
    make_grounded_input,
)


# ---------------------------------------------------------------------------
# A response object shaped like the REAL scripts.lib.deepseek_client response.
#
# The existing helper `mock_author_response` sets `resp.cost_usd`, an attribute
# DeepSeekResponse does not define. That fixture drift is exactly why the cost
# defect survived: the mock answered a question the production client is never
# asked. Model the real dataclass field names instead.
# ---------------------------------------------------------------------------
@dataclass
class RealShapedResponse:
    ok: bool = True
    requested_model_id: str | None = "deepseek-flash"
    returned_model: str | None = "deepseek-flash"
    content: str | None = None
    error_class: str | None = None
    error_message: str | None = None
    latency_ms: int | None = 2600
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 900, "completion_tokens": 220})
    estimated_cost_usd: float | None = 0.00031
    cost_basis: str | None = "measured_tokens_x_price_schedule"
    pricing_tier: str | None = "off_peak"
    cache_hit: bool | None = False
    request_id: str | None = "req-abc123"


def _gin():
    return make_grounded_input()


def _gate(gin):
    return {
        "material_question": (gin["material_residual_question"] or {})["question_text"],
        "selected_memory_fact_ids": [FACT_A1],
        "state": "PROCEED",
    }


def _call_fn(payload, *, cost=0.00031):
    def _c(**_kw):
        return RealShapedResponse(content=json.dumps(payload), estimated_cost_usd=cost)

    return _c


def test_cost_usd_reflects_real_client_cost_field():
    """DEFECT: _extract_response reads `cost_usd`; the client returns
    `estimated_cost_usd`. Every paid L3 call therefore records $0.00, so the
    L3 lane is invisible to every cost report and every budget decision."""
    gin = _gin()
    out = run_author(
        grounded=gin, gate=_gate(gin), call_fn=_call_fn(make_author_json()), source_sha="deadbeef"
    )
    assert out.get("ok") is True, out
    assert out["cost_usd"] == pytest.approx(0.00031), (
        f"paid call recorded cost_usd={out['cost_usd']!r}; real client reported "
        "estimated_cost_usd=0.00031"
    )


def test_prompt_digest_is_persisted():
    """DEFECT: the wake reads provenance.llm.prompt_digest, but run_author
    never sets it, so the prompt is not bound to the record at all. The brief
    requires immutable prompt AND input digests; only input_digest exists."""
    gin = _gin()
    out = run_author(
        grounded=gin, gate=_gate(gin), call_fn=_call_fn(make_author_json()), source_sha="deadbeef"
    )
    assert out.get("prompt_digest"), "author judgment carries no prompt_digest"
    assert str(out["prompt_digest"]).startswith("sha256:")
    assert out["prompt_digest"] != out["input_digest"], (
        "prompt_digest must digest the prompt actually sent, which includes "
        "decay_weight and fact_text; input_digest deliberately excludes both"
    )


def test_judgment_id_is_unique_per_judgment_not_per_input():
    """DEFECT: judgment_id = H(subject, question, input_digest). input_digest
    excludes decay_weight and fact_text, so it is stable hour over hour. Five
    organic judgments with five different output_digests shared ONE id, and
    two persisted views an hour apart carry that id with different confidence
    (0.72 vs 0.60) and different falsifiers. A consumer joining a view to its
    judgment by judgment_id gets an ambiguous N-row match."""
    gin = _gin()
    gate = _gate(gin)
    first = run_author(
        grounded=gin,
        gate=gate,
        call_fn=_call_fn(make_author_json(claim="AAA thesis holds on the cited filing.")),
        source_sha="deadbeef",
    )
    second = run_author(
        grounded=gin,
        gate=gate,
        call_fn=_call_fn(
            make_author_json(
                claim="AAA thesis is now unsupported by the cited filing.",
                confidence=0.41,
                falsifier="Next 10-Q shows sequential revenue growth.",
            )
        ),
        source_sha="deadbeef",
    )
    assert first["ok"] and second["ok"]
    assert first["output_digest"] != second["output_digest"], "fixture must differ"
    assert first["judgment_id"] != second["judgment_id"], (
        "two judgments with different content share judgment_id "
        f"{first['judgment_id']}; the id is not an identifier"
    )


def test_input_digest_stays_stable_when_only_decay_weight_drifts():
    """Guard rail for the fix above: input_digest must remain the evidence
    identity. If a future change folds output into input_digest, the cache and
    the judgment id would both key on the answer, which is circular."""
    gin_a = _gin()
    gin_b = _gin()
    gin_b["memory_facts"][0]["decay_weight"] = 0.79994
    policy = default_l3_policy()
    _, digest_a = build_author_prompt(grounded=gin_a, gate=_gate(gin_a), policy=policy)
    _, digest_b = build_author_prompt(grounded=gin_b, gate=_gate(gin_b), policy=policy)
    assert digest_a == digest_b


def test_cache_does_not_invalidate_on_continuous_decay_drift():
    """DEFECT: evidence_revision_token embeds raw decay_weight, a continuous
    function of elapsed time. Every hourly wake produced a different cache key
    on UNCHANGED evidence -- five keys, five paid calls, zero hits -- while
    input_digest proved the evidence identity had not moved. The cache was
    pure write amplification, and the spend it failed to avoid is what
    exhausted the global budget and starved the lane from 20:00Z."""
    fact_now = make_fact(
        memory_fact_id=FACT_A1, subject_guid=SUBJECT_A, fact_text="x", decay_weight=0.403816
    )
    fact_hour_later = make_fact(
        memory_fact_id=FACT_A1, subject_guid=SUBJECT_A, fact_text="x", decay_weight=0.403712
    )
    gin_now = make_grounded_input(facts=[fact_now])
    gin_later = make_grounded_input(facts=[fact_hour_later])
    tok_now = evidence_revision_token(gin_now, [FACT_A1])
    tok_later = evidence_revision_token(gin_later, [FACT_A1])
    assert tok_now == tok_later, (
        "evidence revision changed on decay drift of 0.0001 with identical "
        "fact digests; the cache can never hit on an hourly schedule"
    )


def test_cache_still_invalidates_on_material_decay_change():
    """The fix must not blind the cache. A weight that has genuinely moved
    must still invalidate, or stale judgments would outlive their evidence."""
    fresh = make_fact(
        memory_fact_id=FACT_A1, subject_guid=SUBJECT_A, fact_text="x", decay_weight=0.81
    )
    decayed = make_fact(
        memory_fact_id=FACT_A1, subject_guid=SUBJECT_A, fact_text="x", decay_weight=0.32
    )
    tok_fresh = evidence_revision_token(make_grounded_input(facts=[fresh]), [FACT_A1])
    tok_decayed = evidence_revision_token(make_grounded_input(facts=[decayed]), [FACT_A1])
    assert tok_fresh != tok_decayed


def test_cache_invalidates_when_fact_content_changes():
    """Digest change must always invalidate regardless of weight quantization."""
    a = make_fact(memory_fact_id=FACT_A1, subject_guid=SUBJECT_A, fact_text="x", decay_weight=0.8)
    b = make_fact(memory_fact_id=FACT_A1, subject_guid=SUBJECT_A, fact_text="x", decay_weight=0.8)
    b["fact_digest"] = "sha256:completely-different"
    tok_a = evidence_revision_token(make_grounded_input(facts=[a]), [FACT_A1])
    tok_b = evidence_revision_token(make_grounded_input(facts=[b]), [FACT_A1])
    assert tok_a != tok_b


def test_release_is_persisted_on_the_judgment():
    """DEFECT: every organic judgment recorded release=''. The brief requires
    provider, model, cost, latency, trigger, subject, SHA, release and epoch on
    the durable record."""
    gin = _gin()
    out = run_author(
        grounded=gin,
        gate=_gate(gin),
        call_fn=_call_fn(make_author_json()),
        source_sha="deadbeef",
        release="eb648174a-main-exact-phase2-20260911-180637",
    )
    assert out["release"] == "eb648174a-main-exact-phase2-20260911-180637"


def test_wake_provenance_records_epoch_and_release():
    """DEFECT: wake provenance was built with no epoch_id and no release key,
    so `release=str(wake["provenance"].get("release") or "")` at the L3 call
    site could only ever pass the empty string. Every organic judgment on
    2026-09-11 recorded release=''."""
    import inspect

    from scripts.lib import persistent_agent_wake as paw

    src = inspect.getsource(paw)
    assert '"release": resolve_release_id()' in src
    assert '"epoch_id": resolve_epoch_id(env)' in src
    assert callable(paw.resolve_release_id)


def test_release_and_epoch_are_separate_identities():
    """resolve_epoch_id honours TRADEAI_EPOCH_ID; resolve_release_id must not.
    Collapsing them would let a campaign rename the served release in the
    audit record."""
    from scripts.lib.persistent_agent_wake import resolve_epoch_id, resolve_release_id

    named = resolve_epoch_id({"TRADEAI_EPOCH_ID": "campaign-named-epoch"})
    assert named == "campaign-named-epoch"
    assert resolve_release_id() != "campaign-named-epoch"


def test_model_cannot_mint_its_own_judgment_id():
    """DEFECT: the envelope honoured parsed["judgment_id"] when the model
    supplied one, defeating the stated rule that envelope provenance is filled
    by the caller so the model cannot invent it."""
    gin = _gin()
    payload = make_author_json()
    payload["judgment_id"] = "jdg_attacker_supplied_value"
    out = run_author(
        grounded=gin, gate=_gate(gin), call_fn=_call_fn(payload), source_sha="deadbeef"
    )
    assert out["ok"] is True
    assert out["judgment_id"] != "jdg_attacker_supplied_value"
    assert out["judgment_id"].startswith("jdg_")


def test_cost_basis_and_pricing_tier_reach_the_record():
    """Cost without its basis is an unfalsifiable number. The real client
    reports how it priced the call; the record must keep that."""
    gin = _gin()
    out = run_author(
        grounded=gin, gate=_gate(gin), call_fn=_call_fn(make_author_json()), source_sha="deadbeef"
    )
    assert out["cost_basis"] == "measured_tokens_x_price_schedule"
    assert out["pricing_tier"] == "off_peak"
