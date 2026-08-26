"""Canonical L0-L7 capability maturity contract for Trade AI."""
from __future__ import annotations

from typing import Any


MATURITY_LEVELS: tuple[dict[str, Any], ...] = (
    {"level": 0, "code": "ABSENT", "live_gate": "No usable artifact exists."},
    {"level": 1, "code": "ARTIFACT", "live_gate": "An implementation artifact exists."},
    {"level": 2, "code": "DURABLE", "live_gate": "State survives the required restart boundary."},
    {"level": 3, "code": "GOVERNED", "live_gate": "Queryable provenance and authority controls are live."},
    {"level": 4, "code": "STATEFUL_REASONING", "live_gate": "Prior governed context changes the next cycle."},
    {"level": 5, "code": "FEEDBACK_LEARNING", "live_gate": "Feedback and outcomes complete a measured loop."},
    {"level": 6, "code": "CROSS_AGENT_PROACTIVE", "live_gate": "Cross-agent state drives material proactive review."},
    {
        "level": 7,
        "code": "INSTITUTIONAL_AUTONOMOUS_PROVEN",
        "live_gate": "Natural, causal, explainable, recoverable operation is proven over time.",
    },
)


def maturity_level(level: int | None, *, evidence: list[str] | None = None) -> dict[str, Any]:
    """Return a maturity receipt; missing evidence stays UNMEASURED."""
    if level is None:
        return {"level": None, "code": "UNMEASURED", "evidence": evidence or []}
    if not isinstance(level, int) or not 0 <= level <= 7:
        raise ValueError("maturity level must be an integer from 0 through 7")
    definition = dict(MATURITY_LEVELS[level])
    definition["evidence"] = list(evidence or [])
    return definition


def maturity_contract() -> dict[str, Any]:
    return {
        "schema": "TradeAIMaturityContract@v1",
        "missing_evidence": "UNMEASURED",
        "levels": [dict(row) for row in MATURITY_LEVELS],
    }
