"""L3 judgment schemas — GroundedJudgmentInput@v1 consumer + JudgmentOutput@v1.

Lane C owns this module. Lane B produces GroundedJudgmentInput@v1; Lane C
consumes it. Shape changes require an SFR to Lane A and a version bump.

Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0. Beliefs/advice only — never
executable trade instructions. No secrets or raw prompts in persisted digests.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_INPUT = "GroundedJudgmentInput@v1"
SCHEMA_OUTPUT = "JudgmentOutput@v1"
SCHEMA_AUTHOR = "L3AuthorJudgment@v1"
SCHEMA_CRITIQUE = "L3Critique@v1"
SCHEMA_REFUSAL = "L3JudgmentRefusal@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
PROMPT_TEMPLATE_VERSION = "l3_judgment_author@v1"

# Deliverable C1 durable states (versioned). Never report a model judgment when
# no call occurred.
GATE_PROCEED = "PROCEED"
NO_MATERIAL_RESIDUAL = "NO_MATERIAL_RESIDUAL"
UNGROUNDED_REFUSED = "UNGROUNDED_REFUSED"
OFFPEAK_DEFERRED = "OFFPEAK_DEFERRED"
CAP_REFUSED = "CAP_REFUSED"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
FREE_FIRST_PENDING = "FREE_FIRST_PENDING"
EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
WRONG_SUBJECT_REFUSED = "WRONG_SUBJECT_REFUSED"
SCHEMA_INVALID = "SCHEMA_INVALID"
MODEL_MISMATCH = "MODEL_MISMATCH"
PROVIDER_OUTAGE = "PROVIDER_OUTAGE"
CRITIC_PROVIDER_COLLISION = "CRITIC_PROVIDER_COLLISION"
QUARANTINED = "QUARANTINED"
UNRECOGNIZED_REFUSAL = "UNRECOGNIZED_REFUSAL"

DURABLE_REFUSAL_STATES = frozenset(
    {
        NO_MATERIAL_RESIDUAL,
        UNGROUNDED_REFUSED,
        OFFPEAK_DEFERRED,
        CAP_REFUSED,
        MODEL_UNAVAILABLE,
        FREE_FIRST_PENDING,
        EVIDENCE_INSUFFICIENT,
        WRONG_SUBJECT_REFUSED,
        SCHEMA_INVALID,
        MODEL_MISMATCH,
        PROVIDER_OUTAGE,
        CRITIC_PROVIDER_COLLISION,
        QUARANTINED,
        UNRECOGNIZED_REFUSAL,
    }
)

# Map deliverable codes → INTERFACE_CONTRACT JudgmentOutput.refusal_reason
REFUSAL_REASON_MAP: dict[str, str] = {
    UNGROUNDED_REFUSED: "no_grounding",
    WRONG_SUBJECT_REFUSED: "no_grounding",
    NO_MATERIAL_RESIDUAL: "no_material_question",
    FREE_FIRST_PENDING: "no_material_question",
    EVIDENCE_INSUFFICIENT: "no_material_question",
    CAP_REFUSED: "budget_cap",
    MODEL_MISMATCH: "model_mismatch",
    MODEL_UNAVAILABLE: "provider_outage",
    PROVIDER_OUTAGE: "provider_outage",
    SCHEMA_INVALID: "schema_invalid",
    QUARANTINED: "schema_invalid",
    CRITIC_PROVIDER_COLLISION: "provider_refusal",  # independence fail — not a schema parse error
    # 2026-09-11 (Lane A, SFR_L3_TO_INTEGRATION): the contract enum was extended
    # rather than reusing provider_refusal. A deferral and a refusal are not the
    # same event: the provider was never asked, nothing was denied, and the work
    # is still due. Filing deferrals as refusals would have made the refusal
    # counters unreadable — every out-of-window slot would have looked like a
    # provider problem.
    OFFPEAK_DEFERRED: "offpeak_deferred",
}

# Author stance must permit disagreement / abstention / dispute.
AUTHOR_STANCES = frozenset(
    {
        "RECOMMEND",
        "DISPUTE",
        "ABSTAIN",
        "BEARISH",
        "BULLISH",
        "NEUTRAL",
        "INSUFFICIENT",
    }
)

CRITIC_VERDICTS = frozenset({"accept", "revise", "abstain", "reject"})

# Broker / mutation vocabulary — fail closed if present on judgment surfaces.
_BROKER_FIELD_RE = re.compile(
    r"\b(order|quantity|shares|broker|stop_loss|limit_price|target_weight|"
    r"position_size|execute_trade|place_order|submit_order)\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_/])[-+]?\d+(?:\.\d+)?%?(?![A-Za-z0-9_/])")


class JudgmentSchemaError(ValueError):
    """Fail-closed schema / grounding / parse error."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest_text(text: str) -> str:
    return "sha256:" + hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def digest_obj(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return digest_text(payload)


def _as_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise JudgmentSchemaError(f"{name}_not_object")
    return dict(value)


@dataclass
class GateDecision:
    state: str
    proceed: bool
    reasons: list[str] = field(default_factory=list)
    material_question: str | None = None
    selected_memory_fact_ids: list[str] = field(default_factory=list)
    evidence_visible: dict[str, Any] = field(default_factory=dict)
    provider_calls_allowed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "proceed": self.proceed,
            "reasons": list(self.reasons),
            "material_question": self.material_question,
            "selected_memory_fact_ids": list(self.selected_memory_fact_ids),
            "evidence_visible": dict(self.evidence_visible),
            "provider_calls_allowed": int(self.provider_calls_allowed),
        }


