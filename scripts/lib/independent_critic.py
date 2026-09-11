"""C3 — independent reflective critique (different provider from author).

The critic receives structured evidence references and author output — not
secrets or raw prompts. Author must never score itself. Same-provider critique
fails closed before any call.

Verdicts: accept | revise | abstain | reject.
Revise must name field changes with before/after. Persist both values.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from scripts.lib.judgment_schema import (
    CRITIC_PROVIDER_COLLISION,
    MODEL_UNAVAILABLE,
    PROVIDER_OUTAGE,
    QUARANTINED,
    SCHEMA_CRITIQUE,
    SCHEMA_INVALID,
    JudgmentSchemaError,
    digest_obj,
    validate_critique,
)
from scripts.lib.model_policy import (
    L3ModelPolicy,
    assert_critic_provider_separated,
    default_l3_policy,
)

CriticCallFn = Callable[..., Any]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _mint_critique_id(judgment_id: str, critic_provider: str, input_digest: str) -> str:
    digest = hashlib.sha256(f"{judgment_id}|{critic_provider}|{input_digest}".encode()).hexdigest()
    return f"crt_{digest[:24]}"


def build_critic_request(
    *,
    grounded: Mapping[str, Any],
    author: Mapping[str, Any],
) -> dict[str, Any]:
    """Evidence references + author output only — no API secrets, no raw prompts."""
    facts = []
    for fact in grounded.get("memory_facts") or []:
        if not isinstance(fact, Mapping):
            continue
        mid = str(fact.get("memory_fact_id") or "")
        if mid not in set(str(x) for x in (author.get("memory_fact_ids") or [])):
            continue
        facts.append(
            {
                "memory_fact_id": mid,
                "fact_digest": fact.get("fact_digest"),
                "age_hours": fact.get("age_hours"),
                "decay_weight": fact.get("decay_weight"),
                "contradiction": fact.get("contradiction"),
            }
        )
    return {
        "schema": "L3CriticRequest@v1",
        "judgment_id": author.get("judgment_id"),
        "subject_guid": author.get("subject_guid"),
        "question": author.get("question"),
        "author": {
            "provider": author.get("provider"),
            "requested_model": author.get("requested_model"),
            "returned_model": author.get("returned_model"),
            "stance": author.get("stance"),
            "claim": author.get("claim"),
            "confidence": author.get("confidence"),
            "falsifier": author.get("falsifier"),
            "horizon": author.get("horizon"),
            "assumptions": author.get("assumptions"),
            "uncertainties": author.get("uncertainties"),
            "next_research_question": author.get("next_research_question"),
            "evidence_source_ids": author.get("evidence_source_ids"),
            "memory_fact_ids": author.get("memory_fact_ids"),
            "research_object_ids": author.get("research_object_ids"),
            "input_digest": author.get("input_digest"),
            "output_digest": author.get("output_digest"),
        },
        "evidence_refs": facts,
        "research_object_ids": list((grounded.get("research") or {}).get("research_object_ids") or []),
        "instructions": {
            "verdicts": ["accept", "revise", "abstain", "reject"],
            "revise_requires_named_field_before_after": True,
            "no_self_author_provider": True,
            "mbi_behavior": 0,
        },
    }


def _default_critic_call(*, provider: str, model: str, prompt: str, **_: Any) -> dict[str, Any]:
    """Call a non-DeepSeek provider via llm_lane.generate when available."""
    from scripts.llm_lane import generate

    text = generate(
        prompt,
        lane=provider,
        model=model,
        process_id="l3_independent_critic",
        task_summary="l3_independent_critic",
    )
    return {
        "ok": True,
        "content": text if isinstance(text, str) else json.dumps(text),
        "provider": provider,
        "model_returned": model,
        "cost_usd": 0.0,
        "latency_ms": 0,
    }


def apply_field_changes(author: Mapping[str, Any], critique: Mapping[str, Any]) -> dict[str, Any]:
    """Return revised author view after critique (before/after preserved on critique)."""
    revised = dict(author)
    for change in critique.get("field_changes") or []:
        if not isinstance(change, Mapping):
            continue
        field = str(change.get("field") or "")
        if not field:
            continue
        if "after" in change:
            revised[field] = change["after"]
    revised["critique_id"] = critique.get("critique_id")
    revised["critic_verdict"] = critique.get("verdict")
    return revised


def run_independent_critic(
    *,
    grounded: Mapping[str, Any],
    author: Mapping[str, Any],
    policy: L3ModelPolicy | None = None,
    call_fn: CriticCallFn | None = None,
    critic_provider: str | None = None,
    critic_model: str | None = None,
) -> dict[str, Any]:
    policy = policy or default_l3_policy()
    author_provider = str(author.get("provider") or policy.author_provider)
    provider = (critic_provider or policy.critic_provider).strip().lower()
    model = critic_model or policy.critic_model

    try:
        assert_critic_provider_separated(author_provider, provider)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "refusal_state": CRITIC_PROVIDER_COLLISION,
            "reasons": [str(exc)],
            "provider_calls": 0,
        }

    request = build_critic_request(grounded=grounded, author=author)
    input_digest = digest_obj(request)
    prompt = (
        "You are an independent L3 critic. Author provider is "
        f"{author_provider}. You MUST use a different provider. "
        "Return JSON L3Critique@v1 with verdict accept|revise|abstain|reject. "
        "If revise, include field_changes[{field,before,after}].\n\n" + json.dumps(request, sort_keys=True, default=str)
    )

    caller = call_fn or _default_critic_call
    t0 = time.perf_counter()
    try:
        raw = caller(provider=provider, model=model, prompt=prompt, request=request)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "refusal_state": PROVIDER_OUTAGE,
            "reasons": [f"critic_call_exception:{type(exc).__name__}"],
            "provider_calls": 1,
        }
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if isinstance(raw, Mapping) and raw.get("ok") is False:
        return {
            "ok": False,
            "refusal_state": MODEL_UNAVAILABLE,
            "reasons": [str(raw.get("error") or "critic_failed")],
            "provider_calls": 1,
            "latency_ms": latency_ms,
        }

    content = raw.get("content") if isinstance(raw, Mapping) else raw
    returned_provider = str((raw.get("provider") if isinstance(raw, Mapping) else None) or provider).lower()
    returned_model = str((raw.get("model_returned") if isinstance(raw, Mapping) else None) or model)
    cost = float((raw.get("cost_usd") if isinstance(raw, Mapping) else 0.0) or 0.0)

    # Independence proof: providers differ and critic did not use author model path.
    independence_proof = {
        "author_provider": author_provider,
        "critic_provider": returned_provider,
        "providers_differ": author_provider != returned_provider,
        "author_judgment_id": author.get("judgment_id"),
        "critic_request_digest": input_digest,
        "proof_id": str(uuid.uuid4()),
    }
    if not independence_proof["providers_differ"]:
        return {
            "ok": False,
            "refusal_state": CRITIC_PROVIDER_COLLISION,
            "reasons": ["critic_returned_author_provider"],
            "provider_calls": 1,
            "independence_proof": independence_proof,
        }

    try:
        parsed = json.loads(content) if isinstance(content, str) else content
        if not isinstance(parsed, dict):
            raise JudgmentSchemaError("critic_content_not_object")
    except (json.JSONDecodeError, JudgmentSchemaError) as exc:
        return {
            "ok": False,
            "refusal_state": SCHEMA_INVALID,
            "reasons": [f"critic_parse:{exc}"],
            "provider_calls": 1,
            "latency_ms": latency_ms,
        }

    critique_id = _mint_critique_id(str(author.get("judgment_id") or ""), returned_provider, input_digest)
    envelope = {
        **parsed,
        "critique_id": parsed.get("critique_id") or critique_id,
        "provider": returned_provider,
        "model_returned": returned_model,
        "cost_usd": cost,
        "latency_ms": int((raw.get("latency_ms") if isinstance(raw, Mapping) else None) or latency_ms),
        "author_provider": author_provider,
        "independence_proof": independence_proof,
        "schema_version": SCHEMA_CRITIQUE,
        "input_digest": input_digest,
        "produced_at": _now_iso(),
        "provider_calls": 1,
        "contradictions": list(parsed.get("contradictions") or []),
        "unsupported_claims": list(parsed.get("unsupported_claims") or []),
        "field_changes": list(parsed.get("field_changes") or []),
        "mbi_behavior": 0,
    }
    if envelope.get("verdict") == "revise" and parsed.get("revised_next_research_question"):
        # Ensure next question revision is a named field change when warranted.
        changes = list(envelope["field_changes"])
        if not any(isinstance(c, Mapping) and c.get("field") == "next_research_question" for c in changes):
            changes.append(
                {
                    "field": "next_research_question",
                    "before": author.get("next_research_question"),
                    "after": parsed.get("revised_next_research_question"),
                }
            )
            envelope["field_changes"] = changes

    try:
        validated = validate_critique(envelope, author_provider=author_provider)
    except JudgmentSchemaError as exc:
        return {
            "ok": False,
            "refusal_state": QUARANTINED,
            "reasons": [str(exc)],
            "provider_calls": 1,
            "latency_ms": latency_ms,
        }

    validated["ok"] = True
    validated["provider_calls"] = 1
    validated["revised_author"] = apply_field_changes(author, validated)
    return validated
