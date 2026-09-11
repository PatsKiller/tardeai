"""AgentView@v1 — falsifiable agent-formed view with critic gate.

May recommend/abstain/dispute. Must not size or execute trades (MBI_BEHAVIOR=0).

L3 closure (20260911): falsifier, provenance class A vs T, and non-template
cost_class when a model authored the view. Template class T must never
masquerade as class A.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import hashlib


NO_CONSUMER_REASON = (
    "maturity-gap-closure-20260909 hermetic lane helpers; serving-SHA producers/"
    "consumers await merge+promote+operator grants (telegram/service/drive). "
    "Zero live consumers is correct until then — not a silent dark contract "
    "(MBI_BEHAVIOR=0; recommendation≠mutation)."
)

SCHEMA = "AgentView@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
STANCES = ("RECOMMEND", "ABSTAIN", "DISPUTE")
PROVENANCE_CLASSES = ("A", "T", "D", "M", "S")


@dataclass
class AgentViewV1:
    view_id: str
    subject: str
    stance: str  # RECOMMEND | ABSTAIN | DISPUTE
    summary: str
    confidence: float
    citations: list[str] = field(default_factory=list)
    uncertainty: str = ""
    falsifier: str = ""
    critic_pass: bool = False
    critic_notes: list[str] = field(default_factory=list)
    cost_class: str = "zero"
    provenance_class: str = "T"
    source_sha: str = ""
    produced_at: str = ""
    authority: str = AUTHORITY
    mbi_behavior: int = MBI_BEHAVIOR
    judgment_id: str | None = None
    critique_id: str | None = None
    llm_provenance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA,
            "view_id": self.view_id,
            "subject": self.subject,
            "stance": self.stance,
            "summary": self.summary,
            "confidence": self.confidence,
            "citations": list(self.citations),
            "uncertainty": self.uncertainty,
            "falsifier": self.falsifier,
            "critic_pass": self.critic_pass,
            "critic_notes": list(self.critic_notes),
            "cost_class": self.cost_class,
            "provenance_class": self.provenance_class,
            "source_sha": self.source_sha,
            "produced_at": self.produced_at,
            "authority": self.authority,
            "mbi_behavior": self.mbi_behavior,
            "judgment_id": self.judgment_id,
            "critique_id": self.critique_id,
            "provenance": {
                "llm": self.llm_provenance,
                "producer": "agent_view_v1",
            },
            "sizes_or_executes_trades": False,
        }


def _mint_view_id(subject: str, summary: str, source_sha: str) -> str:
    digest = hashlib.sha256(f"{subject}|{summary}|{source_sha}".encode()).hexdigest()
    return f"view_{digest[:24]}"


def critic_pass(view: AgentViewV1) -> AgentViewV1:
    """Require citations, bounded confidence, no trade verbs, MBI=0, legal stance."""
    notes: list[str] = []
    ok = True
    if not view.citations:
        ok = False
        notes.append("missing_citations")
    if not (0.0 <= float(view.confidence) <= 1.0):
        ok = False
        notes.append("confidence_out_of_range")
    if view.mbi_behavior != 0:
        ok = False
        notes.append("mbi_behavior_nonzero")
    banned = ("buy ", "sell ", "size ", "order ", "broker")
    low = (view.summary or "").lower()
    if any(b in low for b in banned):
        ok = False
        notes.append("financial_action_language")
    if view.stance not in STANCES:
        ok = False
        notes.append("illegal_stance")
    # Class A (model-involved) must not claim template cost_class zero without llm null.
    if view.provenance_class == "A":
        if view.llm_provenance is None:
            ok = False
            notes.append("class_A_missing_llm_provenance")
        if view.cost_class == "zero":
            ok = False
            notes.append("class_A_cannot_be_cost_class_zero")
        if not (view.falsifier or "").strip():
            ok = False
            notes.append("class_A_missing_falsifier")
    # Template class T must not masquerade as A
    if view.provenance_class == "T" and view.llm_provenance is not None:
        ok = False
        notes.append("class_T_with_llm_provenance")
    if view.provenance_class not in PROVENANCE_CLASSES:
        ok = False
        notes.append("illegal_provenance_class")
    view.critic_pass = ok
    view.critic_notes = notes
    return view


def produce_agent_view_v1(
    *,
    subject: str,
    summary: str,
    citations: list[str],
    confidence: float,
    source_sha: str,
    stance: str | None = None,
    uncertainty: str = "",
    cost_class: str = "zero",
    falsifier: str = "",
    provenance_class: str = "T",
    judgment_id: str | None = None,
    critique_id: str | None = None,
    llm_provenance: dict[str, Any] | None = None,
) -> AgentViewV1:
    """Produce AgentView@v1. Critic must pass before persist callers accept.

    Default remains template-class (T) / cost_class zero for hermetic helpers.
    L3 model synthesis must pass provenance_class='A' with llm_provenance and falsifier.
    """
    if stance is None:
        stance = "ABSTAIN" if confidence < 0.55 or not citations else "RECOMMEND"
    # Infer class A when llm provenance is supplied.
    if llm_provenance is not None and provenance_class == "T":
        provenance_class = "A"
    if provenance_class == "A" and cost_class == "zero":
        cost_class = "model"
    view = AgentViewV1(
        view_id=_mint_view_id(subject, summary, source_sha),
        subject=subject,
        stance=stance,
        summary=summary,
        confidence=float(confidence),
        citations=list(citations),
        uncertainty=uncertainty or ("insufficient_evidence" if not citations else ""),
        falsifier=falsifier,
        cost_class=cost_class,
        provenance_class=provenance_class,
        source_sha=source_sha,
        produced_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        judgment_id=judgment_id,
        critique_id=critique_id,
        llm_provenance=llm_provenance,
    )
    return critic_pass(view)


def persist_allowed(view: AgentViewV1) -> bool:
    return bool(view.critic_pass and view.mbi_behavior == 0 and not view.to_dict()["sizes_or_executes_trades"])