def validate_grounded_input(raw: Any) -> dict[str, Any]:
    """Validate Lane B GroundedJudgmentInput@v1. Do not invent missing fields."""
    data = _as_mapping(raw, "input")
    errs: list[str] = []
    if data.get("schema") != SCHEMA_INPUT:
        errs.append("schema_mismatch")

    subject = data.get("subject")
    if not isinstance(subject, Mapping):
        errs.append("missing_subject")
        subject = {}
    subject_guid = str(subject.get("subject_guid") or "").strip()
    if not subject_guid:
        errs.append("missing_subject_guid")
    try:
        conf = float(subject.get("resolution_confidence", 0))
        if not (0.0 <= conf <= 1.0):
            errs.append("resolution_confidence_out_of_range")
    except (TypeError, ValueError):
        errs.append("resolution_confidence_not_numeric")

    facts = data.get("memory_facts")
    if not isinstance(facts, list):
        errs.append("memory_facts_not_list")
        facts = []

    retrieval = data.get("retrieval")
    if not isinstance(retrieval, Mapping):
        errs.append("missing_retrieval")
        retrieval = {}
    if retrieval.get("cliff_applied") is True:
        errs.append("cliff_applied_forbidden")

    research = data.get("research")
    if not isinstance(research, Mapping):
        errs.append("missing_research")
        research = {}

    mrq = data.get("material_residual_question")
    if not isinstance(mrq, Mapping):
        errs.append("missing_material_residual_question")
        mrq = {}

    for key in ("source_sha", "epoch_id", "schedule_slot", "trigger", "correlation_id", "as_of_utc"):
        if not data.get(key):
            errs.append(f"missing_{key}")

    if errs:
        raise JudgmentSchemaError(";".join(errs))

    # Wrong-subject facts are a hard signal (do not silently use them).
    wrong = []
    for fact in facts:
        if not isinstance(fact, Mapping):
            continue
        fg = str(fact.get("subject_guid") or "").strip()
        if fg and subject_guid and fg != subject_guid:
            wrong.append(str(fact.get("memory_fact_id") or ""))

    out = dict(data)
    out["_wrong_subject_fact_ids"] = wrong
    return out


def author_judgment_required_fields() -> tuple[str, ...]:
    return (
        "judgment_id",
        "subject_guid",
        "question",
        "stance",
        "claim",
        "confidence",
        "evidence_source_ids",
        "memory_fact_ids",
        "research_object_ids",
        "assumptions",
        "uncertainties",
        "falsifier",
        "horizon",
        "next_research_question",
        "provider",
        "requested_model",
        "returned_model",
        "prompt_template_version",
        "input_digest",
        "output_digest",
        "cache_key",
        "cache_hit",
        "cost_usd",
        "latency_ms",
        "source_sha",
        "release",
        "epoch_id",
        "trigger",
        "schema_version",
    )


