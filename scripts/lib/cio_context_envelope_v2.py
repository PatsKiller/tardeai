"""CIOContextEnvelope@v2 overlay — shared by office agents, nested in v1.

Does not replace ContextEnvelope@v1 required keys.
"""
from __future__ import annotations

from typing import Any

from scripts.lib.cio_persistent_cognition import (
    AUTH_BELIEF,
    AUTH_FINANCIAL,
    AUTH_HISTORICAL,
    AUTH_OPERATOR,
    AUTH_POLICY,
    AUTH_RESEARCH,
    build_cio_cognition,
    cross_agent_row,
    resolve_cognition_root,
)

# M3 contracts — consume, do not duplicate.
try:
    from scripts.lib.agent_episode import SCHEMA as EPISODE_SCHEMA  # noqa: F401
    from scripts.lib.memory_consolidator import SCHEMA as CONSOLIDATOR_SCHEMA  # noqa: F401
except Exception:  # pragma: no cover
    EPISODE_SCHEMA = None
    CONSOLIDATOR_SCHEMA = None

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CIOContextEnvelope@v2"
AGENTS = ("hermes", "alex", "advisory", "telegram", "maria", "steph", "aegis", "weekly_cio_learning")
SECTIONS = (
    "OFFICE_TRUTH",
    "POLICY",
    "PORTFOLIO_THESIS",
    "TICKER_RESEARCH_STATE",
    "CURATION",
    "SYMBOL_THESIS",
    "RESEARCH_GAPS",
    "CONTRADICTIONS",
    "EPISODIC_CONTEXT",
    "SEMANTIC_OPERATOR_MEMORY",
    "OUTCOMES",
    "LESSONS",
    "RAG_SUPPORT",
    "RAG_COUNTER",
    "MEMORY_RETRIEVAL_UNITS",
)


def same_brain(root, symbols: list[str], *, held: set[str] | None = None) -> dict[str, Any]:
    rows = {s: cross_agent_row(root, s, held=held or set()) for s in symbols}
    consistent = all(r.get("consistent") for r in rows.values())
    return {
        "schema": "SameBrainAcceptance@v1",
        "agents": list(AGENTS),
        "symbols": rows,
        "consistent": consistent,
        "divergences": [s for s, r in rows.items() if not r.get("consistent")],
        "authority": AUTHORITY,
        "telegram_fork": False,
        "financial_action": False,
    }


def attach_v2(envelope: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    """Nest v2 without dropping v1 required sections."""
    out = dict(envelope)
    research = dict(out.get("research_memory") or {})
    research["cio_context_v2"] = pack.get("cio_context_v2") or {
        "schema": SCHEMA,
        "sections": {k: {"authority": AUTH_RESEARCH if k != "OFFICE_TRUTH" else AUTH_FINANCIAL} for k in SECTIONS},
        "authority": AUTHORITY,
        "overrides_office_truth": False,
    }
    out["research_memory"] = research
    return out


def office_pack(root, symbols: list[str], *, agent: str, held: list[str] | None = None) -> dict[str, Any]:
    if agent not in AGENTS and agent not in {"cio", "alex"}:
        agent = "alex"
    return build_cio_cognition(root, symbols, held=held, agent=agent, task="context_envelope_v2")
