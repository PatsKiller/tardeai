"""Lane G — smallest falsifiable AgentView@v1 with critic gate.

May recommend/abstain. Must not size or execute trades (MBI_BEHAVIOR=0).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import hashlib
import json


NO_CONSUMER_REASON = (
    "maturity-gap-closure-20260909 hermetic lane helpers; serving-SHA producers/"
    "consumers await merge+promote+operator grants (telegram/service/drive). "
    "Zero live consumers is correct until then — not a silent dark contract "
    "(MBI_BEHAVIOR=0; recommendation≠mutation)."
)

SCHEMA = "AgentView@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0


@dataclass
class AgentViewV1:
    view_id: str
    subject: str
    stance: str  # RECOMMEND | ABSTAIN
    summary: str
    confidence: float
    citations: list[str] = field(default_factory=list)
    uncertainty: str = ""
    critic_pass: bool = False
    critic_notes: list[str] = field(default_factory=list)
    cost_class: str = "zero"
    source_sha: str = ""
    produced_at: str = ""
    authority: str = AUTHORITY
    mbi_behavior: int = MBI_BEHAVIOR

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
            "critic_pass": self.critic_pass,
            "critic_notes": list(self.critic_notes),
            "cost_class": self.cost_class,
            "source_sha": self.source_sha,
            "produced_at": self.produced_at,
            "authority": self.authority,
            "mbi_behavior": self.mbi_behavior,
            "sizes_or_executes_trades": False,
        }


def _mint_view_id(subject: str, summary: str, source_sha: str) -> str:
    digest = hashlib.sha256(f"{subject}|{summary}|{source_sha}".encode()).hexdigest()
    return f"view_{digest[:24]}"


def critic_pass(view: AgentViewV1) -> AgentViewV1:
    """Falsifier: require citations, bounded confidence, no trade verbs, MBI=0."""
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
    if view.stance not in ("RECOMMEND", "ABSTAIN"):
        ok = False
        notes.append("illegal_stance")
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
) -> AgentViewV1:
    """Zero-cost path by default; critic must pass before persist callers accept."""
    if stance is None:
        stance = "ABSTAIN" if confidence < 0.55 or not citations else "RECOMMEND"
    view = AgentViewV1(
        view_id=_mint_view_id(subject, summary, source_sha),
        subject=subject,
        stance=stance,
        summary=summary,
        confidence=float(confidence),
        citations=list(citations),
        uncertainty=uncertainty or ("insufficient_evidence" if not citations else ""),
        cost_class=cost_class,
        source_sha=source_sha,
        produced_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    return critic_pass(view)


def persist_allowed(view: AgentViewV1) -> bool:
    return bool(view.critic_pass and view.mbi_behavior == 0 and not view.to_dict()["sizes_or_executes_trades"])