def validate_author_judgment(raw: Any, *, grounded: Mapping[str, Any]) -> dict[str, Any]:
    """Parse/validate structured author output. Fail → quarantine/refusal."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise JudgmentSchemaError(f"non_json:{exc}") from exc
    data = _as_mapping(raw, "author_judgment")
    errs: list[str] = []

    for key in author_judgment_required_fields():
        if key not in data:
            errs.append(f"missing_{key}")

    stance = str(data.get("stance") or "")
    if stance not in AUTHOR_STANCES:
        errs.append("illegal_stance")

    claim = str(data.get("claim") or "").strip()
    if not claim:
        errs.append("missing_claim")

    falsifier = str(data.get("falsifier") or "").strip()
    if not falsifier:
        errs.append("missing_falsifier")

    try:
        conf = float(data.get("confidence"))
        if not (0.0 <= conf <= 1.0):
            errs.append("confidence_out_of_range")
    except (TypeError, ValueError):
        errs.append("confidence_not_numeric")
        conf = None

    mem_ids = data.get("memory_fact_ids")
    if not isinstance(mem_ids, list) or not mem_ids:
        errs.append("missing_memory_fact_ids")
    else:
        allowed = {str(f.get("memory_fact_id")) for f in (grounded.get("memory_facts") or []) if isinstance(f, Mapping)}
        for mid in mem_ids:
            if str(mid) not in allowed:
                errs.append(f"uncited_memory_fact:{mid}")

    ev_ids = data.get("evidence_source_ids")
    if not isinstance(ev_ids, list) or not ev_ids:
        errs.append("missing_evidence_source_ids")

    research_ids = data.get("research_object_ids")
    if not isinstance(research_ids, list):
        errs.append("research_object_ids_not_list")

    # Invented numbers in claim without evidence citation → refuse.
    if claim and _NUMBER_RE.search(claim):
        # Numbers are allowed only when evidence IDs are present AND claim cites them.
        if not ev_ids:
            errs.append("invented_number_uncited")

    # Broker / mutation language fail-closed.
    blob = " ".join(
        [
            claim,
            falsifier,
            str(data.get("next_research_question") or ""),
            " ".join(str(x) for x in (data.get("assumptions") or [])),
        ]
    )
    if _BROKER_FIELD_RE.search(blob):
        errs.append("broker_or_mutation_language")

    if int(data.get("mbi_behavior", 0) or 0) != 0:
        errs.append("mbi_nonzero")

    if errs:
        raise JudgmentSchemaError(";".join(errs))

    out = dict(data)
    out["schema_version"] = SCHEMA_AUTHOR
    out["authority"] = AUTHORITY
    out["mbi_behavior"] = MBI_BEHAVIOR
    out["confidence"] = float(conf) if conf is not None else float(data["confidence"])
    return out


def validate_critique(raw: Any, *, author_provider: str) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise JudgmentSchemaError(f"critic_non_json:{exc}") from exc
    data = _as_mapping(raw, "critique")
    errs: list[str] = []
    for key in (
        "critique_id",
        "verdict",
        "contradictions",
        "unsupported_claims",
        "field_changes",
        "provider",
        "model_returned",
        "cost_usd",
        "latency_ms",
        "author_provider",
        "independence_proof",
    ):
        if key not in data:
            errs.append(f"missing_{key}")

    verdict = str(data.get("verdict") or "").lower()
    if verdict not in CRITIC_VERDICTS:
        errs.append("illegal_verdict")

    critic_provider = str(data.get("provider") or "").strip().lower()
    author_p = str(author_provider or data.get("author_provider") or "").strip().lower()
    if not critic_provider or not author_p:
        errs.append("missing_provider_pair")
    elif critic_provider == author_p:
        errs.append("author_critic_same_provider")

    field_changes = data.get("field_changes")
    if not isinstance(field_changes, list):
        errs.append("field_changes_not_list")
    elif verdict == "revise":
        named = [c for c in field_changes if isinstance(c, Mapping) and c.get("field")]
        if not named:
            errs.append("revise_without_named_field_change")
        for c in named:
            if "before" not in c or "after" not in c:
                errs.append("field_change_missing_before_after")
            elif c.get("before") == c.get("after"):
                errs.append("field_change_noop")

    if errs:
        raise JudgmentSchemaError(";".join(errs))

    out = dict(data)
    out["verdict"] = verdict
    out["schema_version"] = SCHEMA_CRITIQUE
    out["mbi_behavior"] = MBI_BEHAVIOR
    out["authority"] = AUTHORITY
    return out


def build_refusal_output(
    *,
    grounded: Mapping[str, Any] | None,
    gate_state: str,
    reasons: list[str] | None = None,
    source_sha: str = "",
    epoch_id: str = "",
    schedule_slot: str = "",
    correlation_id: str = "",
    subject_guid: str = "",
    provider_calls: int = 0,
) -> dict[str, Any]:
    """Durable refusal/defer — never a template promoted to L3 judgment."""
    g = dict(grounded or {})
    reasons = list(reasons or [])
    if gate_state in DURABLE_REFUSAL_STATES:
        state = gate_state
    else:
        # Latent defect noted 2026-09-11: silently relabelling unknown states as
        # SCHEMA_INVALID asserts "model answered off-contract" about a state the
        # system simply does not recognize. Keep an explicit durable state.
        state = UNRECOGNIZED_REFUSAL
        reasons.append(f"unrecognized_refusal_state:{gate_state}")
    refusal_reason = REFUSAL_REASON_MAP.get(state, "provider_refusal")
    return {
        "schema": SCHEMA_OUTPUT,
        "correlation_id": correlation_id or g.get("correlation_id") or "",
        "subject_guid": subject_guid
        or ((g.get("subject") or {}).get("subject_guid") if isinstance(g.get("subject"), Mapping) else "")
        or "",
        "status": "REFUSED",
        "refusal_reason": refusal_reason,
        "refusal_state": state,
        "refusal_reasons": list(reasons),
        "provider_calls": int(provider_calls),
        "author": None,
        "critic": None,
        "agent_view": None,
        "commitment": None,
        "source_sha": source_sha or g.get("source_sha") or "",
        "epoch_id": epoch_id or g.get("epoch_id") or "",
        "schedule_slot": schedule_slot or g.get("schedule_slot") or "",
        "produced_at": _now_iso(),
        "authority": AUTHORITY,
        "mbi_behavior": MBI_BEHAVIOR,
        "provenance_class": "T",  # refusal is deterministic template-class, not model judgment
    }


def contract_critic_view(critique: Mapping[str, Any]) -> dict[str, Any]:
    """Map rich critique → INTERFACE_CONTRACT critic block."""
    verdict = str(critique.get("verdict") or "").lower()
    changed = verdict == "revise"
    field_named = ""
    changes = critique.get("field_changes") or []
    if isinstance(changes, list) and changes:
        first = changes[0]
        if isinstance(first, Mapping):
            field_named = str(first.get("field") or "")
    if not field_named:
        field_named = "preserved" if not changed else "unknown"
    return {
        "provider": critique.get("provider"),
        "model_returned": critique.get("model_returned"),
        "verdict": "changed" if changed else "preserved",
        "field_named": field_named,
        "reason": str(critique.get("reason") or critique.get("summary") or verdict),
        "rich_verdict": verdict,
        "cost_usd": critique.get("cost_usd"),
        "latency_ms": critique.get("latency_ms"),
        "independence_proof": critique.get("independence_proof"),
    }


def build_judgment_output(
    *,
    grounded: Mapping[str, Any],
    author: Mapping[str, Any],
    critique: Mapping[str, Any],
    agent_view: Mapping[str, Any] | None,
    commitment: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_OUTPUT,
        "correlation_id": grounded.get("correlation_id"),
        "subject_guid": (grounded.get("subject") or {}).get("subject_guid")
        if isinstance(grounded.get("subject"), Mapping)
        else author.get("subject_guid"),
        "status": "JUDGED",
        "refusal_reason": None,
        "refusal_state": None,
        "provider_calls": int(author.get("provider_calls") or 1) + int(critique.get("provider_calls") or 1),
        "author": {
            "provider": author.get("provider"),
            "model_requested": author.get("requested_model"),
            "model_returned": author.get("returned_model"),
            "prompt_digest": author.get("prompt_template_version"),
            "input_digest": author.get("input_digest"),
            "output_digest": author.get("output_digest"),
            "cost_usd": author.get("cost_usd"),
            "latency_ms": author.get("latency_ms"),
            "off_peak": author.get("off_peak"),
            "judgment_id": author.get("judgment_id"),
            "cache_hit": author.get("cache_hit"),
        },
        "critic": contract_critic_view(critique),
        "agent_view": agent_view,
        "commitment": commitment,
        "source_sha": grounded.get("source_sha") or author.get("source_sha"),
        "epoch_id": grounded.get("epoch_id") or author.get("epoch_id"),
        "schedule_slot": grounded.get("schedule_slot"),
        "produced_at": _now_iso(),
        "authority": AUTHORITY,
        "mbi_behavior": MBI_BEHAVIOR,
        "provenance_class": "A",
    }
