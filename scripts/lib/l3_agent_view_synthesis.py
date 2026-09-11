"""C4 — deterministic AgentView + governed commitment synthesis.

Synthesis validates model prose against schemas; it does not invent judgment.
AgentView@v1 is emitted only when judgment + critique schemas pass.

- stance may vary and includes abstention/dispute
- provenance class A reflects model involvement (T cannot masquerade as A)
- every quantitative value must cite a source or be refused
- uncertainty and disagreement survive synthesis
- no behavioral/portfolio mutation fields
- commitment requires falsifier + judgment_id + critique_id + checkpoint_id
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from scripts.lib.agent_view_v1 import (
    SCHEMA as AGENT_VIEW_SCHEMA,
    produce_agent_view_v1,
)
from scripts.lib.governed_commitment import CommitmentError, build_governed_commitment
from scripts.lib.judgment_schema import AUTHOR_STANCES, JudgmentSchemaError

AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
_BROKER_RE = re.compile(
    r"\b(order|quantity|shares|broker|stop_loss|limit_price|target_weight|position_size)\b",
    re.I,
)
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_/])[-+]?\d+(?:\.\d+)?%?(?![A-Za-z0-9_/])")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _checkpoint_id(judgment_id: str, critique_id: str, schedule_slot: str) -> str:
    digest = hashlib.sha256(f"{judgment_id}|{critique_id}|{schedule_slot}".encode()).hexdigest()
    return f"chk_{digest[:24]}"


def map_stance(author_stance: str, critic_verdict: str) -> str:
    stance = str(author_stance or "").upper()
    verdict = str(critic_verdict or "").lower()
    if verdict in {"reject", "abstain"}:
        return "ABSTAIN"
    if stance in AUTHOR_STANCES:
        # AgentView@v1 historically RECOMMEND|ABSTAIN — extend with DISPUTE via notes,
        # but keep primary stance in the expanded set on the synthesized record.
        return stance
    return "ABSTAIN"


def synthesize_agent_view(
    *,
    author: Mapping[str, Any],
    critique: Mapping[str, Any],
    grounded: Mapping[str, Any],
    source_sha: str,
) -> dict[str, Any]:
    """Emit AgentView only after judgment+critique schema success (caller-enforced)."""
    if critique.get("ok") is False or author.get("ok") is False:
        raise JudgmentSchemaError("cannot_synthesize_from_failed_parts")

    revised = critique.get("revised_author") if isinstance(critique.get("revised_author"), Mapping) else author
    stance = map_stance(str(revised.get("stance") or author.get("stance")), str(critique.get("verdict")))
    claim = str(revised.get("claim") or "")
    falsifier = str(revised.get("falsifier") or "").strip()
    if not falsifier:
        raise JudgmentSchemaError("agent_view_missing_falsifier")

    if _BROKER_RE.search(claim) or _BROKER_RE.search(falsifier):
        raise JudgmentSchemaError("agent_view_broker_language")

    # Quantitative values must cite evidence or be refused.
    if _NUMBER_RE.search(claim):
        ev = revised.get("evidence_source_ids") or []
        if not ev:
            raise JudgmentSchemaError("quantitative_claim_without_evidence")

    conf = float(revised.get("confidence") or 0)
    citations = [str(x) for x in (revised.get("evidence_source_ids") or [])]
    citations.extend(str(x) for x in (revised.get("memory_fact_ids") or []))
    # Dedup preserve order
    seen: set[str] = set()
    cites: list[str] = []
    for c in citations:
        if c and c not in seen:
            seen.add(c)
            cites.append(c)

    uncertainty = revised.get("uncertainties")
    if isinstance(uncertainty, list):
        uncertainty_s = "; ".join(str(u) for u in uncertainty)
        uncertainty_f = min(1.0, 0.15 * len(uncertainty) + (0.2 if stance == "ABSTAIN" else 0.0))
    else:
        uncertainty_s = str(uncertainty or "")
        uncertainty_f = 0.5 if stance == "ABSTAIN" else 0.2

    # Disagreement survives: critic reject/abstain/revise noted.
    critic_notes = [
        f"critic_verdict={critique.get('verdict')}",
        f"critic_provider={critique.get('provider')}",
    ]
    if critique.get("verdict") == "revise":
        for ch in critique.get("field_changes") or []:
            if isinstance(ch, Mapping):
                critic_notes.append(f"revised:{ch.get('field')}")
    if critique.get("contradictions"):
        critic_notes.append(f"contradictions={len(critique.get('contradictions') or [])}")

    cost_usd = float(author.get("cost_usd") or 0) + float(critique.get("cost_usd") or 0)
    cost_class = "model" if cost_usd > 0 or not author.get("cache_hit") else "model_cached"
    if (
        author.get("cache_hit")
        and float(author.get("cost_usd") or 0) == 0
        and float(critique.get("cost_usd") or 0) == 0
    ):
        # Still model class A — never template zero masquerading.
        cost_class = "model_cached"

    # Map extended judgment stances onto AgentView@v1 STANCES.
    if stance in {"ABSTAIN", "INSUFFICIENT", "NEUTRAL"}:
        view_stance = "ABSTAIN"
    elif stance == "DISPUTE":
        view_stance = "DISPUTE"
    elif stance in {"RECOMMEND", "BULLISH"}:
        view_stance = "RECOMMEND"
    elif stance == "BEARISH":
        view_stance = "DISPUTE"
    else:
        view_stance = "ABSTAIN"

    llm_prov = {
        "author_provider": author.get("provider"),
        "author_model": author.get("returned_model"),
        "critic_provider": critique.get("provider"),
        "critic_model": critique.get("model_returned"),
        "author_input_digest": author.get("input_digest"),
        "author_output_digest": author.get("output_digest"),
    }
    base = produce_agent_view_v1(
        subject=str(revised.get("subject_guid") or ""),
        summary=claim,
        citations=cites,
        confidence=conf,
        source_sha=source_sha,
        stance=view_stance,
        uncertainty=uncertainty_s,
        cost_class=cost_class,
        falsifier=falsifier,
        provenance_class="A",
        judgment_id=str(author.get("judgment_id") or "") or None,
        critique_id=str(critique.get("critique_id") or "") or None,
        llm_provenance=llm_prov,
    )
    view = base.to_dict()
    view.update(
        {
            "schema_version": AGENT_VIEW_SCHEMA,
            "judgment_stance": stance,
            "uncertainty_score": round(float(uncertainty_f), 4),
            "horizon": revised.get("horizon"),
            "provenance": {
                "producer": "l3_agent_view_synthesis",
                "llm": llm_prov,
                "policy_decisions": critic_notes,
            },
            "cost_usd": cost_usd,
            "disagreement": {
                "critic_verdict": critique.get("verdict"),
                "field_changes": list(critique.get("field_changes") or []),
                "contradictions": list(critique.get("contradictions") or []),
            },
            "mbi_behavior": MBI_BEHAVIOR,
            "authority": AUTHORITY,
            "sizes_or_executes_trades": False,
            "behavioral_mutation_fields": None,
            "portfolio_mutation_fields": None,
        }
    )
    if view["provenance_class"] != "A" or view["provenance"].get("llm") is None:
        raise JudgmentSchemaError("provenance_class_A_required_for_model_view")
    if not view.get("critic_pass"):
        raise JudgmentSchemaError("agent_view_critic_pass_failed:" + ",".join(view.get("critic_notes") or []))
    return view


def synthesize_commitment(
    *,
    author: Mapping[str, Any],
    critique: Mapping[str, Any],
    agent_view: Mapping[str, Any],
    grounded: Mapping[str, Any],
    source_sha: str,
    release: str = "",
    served_sha: str = "",
) -> dict[str, Any] | None:
    """Return commitment dict or None when falsifier missing (explanation-only path)."""
    revised = critique.get("revised_author") if isinstance(critique.get("revised_author"), Mapping) else author
    falsifier = str(revised.get("falsifier") or agent_view.get("falsifier") or "").strip()
    if not falsifier:
        return None  # No falsifier ⇒ no commitment row

    if str(critique.get("verdict") or "").lower() in {"reject", "abstain"}:
        # Critic reject/abstain: may store explanation separately; no commitment.
        return None

    judgment_id = str(author.get("judgment_id") or "")
    critique_id = str(critique.get("critique_id") or "")
    schedule_slot = str(grounded.get("schedule_slot") or "")
    checkpoint_id = _checkpoint_id(judgment_id, critique_id, schedule_slot)

    mem_ids = [str(x) for x in (revised.get("memory_fact_ids") or [])]
    research_ids = [str(x) for x in (revised.get("research_object_ids") or [])]
    evidence_refs = mem_ids + research_ids + [str(x) for x in (revised.get("evidence_source_ids") or [])]
    # Dedup
    seen: set[str] = set()
    refs: list[str] = []
    for e in evidence_refs:
        if e and e not in seen:
            seen.add(e)
            refs.append(e)
    if not refs:
        raise CommitmentError("missing_evidence")

    created = _now()
    # Horizon → due window (simple day parse)
    horizon = str(revised.get("horizon") or "7d")
    days = 7
    m = re.match(r"^(\d+)d$", horizon.strip())
    if m:
        days = max(1, int(m.group(1)))
    due = created + timedelta(days=days)
    frozen = created  # freeze before outcome window

    subject_guid = str(revised.get("subject_guid") or (grounded.get("subject") or {}).get("subject_guid") or "")
    gc = build_governed_commitment(
        claim=str(revised.get("claim") or agent_view.get("summary") or ""),
        confidence=float(revised.get("confidence") or agent_view.get("confidence") or 0),
        horizon=horizon,
        due_at=due,
        falsifier=falsifier,
        evidence_refs=refs,
        source_identity="l3_judgment_pipeline",
        source_sha=source_sha or str(grounded.get("source_sha") or ""),
        served_sha=served_sha or release or source_sha,
        subject_guid=subject_guid,
        trigger_provenance={
            "producer": "l3_judgment_pipeline",
            "trigger": grounded.get("trigger") or "scheduled",
            "schedule_slot": schedule_slot,
            "epoch_id": grounded.get("epoch_id"),
            "correlation_id": grounded.get("correlation_id"),
        },
        created_at=created,
        frozen_at=frozen,
    )
    gc.update(
        {
            "judgment_id": judgment_id,
            "critique_id": critique_id,
            "checkpoint_id": checkpoint_id,
            "view_id": agent_view.get("view_id"),
            "evidence_ids": {
                "memory_fact_ids": mem_ids,
                "research_object_ids": research_ids,
            },
            "checkpoint_binding": checkpoint_id,
            "release": release,
            "epoch_id": grounded.get("epoch_id"),
            "exact_source_sha": source_sha or grounded.get("source_sha"),
            "created_at": _iso(created),
            "frozen_at": _iso(frozen),
        }
    )
    return gc
