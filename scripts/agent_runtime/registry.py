from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .contracts import AgentDefinition, BudgetPolicy, DeploymentState


class RegistryError(ValueError):
    pass


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RegistryError("tool and job lists must be JSON arrays")
    return tuple(str(item) for item in value)


def definition_from_mapping(agent_id: str, raw: Mapping[str, Any]) -> AgentDefinition:
    budget_raw = raw.get("budget") or {}
    if not isinstance(budget_raw, Mapping):
        raise RegistryError(f"{agent_id}.budget must be an object")
    try:
        state = DeploymentState(str(raw.get("deployment_state", "DESIGNED")))
    except ValueError as exc:
        raise RegistryError(f"invalid deployment state for {agent_id}") from exc
    definition = AgentDefinition(
        agent_id=agent_id,
        display_name=str(raw.get("display_name") or agent_id),
        role=str(raw.get("role") or ""),
        version=str(raw.get("version") or ""),
        owner=str(raw.get("owner") or ""),
        allowed_job_types=_tuple(raw.get("allowed_job_types")),
        allowed_tools=_tuple(raw.get("allowed_tools")),
        denied_tools=_tuple(raw.get("denied_tools")),
        retrieval_required=bool(raw.get("retrieval_required", True)),
        budget=BudgetPolicy(
            max_model_calls=int(budget_raw.get("max_model_calls", 3)),
            max_tool_calls=int(budget_raw.get("max_tool_calls", 12)),
            max_cost_usd=float(budget_raw.get("max_cost_usd", 0.0)),
            deadline_seconds=int(budget_raw.get("deadline_seconds", 360)),
        ),
        deployment_state=state,
        enabled=bool(raw.get("enabled", False)),
    )
    definition.validate()
    return definition


def load_registry(path: str | Path) -> dict[str, AgentDefinition]:
    registry_path = Path(path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "trade-ai-agent-runtime-mvl-v1":
        raise RegistryError("unsupported agent registry schema")
    raw_agents = payload.get("agents")
    if not isinstance(raw_agents, Mapping) or not raw_agents:
        raise RegistryError("registry must define agents")
    definitions = {
        str(agent_id): definition_from_mapping(str(agent_id), raw)
        for agent_id, raw in raw_agents.items()
        if isinstance(raw, Mapping)
    }
    if set(definitions) != set(raw_agents):
        raise RegistryError("every agent entry must be an object")
    return definitions
