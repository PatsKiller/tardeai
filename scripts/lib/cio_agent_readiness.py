"""
CIO Agent Readiness Registry — Single authoritative source for specialist maturity.

Reads config/agent_maturity_catalog.json as the canonical persistence.
Provides AgentReadinessRegistry as the single query point.

Gate-C component. Replaces triple-source inconsistency with one authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class AgentReadiness:
    """Typed readiness view for a single agent."""
    agent_id: str
    canonical_identity: str
    display_name: str
    maturity_stage: str       # DESIGNED | SHADOW | etc — separate from readiness
    readiness_state: str      # NOT_READY | READY_FOR_HANDOFF | SUSPENDED
    enabled: bool
    task_capabilities: list[str] = field(default_factory=list)
    deterministic_sources: list[str] = field(default_factory=list)
    governed_gateway_process: Optional[str] = None
    gateway_policy: Optional[str] = None
    artifact_schema: Optional[str] = None
    bounded_tools: list[str] = field(default_factory=list)
    prohibited_authorities: list[str] = field(default_factory=list)
    handoff_claim_capable: bool = False
    handoff_completion_capable: bool = False
    parent_run_id_persistent: bool = False
    same_run_resume_capable: bool = False
    live_canary_active: bool = False
    canary_status: Optional[str] = None      # NOT_RUN | PASS | FAIL | EXPIRED
    canary_last_verified_at: Optional[str] = None
    readiness_version: Optional[str] = None
    promotion_blockers: list[str] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    authority: dict[str, str] = field(default_factory=dict)
    stop_conditions: list[str] = field(default_factory=list)
    advisory_schema_readiness: str = ""  # SCHEMA_DEFINED | SCHEMA_VALIDATED | LIVE_OUTPUT_VALIDATED | ""

    @property
    def is_not_ready(self) -> bool:
        return self.readiness_state == "NOT_READY"

    @property
    def is_ready_for_handoff(self) -> bool:
        return self.readiness_state == "READY_FOR_HANDOFF" and self.handoff_claim_capable

    @property
    def canary_passed(self) -> bool:
        """Canary must be active AND have passed to count as verified."""
        return self.live_canary_active and self.canary_status == "PASS"


class AgentReadinessRegistry:
    """Single authoritative readiness projection for all agents.
    
    Reads config/agent_maturity_catalog.json at startup.
    All other representations (AGENT_REGISTRY, definitions.py) must become
    generated aliases of this registry — not independently writable copies.
    """

    _instance: Optional[AgentReadinessRegistry] = None

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw
        self._agents: dict[str, AgentReadiness] = {}
        self._parse_agents(raw.get("agents", {}))
        self._catalog_hash = self._compute_hash()

    def _parse_agents(self, agents_raw: dict[str, Any]) -> None:
        for agent_id, a in agents_raw.items():
            dep_state = a.get("deployment_state", "DESIGNED")
            maturity_stage = dep_state  # DESIGNED, SHADOW, etc.
            
            # Derive readiness from deployment_state + enabled
            enabled = dep_state in ("SHADOW",) or a.get("enabled", False)
            readiness = "NOT_READY"
            if dep_state == "SHADOW" and enabled:
                readiness = "NOT_READY"  # SHADOW agents still NOT_READY for production
            
            self._agents[agent_id] = AgentReadiness(
                agent_id=agent_id,
                canonical_identity=a.get("canonical_identity", agent_id),
                display_name=a.get("display_name", agent_id),
                maturity_stage=maturity_stage,
                readiness_state=readiness,
                enabled=enabled,
                task_capabilities=a.get("allowed_job_types", []),
                deterministic_sources=a.get("deterministic_sources", []),
                governed_gateway_process=a.get("governed_gateway_process"),
                gateway_policy=a.get("gateway_policy"),
                artifact_schema=a.get("artifact_schema"),
                bounded_tools=a.get("allowed_tools", []),
                prohibited_authorities=["order_authority", "broker_authority"],
                handoff_claim_capable=dep_state in ("SHADOW",),
                handoff_completion_capable=dep_state in ("SHADOW",),
                parent_run_id_persistent=False,
                same_run_resume_capable=False,
                live_canary_active=dep_state in ("SHADOW",),
                canary_status="NOT_RUN",
                readiness_version=a.get("version", "1.0.0"),
                promotion_blockers=a.get("current_limitations", []),
                budget=a.get("budget", {}),
                authority=a.get("authority", {}),
                stop_conditions=a.get("stop_conditions", []),
            )

    def _compute_hash(self) -> str:
        canonical = json.dumps(self._raw, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> AgentReadinessRegistry:
        if config_path is None:
            config_path = str(
                Path(__file__).resolve().parents[2]
                / "config"
                / "agent_maturity_catalog.json"
            )
        with open(config_path) as f:
            raw = json.load(f)
        instance = cls(raw)
        cls._instance = instance
        return instance

    @classmethod
    def get_instance(cls) -> AgentReadinessRegistry:
        if cls._instance is None:
            raise RuntimeError("AgentReadinessRegistry not loaded")
        return cls._instance

    @property
    def catalog_hash(self) -> str:
        return self._catalog_hash

    @property
    def catalog_version(self) -> str:
        return self._raw.get("_version", "1.0.0")

    def get(self, agent_id: str) -> AgentReadiness:
        if agent_id not in self._agents:
            raise KeyError(f"Unknown agent: {agent_id}")
        return self._agents[agent_id]

    def has(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def all_agents(self) -> dict[str, AgentReadiness]:
        return dict(self._agents)

    def ready_agents(self) -> list[str]:
        return [a.agent_id for a in self._agents.values() if a.is_ready_for_handoff]

    def can_enqueue(self, agent_id: str) -> tuple[bool, str]:
        """Check if an agent can receive handoffs. Returns (allowed, reason)."""
        try:
            agent = self.get(agent_id)
        except KeyError:
            return False, "UNKNOWN_AGENT"
        if not agent.enabled:
            return False, f"AGENT_DISABLED:maturity={agent.maturity_stage}"
        if agent.is_not_ready:
            return False, f"AGENT_NOT_READY:maturity={agent.maturity_stage}"
        if not agent.handoff_claim_capable:
            return False, "HANDOFF_CLAIM_NOT_CAPABLE"
        return True, "READY"

    def can_claim(self, agent_id: str, claimed_at_catalog_hash: Optional[str] = None) -> tuple[bool, str]:
        """Check if agent can claim a handoff. Includes catalog version check."""
        allowed, reason = self.can_enqueue(agent_id)
        if not allowed:
            return False, reason
        if claimed_at_catalog_hash and claimed_at_catalog_hash != self._catalog_hash:
            return False, "CATALOG_VERSION_CHANGED:readiness may have changed since enqueue"
        try:
            agent = self.get(agent_id)
            if agent.live_canary_active and agent.canary_status == "FAIL":
                return False, "CANARY_FAILED"
            if agent.live_canary_active and agent.canary_status == "EXPIRED":
                return False, "CANARY_EXPIRED"
        except KeyError:
            return False, "AGENT_REMOVED_FROM_CATALOG"
        return True, "READY"

    @staticmethod
    def get_advisory_schema_readiness() -> str:
        """Return the current advisory-schema readiness tier.

        Delegates to CIOSpecialistAdvisoryReadiness which distinguishes three
        tiers: SCHEMA_DEFINED (class exists), SCHEMA_VALIDATED (validation
        functions pass offline), and LIVE_OUTPUT_VALIDATED (proven via live
        specialist canary output).

        Returns one of: SCHEMA_DEFINED | SCHEMA_VALIDATED | LIVE_OUTPUT_VALIDATED
        or an empty string if the readiness module is unavailable.
        """
        try:
            from scripts.lib.cio_advisory_readiness import CIOSpecialistAdvisoryReadiness
            return CIOSpecialistAdvisoryReadiness.advisory_schema_tier()
        except ImportError:
            return ""

    @classmethod
    def get_readiness(cls, agent_id: str) -> dict:
        """Return a readiness summary dict for a single agent.

        Includes the advisory schema readiness tier alongside the standard
        AgentReadiness fields.  This is the recommended single-query entry
        point for Gate-D promotion checks.
        """
        try:
            instance = cls.get_instance()
            agent = instance.get(agent_id)
        except (RuntimeError, KeyError):
            return {
                "agent_id": agent_id,
                "found": False,
                "readiness_state": "UNKNOWN",
                "advisory_schema_readiness": cls.get_advisory_schema_readiness(),
            }

        return {
            "agent_id": agent.agent_id,
            "found": True,
            "display_name": agent.display_name,
            "maturity_stage": agent.maturity_stage,
            "readiness_state": agent.readiness_state,
            "enabled": agent.enabled,
            "artifact_schema": agent.artifact_schema,
            "governed_gateway_process": agent.governed_gateway_process,
            "advisory_schema_readiness": cls.get_advisory_schema_readiness(),
            "handoff_claim_capable": agent.handoff_claim_capable,
            "canary_status": agent.canary_status,
            "promotion_blockers": agent.promotion_blockers,
        }
