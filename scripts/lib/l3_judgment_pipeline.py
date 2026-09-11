"""L3 judgment pipeline — gate → author → critic → AgentView → commitment.

Library-side orchestration for Lane C. Lane A wires wake entrypoints via SFR.
Never reports a model judgment when no call occurred. MBI_BEHAVIOR=0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from scripts.lib.independent_critic import run_independent_critic
from scripts.lib.judgment_schema import (
    GATE_PROCEED,
    build_judgment_output,
    build_refusal_output,
)
from scripts.lib.l3_agent_view_synthesis import synthesize_agent_view, synthesize_commitment
from scripts.lib.l3_judgment_author import run_author
from scripts.lib.l3_judgment_cache import JudgmentCache
from scripts.lib.material_residual_gate import evaluate_material_residual_gate
from scripts.lib.model_policy import L3ModelPolicy, default_l3_policy

AuthorCallFn = Callable[..., Any]
CriticCallFn = Callable[..., Any]


@dataclass
class PipelineResult:
    output: dict[str, Any]
    gate: dict[str, Any]
    author: dict[str, Any] | None = None
    critique: dict[str, Any] | None = None
    agent_view: dict[str, Any] | None = None
    commitment: dict[str, Any] | None = None
    provider_calls: int = 0
    durable_rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.output.get("status") == "JUDGED"


def run_l3_judgment_pipeline(
    raw_input: Any,
    *,
    policy: L3ModelPolicy | None = None,
    cache: JudgmentCache | None = None,
    author_call_fn: AuthorCallFn | None = None,
    critic_call_fn: CriticCallFn | None = None,
    now: datetime | None = None,
    budget_remaining_usd: float | None = None,
    model_available: bool = True,
    lane_calls_remaining: int | None = None,
    request_cap_remaining: int | None = None,
    source_sha: str = "",
    release: str = "",
    served_sha: str = "",
    persist_rows: list[dict[str, Any]] | None = None,
) -> PipelineResult:
    """Full C1–C4 pipeline. Deterministic gates before any provider call."""
    policy = policy or default_l3_policy()
    when = now or datetime.now(timezone.utc)
    durable: list[dict[str, Any]] = persist_rows if persist_rows is not None else []

    gate = evaluate_material_residual_gate(
        raw_input,
        policy=policy,
        now=when,
        budget_remaining_usd=budget_remaining_usd,
        model_available=model_available,
        lane_calls_remaining=lane_calls_remaining,
        request_cap_remaining=request_cap_remaining,
    )
    gate_d = gate.to_dict()

    grounded = raw_input if isinstance(raw_input, Mapping) else {}
    # Re-validate only when proceeding; refusal path still echoes ids from raw.
    if not gate.proceed or gate.state != GATE_PROCEED:
        out = build_refusal_output(
            grounded=grounded if isinstance(grounded, Mapping) else {},
            gate_state=gate.state,
            reasons=gate.reasons,
            source_sha=source_sha or str((grounded or {}).get("source_sha") or ""),
            epoch_id=str((grounded or {}).get("epoch_id") or ""),
            schedule_slot=str((grounded or {}).get("schedule_slot") or ""),
            correlation_id=str((grounded or {}).get("correlation_id") or ""),
            provider_calls=0,
        )
        durable.append({"kind": "refusal", "body": out, "gate": gate_d})
        return PipelineResult(output=out, gate=gate_d, provider_calls=0, durable_rows=durable)

    from scripts.lib.judgment_schema import validate_grounded_input

    grounded_v = validate_grounded_input(raw_input)

    author = run_author(
        grounded=grounded_v,
        gate=gate_d,
        policy=policy,
        cache=cache,
        call_fn=author_call_fn,
        source_sha=source_sha or str(grounded_v.get("source_sha") or ""),
        release=release,
        now=when,
    )
    provider_calls = int(author.get("provider_calls") or 0)

    if not author.get("ok"):
        out = build_refusal_output(
            grounded=grounded_v,
            gate_state=str(author.get("refusal_state") or "SCHEMA_INVALID"),
            reasons=list(author.get("reasons") or []),
            source_sha=source_sha or str(grounded_v.get("source_sha") or ""),
            epoch_id=str(grounded_v.get("epoch_id") or ""),
            schedule_slot=str(grounded_v.get("schedule_slot") or ""),
            correlation_id=str(grounded_v.get("correlation_id") or ""),
            provider_calls=provider_calls,
        )
        durable.append({"kind": "refusal", "body": out, "author": author, "gate": gate_d})
        return PipelineResult(
            output=out,
            gate=gate_d,
            author=author,
            provider_calls=provider_calls,
            durable_rows=durable,
        )

    critique = run_independent_critic(
        grounded=grounded_v,
        author=author,
        policy=policy,
        call_fn=critic_call_fn,
    )
    provider_calls += int(critique.get("provider_calls") or 0)

    if not critique.get("ok"):
        out = build_refusal_output(
            grounded=grounded_v,
            gate_state=str(critique.get("refusal_state") or "SCHEMA_INVALID"),
            reasons=list(critique.get("reasons") or []),
            source_sha=source_sha or str(grounded_v.get("source_sha") or ""),
            epoch_id=str(grounded_v.get("epoch_id") or ""),
            schedule_slot=str(grounded_v.get("schedule_slot") or ""),
            correlation_id=str(grounded_v.get("correlation_id") or ""),
            provider_calls=provider_calls,
        )
        # Author succeeded but critique failed — persist author quarantine, no AgentView/commitment.
        durable.append({"kind": "author_without_critique", "author": author, "critique": critique})
        durable.append({"kind": "refusal", "body": out, "gate": gate_d})
        return PipelineResult(
            output=out,
            gate=gate_d,
            author=author,
            critique=critique,
            provider_calls=provider_calls,
            durable_rows=durable,
        )

    try:
        agent_view = synthesize_agent_view(
            author=author,
            critique=critique,
            grounded=grounded_v,
            source_sha=source_sha or str(grounded_v.get("source_sha") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        out = build_refusal_output(
            grounded=grounded_v,
            gate_state="QUARANTINED",
            reasons=[f"agent_view_synthesis:{exc}"],
            source_sha=source_sha or str(grounded_v.get("source_sha") or ""),
            epoch_id=str(grounded_v.get("epoch_id") or ""),
            schedule_slot=str(grounded_v.get("schedule_slot") or ""),
            correlation_id=str(grounded_v.get("correlation_id") or ""),
            provider_calls=provider_calls,
        )
        durable.append({"kind": "refusal", "body": out, "author": author, "critique": critique})
        return PipelineResult(
            output=out,
            gate=gate_d,
            author=author,
            critique=critique,
            provider_calls=provider_calls,
            durable_rows=durable,
        )

    commitment = None
    try:
        commitment = synthesize_commitment(
            author=author,
            critique=critique,
            agent_view=agent_view,
            grounded=grounded_v,
            source_sha=source_sha or str(grounded_v.get("source_sha") or ""),
            release=release,
            served_sha=served_sha or release,
        )
    except Exception as exc:  # noqa: BLE001
        # Commitment failure does not erase judgment; record explanation separately.
        durable.append({"kind": "commitment_refused", "reason": str(exc)})

    # Idempotency: do not append duplicate durable judgment rows for same judgment_id.
    jid = str(author.get("judgment_id") or "")
    if jid and any(
        isinstance(r, Mapping)
        and r.get("kind") == "judgment"
        and (r.get("body") or {}).get("author", {}).get("judgment_id") == jid
        for r in durable
    ):
        # Retry path — no duplicate
        pass
    else:
        out = build_judgment_output(
            grounded=grounded_v,
            author=author,
            critique=critique,
            agent_view=agent_view,
            commitment=commitment,
        )
        out["provider_calls"] = provider_calls
        durable.append({"kind": "judgment", "body": out})
        if commitment:
            durable.append({"kind": "commitment", "body": commitment})
        else:
            durable.append(
                {
                    "kind": "explanation_without_commitment",
                    "reason": "missing_falsifier_or_critic_abstain_reject",
                    "judgment_id": jid,
                    "critique_id": critique.get("critique_id"),
                }
            )

        return PipelineResult(
            output=out,
            gate=gate_d,
            author=author,
            critique=critique,
            agent_view=agent_view,
            commitment=commitment,
            provider_calls=provider_calls,
            durable_rows=durable,
        )

    # Fallback (duplicate path): still return latest output shape
    out = build_judgment_output(
        grounded=grounded_v,
        author=author,
        critique=critique,
        agent_view=agent_view,
        commitment=commitment,
    )
    out["provider_calls"] = provider_calls
    return PipelineResult(
        output=out,
        gate=gate_d,
        author=author,
        critique=critique,
        agent_view=agent_view,
        commitment=commitment,
        provider_calls=provider_calls,
        durable_rows=durable,
    )
