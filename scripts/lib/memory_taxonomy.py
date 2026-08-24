"""TradeAIMemoryTaxonomy@v2 — one primary plane per persistent object.

READ_ONLY_ADVISORY. MEMORY_BEHAVIOR_INFLUENCE=0.
Memory is context/history/learning evidence. Never broker/position/cash/price/order/stop/2FA truth.
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "TradeAIMemoryTaxonomy@v2"

PLANE_WORKING = "WORKING_SESSION"
PLANE_EPISODIC = "EPISODIC"
PLANE_SEMANTIC = "SEMANTIC_OPERATOR"
PLANE_POLICY = "CANONICAL_POLICY_BELIEF"
PLANE_RAG = "DOCUMENT_EVIDENCE_RAG"
PLANE_PROCEDURAL = "PROCEDURAL_LESSON"
PLANE_ORCHESTRATION = "ORCHESTRATION_HISTORY"

PLANES = (
    PLANE_WORKING,
    PLANE_EPISODIC,
    PLANE_SEMANTIC,
    PLANE_POLICY,
    PLANE_RAG,
    PLANE_PROCEDURAL,
    PLANE_ORCHESTRATION,
)

AIF_CLASSES = (
    "RESEARCH_POINTER",
    "EPISODIC",
    "SEMANTIC_OPERATOR",
    "POLICY_POINTER",
    "LESSON_POINTER",
    "QUARANTINED",
)


def classify_aif_row(row: dict[str, Any]) -> str:
    """Classify a durable AIF memory row. Research prose is a pointer, not operator semantics."""
    if not isinstance(row, dict):
        return "QUARANTINED"
    kind = str(row.get("kind") or row.get("memory_kind") or row.get("type") or "").upper()
    purpose = str(row.get("purpose") or row.get("role") or row.get("category") or "").upper()
    blob = " ".join(str(row.get(k) or "") for k in ("text", "body", "content", "summary", "title")).lower()
    if any(s in blob for s in ("ignore previous", "api key", "password", "2fa", "place order", "cancel stop")):
        return "QUARANTINED"
    if "RESEARCH" in kind or "RESEARCH" in purpose or purpose == "RESEARCH_REFERENCE" or kind == "RESEARCH_REFERENCE":
        return "RESEARCH_POINTER"
    if "LESSON" in kind or "LESSON" in purpose or "CANON" in kind:
        return "LESSON_POINTER"
    if "POLICY" in kind or "POLICY" in purpose or "IPS" in kind:
        return "POLICY_POINTER"
    if "EPISODE" in kind or "WAKE" in kind or "TRACE" in kind:
        return "EPISODIC"
    if "PREFERENCE" in kind or "OPERATOR" in kind or "SEMANTIC" in kind:
        return "SEMANTIC_OPERATOR"
    # Default: unconfirmed research-shaped rows are pointers, not operator knowledge.
    if row.get("status") in ("CANDIDATE", None) and (row.get("source") or row.get("url") or "http" in blob):
        return "RESEARCH_POINTER"
    return "RESEARCH_POINTER"


def plane_for_schema(schema: str | None) -> str:
    s = str(schema or "")
    mapping = {
        "TickerResearchArtifact@v1": PLANE_RAG,
        "TickerKnowledgeProfile@v1": PLANE_POLICY,
        "TickerResearchState@v1": PLANE_POLICY,
        "HermesCurationSummary@v1": PLANE_POLICY,
        "BaselineCurationSnapshot@v1": PLANE_POLICY,
        "ResearchGap@v1": PLANE_EPISODIC,
        "EvidenceContradiction@v1": PLANE_EPISODIC,
        "OperatorInvestmentPolicy@v1": PLANE_POLICY,
        "CIOPortfolioThesis@v1": PLANE_POLICY,
        "SymbolThesis@v1": PLANE_POLICY,
        "AgentEpisode@v1": PLANE_EPISODIC,
        "MemoryFact@v2": PLANE_SEMANTIC,
        "PreferenceCandidate@v1": PLANE_SEMANTIC,
        "LessonCandidate@v1": PLANE_PROCEDURAL,
        "OutcomeRecord@v1": PLANE_EPISODIC,
        "OperatorFeedback@v1": PLANE_EPISODIC,
        "FreeFirstCirculationReport@v1": PLANE_ORCHESTRATION,
        "ContextEnvelope@v1": PLANE_WORKING,
        "ContextEnvelope@v2": PLANE_WORKING,
        "AgentThread@v1": PLANE_WORKING,
        "SessionCheckpoint@v1": PLANE_WORKING,
    }
    return mapping.get(s, PLANE_ORCHESTRATION)


def taxonomy() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
        "financial_action": False,
        "planes": list(PLANES),
        "aif_classes": list(AIF_CLASSES),
        "never": [
            "broker_truth",
            "position_truth",
            "cash_truth",
            "price_truth",
            "order_truth",
            "stop_truth",
            "risk_truth",
            "2fa_truth",
            "execution_authority",
        ],
    }
