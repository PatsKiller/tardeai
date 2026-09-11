"""Shared GroundedJudgmentInput@v1 fixtures for Lane C L3 tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# Off-peak / DST sample times.
OFFPEAK_SUMMER_ET = datetime(2026, 8, 15, 15, 0, tzinfo=ET)  # eligible bulk ET (EDT)
DEFERRED_SUMMER_ET = datetime(2026, 8, 15, 22, 0, tzinfo=ET)  # outside bulk ET
OFFPEAK_WINTER_ET = datetime(2026, 1, 15, 15, 0, tzinfo=ET)  # eligible bulk ET (EST)
OFFICIAL_PEAK_UTC = datetime(2026, 8, 17, 2, 0, tzinfo=UTC)  # weekday official peak


SUBJECT_A = "11111111-1111-4111-8111-111111111111"
SUBJECT_B = "22222222-2222-4222-8222-222222222222"
FACT_A1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
FACT_A2 = "aaaaaaaa-aaaa-4aaa-8aaa-bbbbbbbbbbbb"
FACT_B1 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def make_fact(
    *,
    memory_fact_id: str,
    subject_guid: str,
    fact_text: str,
    age_hours: float = 12.0,
    decay_weight: float = 0.8,
    contradiction_state: str = "none",
) -> dict[str, Any]:
    return {
        "memory_fact_id": memory_fact_id,
        "fact_text": fact_text,
        "fact_digest": f"sha256:digest-{memory_fact_id[:8]}",
        "observed_at_utc": "2026-09-10T12:00:00Z",
        "recorded_at_utc": "2026-09-10T12:05:00Z",
        "age_hours": age_hours,
        "decay_weight": decay_weight,
        "decay_model": "halflife_exp:336h",
        "provenance": {
            "source_kind": "durable_memory",
            "source_id": memory_fact_id,
            "source_sha": "aa43a8c9e61e963030fa15009c975f1de88da85a",
            "epoch_id": "l1l3-epoch-aa43a8c9e-main-exact-phase2-20260910-220559",
        },
        "contradiction": {"state": contradiction_state, "counterpart_fact_ids": []},
        "subject_guid": subject_guid,
    }


def make_grounded_input(
    *,
    subject_guid: str = SUBJECT_A,
    symbol: str = "AAA",
    facts: list[dict[str, Any]] | None = None,
    grounded: bool = True,
    free_first_exhausted: bool = True,
    residual_present: bool = True,
    question_text: str = "Does AAA's thesis still hold given the latest filing?",
    materiality_basis: str = "price_move_gt_threshold",
    resolution_confidence: float = 0.95,
    trigger: str = "scheduled",
    schedule_slot: str = "2026-09-11T10:00:00Z",
    research_object_ids: list[str] | None = None,
    filtered_wrong_subject: int = 0,
    as_of_utc: str = "2026-09-11T10:00:00Z",
    correlation_id: str = "corr-l3-test-0001",
) -> dict[str, Any]:
    if facts is None:
        facts = [
            make_fact(
                memory_fact_id=FACT_A1,
                subject_guid=subject_guid,
                fact_text=f"{symbol} reported sequential revenue growth and stable margins.",
            )
        ]
    return {
        "schema": "GroundedJudgmentInput@v1",
        "subject": {
            "subject_guid": subject_guid,
            "subject_kind": "security",
            "symbol": symbol,
            "resolved_by": "memory_subject_resolver@v1",
            "resolution_confidence": resolution_confidence,
        },
        "memory_facts": deepcopy(facts),
        "retrieval": {
            "candidates_considered": max(len(facts), 1),
            "returned": len(facts),
            "filtered_wrong_subject": filtered_wrong_subject,
            "filtered_below_floor": 0,
            "decay_weight_min": min((f["decay_weight"] for f in facts), default=0.0),
            "decay_weight_max": max((f["decay_weight"] for f in facts), default=0.0),
            "decay_weight_median": 0.8 if facts else 0.0,
            "oldest_returned_age_hours": max((f["age_hours"] for f in facts), default=0.0),
            "retrieval_latency_ms": 3,
            "cliff_applied": False,
        },
        "research": {
            "research_object_ids": list(research_object_ids or ["research-obj-1"]),
            "free_first_exhausted": free_first_exhausted,
            "effect_kind": "changed_question" if residual_present else "none",
        },
        "grounded": grounded,
        "material_residual_question": {
            "present": residual_present,
            "question_text": question_text if residual_present else None,
            "why_unresolved_by_research": "free lanes did not resolve material uncertainty"
            if residual_present
            else None,
            "materiality_basis": materiality_basis if residual_present else None,
        },
        "source_sha": "aa43a8c9e61e963030fa15009c975f1de88da85a",
        "epoch_id": "l1l3-epoch-aa43a8c9e-main-exact-phase2-20260910-220559",
        "schedule_slot": schedule_slot,
        "trigger": trigger,
        "correlation_id": correlation_id,
        "as_of_utc": as_of_utc,
    }


def make_author_json(
    *,
    subject_guid: str = SUBJECT_A,
    stance: str = "BULLISH",
    claim: str = "AAA thesis remains intact on the cited filing.",
    falsifier: str = "Next 10-Q shows sequential revenue decline.",
    memory_fact_ids: list[str] | None = None,
    confidence: float = 0.72,
) -> dict[str, Any]:
    mids = list(memory_fact_ids or [FACT_A1])
    return {
        "stance": stance,
        "claim": claim,
        "confidence": confidence,
        "evidence_source_ids": mids,
        "memory_fact_ids": mids,
        "research_object_ids": ["research-obj-1"],
        "assumptions": ["filing authenticity"],
        "uncertainties": ["macro demand"],
        "falsifier": falsifier,
        "horizon": "14d",
        "next_research_question": "What does channel check say about next quarter?",
    }


def mock_author_response(
    payload: dict[str, Any],
    *,
    returned_model: str = "deepseek-flash",
    ok: bool = True,
    error_class: str | None = None,
    error_message: str | None = None,
    cost_usd: float = 0.002,
):
    import json

    class Resp:
        pass

    resp = Resp()
    resp.ok = ok
    resp.content = json.dumps(payload) if ok else None
    resp.requested_model_id = "deepseek-flash"
    resp.returned_model = returned_model
    resp.error_class = error_class
    resp.error_message = error_message
    resp.latency_ms = 12
    resp.cost_usd = cost_usd
    return resp


def make_author_call_fn(
    payload: dict[str, Any] | None = None,
    *,
    returned_model: str = "deepseek-flash",
    ok: bool = True,
    error_class: str | None = None,
    raise_exc: BaseException | None = None,
    counter: list[int] | None = None,
):
    """Injectable author_call_fn for run_author / pipeline."""
    body = payload if payload is not None else make_author_json()

    def _call(**_kwargs: Any):
        if counter is not None:
            counter.append(1)
        if raise_exc is not None:
            raise raise_exc
        return mock_author_response(
            body,
            returned_model=returned_model,
            ok=ok,
            error_class=error_class,
            error_message=error_class,
        )

    return _call


def mock_critic_response(
    *,
    verdict: str = "accept",
    field_changes: list[dict[str, Any]] | None = None,
    provider: str = "grok",
    model: str = "grok-3-mini",
    cost_usd: float = 0.001,
) -> dict[str, Any]:
    import json

    body = {
        "verdict": verdict,
        "contradictions": [],
        "unsupported_claims": [],
        "field_changes": field_changes or [],
        "reason": f"critic_{verdict}",
        "summary": f"critic_{verdict}",
    }
    return {
        "ok": True,
        "content": json.dumps(body),
        "provider": provider,
        "model_returned": model,
        "cost_usd": cost_usd,
        "latency_ms": 8,
    }


def make_critic_call_fn(
    *,
    verdict: str = "accept",
    field_changes: list[dict[str, Any]] | None = None,
    force_returned_provider: str | None = None,
    model: str = "grok-3-mini",
    raise_exc: BaseException | None = None,
    counter: list[int] | None = None,
    raw_content: str | None = None,
):
    """Injectable critic_call_fn for run_independent_critic / pipeline."""

    def _call(*, provider: str = "grok", model: str = model, prompt: str = "", **_kw: Any):
        if counter is not None:
            counter.append(1)
        if raise_exc is not None:
            raise raise_exc
        use_provider = force_returned_provider or provider
        if raw_content is not None:
            return {
                "ok": True,
                "content": raw_content,
                "provider": use_provider,
                "model_returned": model,
                "cost_usd": 0.001,
                "latency_ms": 8,
            }
        return mock_critic_response(
            verdict=verdict,
            field_changes=field_changes,
            provider=use_provider,
            model=model,
        )

    return _call
