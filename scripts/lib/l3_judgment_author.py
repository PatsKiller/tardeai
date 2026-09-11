"""C2 — DeepSeek Flash L3 judgment author.

Routes eligible calls through exact model registry identity. Validates the
*returned* model ID. Structured output with full provenance. Caching before
time-of-day savings. Never invents numbers or omits falsifier/evidence IDs.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from scripts.lib.judgment_schema import (
    MODEL_MISMATCH,
    MODEL_UNAVAILABLE,
    PROMPT_TEMPLATE_VERSION,
    PROVIDER_OUTAGE,
    QUARANTINED,
    SCHEMA_AUTHOR,
    SCHEMA_INVALID,
    JudgmentSchemaError,
    digest_obj,
    digest_text,
    validate_author_judgment,
)
from scripts.lib.l3_judgment_cache import (
    CacheEntry,
    JudgmentCache,
    build_cache_key,
    evidence_revision_token,
)
from scripts.lib.model_policy import (
    L3ModelPolicy,
    default_l3_policy,
    evaluate_offpeak_eligibility,
    forbid_local_author_substitute,
    resolve_author_model,
    validate_returned_model,
)

AuthorCallFn = Callable[..., Any]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _mint_judgment_id(subject_guid: str, question: str, input_digest: str) -> str:
    digest = hashlib.sha256(f"{subject_guid}|{question}|{input_digest}".encode()).hexdigest()
    return f"jdg_{digest[:24]}"


#: The subset of L3AuthorJudgment@v1 the MODEL must supply. The remaining
#: required fields (judgment_id, provider, requested_model, returned_model,
#: prompt_template_version, input_digest, ...) are envelope fields the caller
#: fills after the response returns — asking the model for them would invite it
#: to invent its own provenance.
MODEL_SUPPLIED_FIELDS = (
    "stance",
    "claim",
    "confidence",
    "assumptions",
    "uncertainties",
    "falsifier",
    "horizon",
    "next_research_question",
    "memory_fact_ids",
    "evidence_source_ids",
    "research_object_ids",
)

def build_author_prompt(
    *,
    grounded: Mapping[str, Any],
    gate: Mapping[str, Any],
    policy: L3ModelPolicy,
) -> tuple[str, str]:
    """Return (prompt_text, input_digest). Prompt itself is not persisted — digest only."""
    subject = grounded.get("subject") or {}
    facts = []
    wanted = set(gate.get("selected_memory_fact_ids") or [])
    for fact in grounded.get("memory_facts") or []:
        if not isinstance(fact, Mapping):
            continue
        mid = str(fact.get("memory_fact_id") or "")
        if wanted and mid not in wanted:
            continue
        facts.append(
            {
                "memory_fact_id": mid,
                "fact_digest": fact.get("fact_digest"),
                "age_hours": fact.get("age_hours"),
                "decay_weight": fact.get("decay_weight"),
                "contradiction": fact.get("contradiction"),
                # fact_text is for the model call only; digest stored in evidence
                "fact_text": fact.get("fact_text"),
            }
        )
    research = grounded.get("research") or {}
    payload = {
        "subject_guid": subject.get("subject_guid"),
        "symbol": subject.get("symbol"),
        "question": gate.get("material_question"),
        "memory_facts": facts,
        "research_object_ids": list(research.get("research_object_ids") or []),
        "retrieval": grounded.get("retrieval"),
        "why_unresolved": (grounded.get("material_residual_question") or {}).get("why_unresolved_by_research"),
        "instructions": {
            "stance_enum": sorted(
                [
                    "RECOMMEND",
                    "DISPUTE",
                    "ABSTAIN",
                    "BEARISH",
                    "BULLISH",
                    "NEUTRAL",
                    "INSUFFICIENT",
                ]
            ),
            "require_falsifier": True,
            "require_evidence_ids": True,
            "no_invented_numbers": True,
            "no_trade_instructions": True,
            "mbi_behavior": 0,
            "output_schema": SCHEMA_AUTHOR,
            # The model cannot see SCHEMA_AUTHOR — it is only a version STRING.
            # Measured 2026-09-11: naming the schema without listing its fields
            # produced a well-formed JSON object that omitted claim, assumptions,
            # uncertainties, horizon and next_research_question, so every organic
            # attempt quarantined as schema_invalid. Ask for the fields by name.
            "required_fields": list(MODEL_SUPPLIED_FIELDS),
            "field_notes": {
                "stance": "one of stance_enum",
                "claim": "one sentence, falsifiable, no numbers you were not given",
                "confidence": "float 0.0-1.0",
                "assumptions": "list of strings; [] if none",
                "uncertainties": "list of strings; [] if none",
                "falsifier": "the concrete observation that would prove this claim wrong",
                "horizon": "e.g. 14d",
                "next_research_question": "the question to ask next",
                "memory_fact_ids": "cite ONLY ids present in memory_facts above",
                "evidence_source_ids": "ids you actually used",
                "research_object_ids": "echo the ids given above",
            },
        },
    }
    prompt = (
        "You are the Trade AI L3 judgment author (DeepSeek Flash). "
        "Return a single JSON object matching L3AuthorJudgment@v1. "
        "Beliefs/advice only — never orders, sizes, or broker actions.\n\n"
        + json.dumps(payload, sort_keys=True, default=str)
    )
    # Digest excludes raw fact_text to avoid storing sensitive source text in evidence.
    digest_payload = {
        "subject_guid": subject.get("subject_guid"),
        "question": gate.get("material_question"),
        "memory_fact_ids": sorted(wanted),
        "fact_digests": sorted(str(f.get("fact_digest") or "") for f in facts),
        "research_object_ids": sorted(str(x) for x in (research.get("research_object_ids") or [])),
        "prompt_template_version": policy.prompt_template_version or PROMPT_TEMPLATE_VERSION,
    }
    return prompt, digest_obj(digest_payload)




def _default_deepseek_call(**kwargs: Any) -> Any:
    from scripts.lib.deepseek_client import chat

    return chat(**kwargs)


def _extract_response(resp: Any) -> dict[str, Any]:
    """Normalize DeepSeekResponse or mapping/mock into a dict."""
    if hasattr(resp, "ok"):
        return {
            "ok": bool(resp.ok),
            "content": getattr(resp, "content", None),
            "requested_model_id": getattr(resp, "requested_model_id", None),
            "returned_model": getattr(resp, "returned_model", None),
            "error_class": getattr(resp, "error_class", None),
            "error_message": getattr(resp, "error_message", None),
            "latency_ms": getattr(resp, "latency_ms", None),
            "cost_usd": getattr(resp, "cost_usd", None),
            "usage": getattr(resp, "usage", None),
        }
    if isinstance(resp, Mapping):
        return dict(resp)
    raise JudgmentSchemaError("author_response_unrecognized")


def run_author(
    *,
    grounded: Mapping[str, Any],
    gate: Mapping[str, Any],
    policy: L3ModelPolicy | None = None,
    cache: JudgmentCache | None = None,
    call_fn: AuthorCallFn | None = None,
    source_sha: str = "",
    release: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Execute author path. Returns author judgment dict or refusal-shaped error dict.

    Refusal-shaped dict uses keys: ok=False, refusal_state, reasons, provider_calls.
    """
    policy = policy or default_l3_policy()
    forbid_local_author_substitute(policy.author_provider, policy=policy)
    binding = resolve_author_model(policy)
    subject = grounded.get("subject") or {}
    subject_guid = str(subject.get("subject_guid") or "")
    question = str(gate.get("material_question") or "")
    mem_ids = [str(x) for x in (gate.get("selected_memory_fact_ids") or [])]

    prompt, input_digest = build_author_prompt(grounded=grounded, gate=gate, policy=policy)
    cache_key = build_cache_key(
        subject_guid=subject_guid,
        material_question=question,
        grounded=grounded,
        memory_fact_ids=mem_ids,
        policy=policy,
    )
    evid_rev = evidence_revision_token(grounded, mem_ids)

    if cache is not None:
        hit = cache.get(cache_key, subject_guid=subject_guid, evidence_revision=evid_rev)
        if hit is not None:
            judgment = dict(hit.author_judgment)
            judgment["cache_key"] = cache_key
            judgment["cache_hit"] = True
            judgment["provider_calls"] = 0
            judgment["ok"] = True
            return judgment

    when = now or datetime.now(timezone.utc)
    offpeak = evaluate_offpeak_eligibility(when, policy=policy)
    caller = call_fn or _default_deepseek_call
    t0 = time.perf_counter()
    try:
        raw_resp = caller(
            policy=binding["logical_policy"],
            prompt=prompt,
            response_json=True,
            max_tokens=2048,
            source_service="l3_judgment",
            source_process="l3_judgment_author",
            source_lane="GROK_C",
            agent="l3_author",
            run_id=str(uuid.uuid4()),
        )
    except Exception as exc:  # noqa: BLE001 — map to durable unavailable
        return {
            "ok": False,
            "refusal_state": PROVIDER_OUTAGE,
            "reasons": [f"author_call_exception:{type(exc).__name__}"],
            "provider_calls": 1,
            "cache_key": cache_key,
            "cache_hit": False,
        }

    latency_ms = int((time.perf_counter() - t0) * 1000)
    resp = _extract_response(raw_resp)
    if not resp.get("ok"):
        err = str(resp.get("error_class") or "")
        state = MODEL_UNAVAILABLE
        if "CAP" in err.upper() or "BUDGET" in err.upper():
            from scripts.lib.judgment_schema import CAP_REFUSED

            state = CAP_REFUSED
        elif "AUTH" in err.upper():
            # Auth failures are provider outages for L3, not schema errors.
            # Measured 2026-09-11: mis-mapping here made organic wakes look like
            # schema_invalid when the real issue was environment/credentials.
            state = PROVIDER_OUTAGE
        return {
            "ok": False,
            "refusal_state": state,
            "reasons": [err or str(resp.get("error_message") or "author_failed")],
            "provider_calls": 1,
            "cache_key": cache_key,
            "cache_hit": False,
            "latency_ms": latency_ms,
        }

    requested = str(resp.get("requested_model_id") or binding["model_id"])
    returned = resp.get("returned_model")
    try:
        validate_returned_model(
            requested_model=requested,
            returned_model=str(returned) if returned is not None else None,
            provider=binding["provider"],
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "refusal_state": MODEL_MISMATCH,
            "reasons": [str(exc)],
            "provider_calls": 1,
            "requested_model": requested,
            "returned_model": returned,
            "cache_key": cache_key,
            "cache_hit": False,
            "latency_ms": latency_ms,
        }

    content = resp.get("content")
    # Fill required envelope fields before schema validate.
    try:
        parsed = json.loads(content) if isinstance(content, str) else content
        if not isinstance(parsed, dict):
            raise JudgmentSchemaError("author_content_not_object")
    except (json.JSONDecodeError, JudgmentSchemaError) as exc:
        return {
            "ok": False,
            "refusal_state": SCHEMA_INVALID,
            "reasons": [f"author_parse:{exc}"],
            "provider_calls": 1,
            "cache_key": cache_key,
            "cache_hit": False,
            "latency_ms": latency_ms,
        }

    research = grounded.get("research") or {}
    judgment_id = _mint_judgment_id(subject_guid, question, input_digest)
    output_digest = digest_text(content if isinstance(content, str) else json.dumps(content, sort_keys=True))
    # Do not silently replace empty evidence lists — empty means schema failure.
    if "memory_fact_ids" in parsed:
        memory_fact_ids = parsed.get("memory_fact_ids")
    else:
        memory_fact_ids = mem_ids
    if "research_object_ids" in parsed:
        research_object_ids = parsed.get("research_object_ids")
    else:
        research_object_ids = list(research.get("research_object_ids") or [])
    if "evidence_source_ids" in parsed:
        evidence_source_ids = parsed.get("evidence_source_ids")
    else:
        evidence_source_ids = list(mem_ids)
    envelope = {
        **parsed,
        "judgment_id": parsed.get("judgment_id") or judgment_id,
        "subject_guid": subject_guid,
        "question": question,
        "provider": binding["provider"],
        "requested_model": requested,
        "returned_model": str(returned),
        "prompt_template_version": policy.prompt_template_version or PROMPT_TEMPLATE_VERSION,
        "input_digest": input_digest,
        "output_digest": output_digest,
        "cache_key": cache_key,
        "cache_hit": False,
        "cost_usd": float(resp.get("cost_usd") or 0.0),
        "latency_ms": int(resp.get("latency_ms") or latency_ms),
        "source_sha": source_sha or grounded.get("source_sha") or "",
        "release": release or "",
        "epoch_id": grounded.get("epoch_id") or "",
        "trigger": grounded.get("trigger") or "",
        "schema_version": SCHEMA_AUTHOR,
        "memory_fact_ids": memory_fact_ids,
        "research_object_ids": research_object_ids,
        "evidence_source_ids": evidence_source_ids,
        "off_peak": offpeak.eligible,
        "mbi_behavior": 0,
        "provider_calls": 1,
    }

    try:
        validated = validate_author_judgment(envelope, grounded=grounded)
    except JudgmentSchemaError as exc:
        return {
            "ok": False,
            "refusal_state": QUARANTINED,
            "reasons": [str(exc)],
            "provider_calls": 1,
            "cache_key": cache_key,
            "cache_hit": False,
            "latency_ms": latency_ms,
            "quarantine_digest": output_digest,
        }

    validated["ok"] = True
    validated["provider_calls"] = 1
    validated["produced_at"] = _now_iso()
    validated["confidence_calibration_caveat"] = validated.get("confidence_calibration_caveat") or (
        "confidence is model-elicited and uncalibrated until outcome settlement"
    )

    if cache is not None:
        cache.put(
            CacheEntry(
                cache_key=cache_key,
                subject_guid=subject_guid,
                created_at=_now_iso(),
                evidence_revision=evid_rev,
                author_judgment={k: v for k, v in validated.items() if k != "ok"},
                provider=binding["provider"],
                requested_model=requested,
                returned_model=str(returned),
                provenance={
                    "input_digest": input_digest,
                    "output_digest": output_digest,
                    "prompt_template_version": policy.prompt_template_version,
                },
            )
        )
    return validated
