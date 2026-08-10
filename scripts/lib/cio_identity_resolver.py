"""
Gate-B: Agent Identity Alias Resolver.

Resolves split identities for Guardian (risk_agent) and Ledger (tax_agent).
The canonical financial-agent IDs are guardian and ledger. risk_agent and
tax_agent are legacy aliases.

Do not promote either agent from NOT_READY during Gate B.
Do not delete historical OpenClaw/workspace directories.
"""
from __future__ import annotations

from typing import Optional

# ── Canonical identity mapping ──────────────────────────────────────────────
# Legacy alias → canonical ID (one business role, one identity)

CANONICAL_IDENTITY: dict[str, str] = {
    "risk_agent": "guardian",
    "tax_agent": "ledger",
    "guardian": "guardian",
    "ledger": "ledger",
}

# Display names for canonical identities
IDENTITY_DISPLAY: dict[str, str] = {
    "guardian": "Guardian Risk",
    "ledger": "Ledger Tax",
}

# Fleet agent IDs (for systemd/live_providers references)
FLEET_ID_MAP: dict[str, str] = {
    "guardian": "risk_agent",  # fleet uses risk_agent for systemd reference
    "ledger": "ledger",
}

# Handoff queue agent IDs (for specialist routing)
HANDOFF_QUEUE_ID_MAP: dict[str, str] = {
    "guardian": "guardian",
    "ledger": "ledger",
}

# Maturity catalog keys
MATURITY_CATALOG_KEYS: dict[str, str] = {
    "guardian": "risk_agent",
    "ledger": "tax_agent",
}

# LLM process registry IDs
PROCESS_REGISTRY_IDS: dict[str, str] = {
    "guardian": "guardian_risk_critique",
    "ledger": "ledger_tax_critique",
}


def resolve_canonical_id(agent_id: str) -> str:
    """Resolve any agent ID to its canonical identity.
    
    risk_agent → guardian
    tax_agent → ledger
    guardian → guardian
    ledger → ledger
    unknown → returned as-is
    """
    return CANONICAL_IDENTITY.get(agent_id, agent_id)


def get_display_name(canonical_id: str) -> str:
    """Get the display name for a canonical identity."""
    return IDENTITY_DISPLAY.get(canonical_id, canonical_id)


def get_fleet_id(canonical_id: str) -> str:
    """Get the fleet agent ID for a canonical identity."""
    return FLEET_ID_MAP.get(canonical_id, canonical_id)


def get_handoff_queue_id(canonical_id: str) -> str:
    """Get the handoff queue agent ID for a canonical identity."""
    return HANDOFF_QUEUE_ID_MAP.get(canonical_id, canonical_id)


def get_maturity_catalog_key(canonical_id: str) -> str:
    """Get the maturity catalog key for a canonical identity."""
    return MATURITY_CATALOG_KEYS.get(canonical_id, canonical_id)


def get_process_registry_id(canonical_id: str) -> str:
    """Get the LLM process registry ID for a canonical identity."""
    return PROCESS_REGISTRY_IDS.get(canonical_id, canonical_id)


def is_financial_agent(agent_id: str) -> bool:
    """Check if an agent is one of the six governed financial agents."""
    canonical = resolve_canonical_id(agent_id)
    return canonical in ("alex", "maria", "steph", "guardian", "ledger", "morgan")


def is_specialist(agent_id: str) -> bool:
    """Check if an agent is a professional specialist (not CIO)."""
    canonical = resolve_canonical_id(agent_id)
    return canonical in ("maria", "steph", "guardian", "ledger", "morgan")
