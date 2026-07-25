"""Read-only agent maturity and monitoring contracts.

This module is intentionally persistence-agnostic. It validates the versioned
agent maturity catalog and projects deterministic fixture/read-model payloads
for Command Center work while the authoritative persistence adapter is reviewed
on a separate branch.

It never opens a database connection, imports a provider SDK, controls a
service, or represents broker/order/approval/2FA authority.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import canonical_hash


CATALOG_SCHEMA = "trade-ai-agent-maturity-catalog-v1"
MONITORING_CONTRACT = "agent-runtime-monitoring-v1"
ALLOWED_DEPLOYMENT_STATES = frozenset(
    {"DESIGNED", "SHADOW", "OPERATIONAL", "RESTRICTED", "RETOOL", "RETIRED"}
)
CANONICAL_AGENT_IDS = frozenset(
    {
        "sentinel",
        "darwin",
        "iris",
        "reflection",
        "argus",
        "maria",
        "vega",
        "pulse",
        "steph",
        "risk_agent",
        "tax_agent",
        "hermes",
        "aegis",
        "alex",
        "concierge",
        "atlas",
    }
)
REQUIRED_AUTHORITY_KEYS = frozenset(
    {
        "broker_authority",
        "order_authority",
        "approval_authority",
        "two_factor_authority",
        "production_config_promotion",
        "production_secret_access",
        "production_database_write",
        "service_control",
    }
)
REQUIRED_AGENT_FIELDS = frozenset(
    {
        "display_name",
        "objective",
        "owner",
        "version",
        "deployment_state",
        "maturity_target",
        "allowed_job_types",
        "allowed_tools",
        "denied_tools",
        "retrieval_policy",
        "artifact_schema",
        "review_policy",
        "score_policy",
        "budget",
        "stop_conditions",
        "disable_control",
        "rollback_control",
        "current_limitations",
        "acceptance_evidence",
        "authority",
    }
)
RUN_STATES = (
    "RUNNING",
    "BLOCKED",
    "FAILED",
    "STALE",
    "CANCELLED",
    "DEADLINE_EXCEEDED",
    "COMPLETED",
)


class MonitoringContractError(ValueError):
    """Raised when a maturity or monitoring contract is incomplete or unsafe."""


def _string_tuple(value: Any, *, field: str, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise MonitoringContractError(f"{field} must be a JSON array")
    items = tuple(str(item).strip() for item in value)
    if any(not item for item in items):
        raise MonitoringContractError(f"{field} cannot contain empty values")
    if not allow_empty and not items:
        raise MonitoringContractError(f"{field} must contain at least one value")
    return items


def _required_text(raw: Mapping[str, Any], field: str, *, agent_id: str) -> str:
    value = str(raw.get(field) or "").strip()
    if not value:
        raise MonitoringContractError(f"{agent_id}.{field} is required")
    return value


def _validate_authority(raw: Any, *, scope: str) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise MonitoringContractError(f"{scope}.authority must be an object")
    missing = REQUIRED_AUTHORITY_KEYS.difference(raw)
    if missing:
        raise MonitoringContractError(
            f"{scope}.authority missing keys: {sorted(missing)}"
        )
    authority = {key: str(raw[key]).upper() for key in REQUIRED_AUTHORITY_KEYS}
    not_denied = {key: value for key, value in authority.items() if value != "DENIED"}
    if not_denied:
        raise MonitoringContractError(
            f"{scope} exposes forbidden authority: {not_denied}"
        )
    return authority


@dataclass(frozen=True)
class AgentMaturityRecord:
    agent_id: str
    display_name: str
    objective: str
    owner: str
    version: str
    deployment_state: str
    maturity_target: str
    allowed_job_types: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    denied_tools: tuple[str, ...]
    retrieval_required: bool
    contradiction_search_required: bool
    provenance_required: bool
    artifact_schema: str
    review_policy: str
    score_policy: str
    max_model_calls: int
    max_tool_calls: int
    max_cost_usd: float
    deadline_seconds: int
    stop_conditions: tuple[str, ...]
    disable_control: str
    rollback_control: str
    current_limitations: tuple[str, ...]
    acceptance_evidence: tuple[str, ...]
    authority: Mapping[str, str]

    def as_read_model(self) -> dict[str, Any]:
        """Return the stable read model consumed by API/UI adapters."""
        payload = {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "objective": self.objective,
            "owner": self.owner,
            "version": self.version,
            "deployment_state": self.deployment_state,
            "maturity_target": self.maturity_target,
            "allowed_job_types": list(self.allowed_job_types),
            "allowed_tools": list(self.allowed_tools),
            "denied_tools": list(self.denied_tools),
            "retrieval_policy": {
                "required": self.retrieval_required,
                "contradiction_search_required": self.contradiction_search_required,
                "provenance_required": self.provenance_required,
            },
            "artifact_schema": self.artifact_schema,
            "review_policy": self.review_policy,
            "score_policy": self.score_policy,
            "budget": {
                "max_model_calls": self.max_model_calls,
                "max_tool_calls": self.max_tool_calls,
                "max_cost_usd": self.max_cost_usd,
                "deadline_seconds": self.deadline_seconds,
            },
            "stop_conditions": list(self.stop_conditions),
            "disable_control": self.disable_control,
            "rollback_control": self.rollback_control,
            "current_limitations": list(self.current_limitations),
            "acceptance_evidence": list(self.acceptance_evidence),
            "authority": dict(self.authority),
        }
        return {**payload, "definition_hash": canonical_hash(payload)}


def record_from_mapping(agent_id: str, raw: Mapping[str, Any]) -> AgentMaturityRecord:
    missing_fields = set(REQUIRED_AGENT_FIELDS).difference(raw)
    if missing_fields:
        raise MonitoringContractError(
            f"{agent_id} missing fields: {sorted(missing_fields)}"
        )
    state = _required_text(raw, "deployment_state", agent_id=agent_id).upper()
    if state not in ALLOWED_DEPLOYMENT_STATES:
        raise MonitoringContractError(
            f"{agent_id}.deployment_state is invalid: {state}"
        )

    retrieval = raw.get("retrieval_policy")
    if not isinstance(retrieval, Mapping):
        raise MonitoringContractError(f"{agent_id}.retrieval_policy must be an object")
    for key in ("required", "contradiction_search_required", "provenance_required"):
        if key not in retrieval or not isinstance(retrieval[key], bool):
            raise MonitoringContractError(
                f"{agent_id}.retrieval_policy.{key} must be boolean"
            )

    budget = raw.get("budget")
    if not isinstance(budget, Mapping):
        raise MonitoringContractError(f"{agent_id}.budget must be an object")
    try:
        max_model_calls = int(budget["max_model_calls"])
        max_tool_calls = int(budget["max_tool_calls"])
        max_cost_usd = float(budget["max_cost_usd"])
        deadline_seconds = int(budget["deadline_seconds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MonitoringContractError(
            f"{agent_id}.budget is incomplete or invalid"
        ) from exc
    if max_model_calls < 0 or max_tool_calls < 0 or max_cost_usd < 0:
        raise MonitoringContractError(f"{agent_id}.budget must be non-negative")
    if not 1 <= deadline_seconds <= 86_400:
        raise MonitoringContractError(
            f"{agent_id}.budget.deadline_seconds must be 1..86400"
        )

    allowed = _string_tuple(raw.get("allowed_tools"), field=f"{agent_id}.allowed_tools")
    denied = _string_tuple(
        raw.get("denied_tools"), field=f"{agent_id}.denied_tools", allow_empty=True
    )
    overlap = sorted(set(allowed).intersection(denied))
    if overlap:
        raise MonitoringContractError(
            f"{agent_id} tools cannot be both allowed and denied: {overlap}"
        )

    authority = _validate_authority(raw.get("authority"), scope=agent_id)
    record = AgentMaturityRecord(
        agent_id=agent_id,
        display_name=_required_text(raw, "display_name", agent_id=agent_id),
        objective=_required_text(raw, "objective", agent_id=agent_id),
        owner=_required_text(raw, "owner", agent_id=agent_id),
        version=_required_text(raw, "version", agent_id=agent_id),
        deployment_state=state,
        maturity_target=_required_text(raw, "maturity_target", agent_id=agent_id),
        allowed_job_types=_string_tuple(
            raw.get("allowed_job_types"), field=f"{agent_id}.allowed_job_types"
        ),
        allowed_tools=allowed,
        denied_tools=denied,
        retrieval_required=bool(retrieval["required"]),
        contradiction_search_required=bool(
            retrieval["contradiction_search_required"]
        ),
        provenance_required=bool(retrieval["provenance_required"]),
        artifact_schema=_required_text(raw, "artifact_schema", agent_id=agent_id),
        review_policy=_required_text(raw, "review_policy", agent_id=agent_id),
        score_policy=_required_text(raw, "score_policy", agent_id=agent_id),
        max_model_calls=max_model_calls,
        max_tool_calls=max_tool_calls,
        max_cost_usd=max_cost_usd,
        deadline_seconds=deadline_seconds,
        stop_conditions=_string_tuple(
            raw.get("stop_conditions"), field=f"{agent_id}.stop_conditions"
        ),
        disable_control=_required_text(raw, "disable_control", agent_id=agent_id),
        rollback_control=_required_text(raw, "rollback_control", agent_id=agent_id),
        current_limitations=_string_tuple(
            raw.get("current_limitations"), field=f"{agent_id}.current_limitations"
        ),
        acceptance_evidence=_string_tuple(
            raw.get("acceptance_evidence"), field=f"{agent_id}.acceptance_evidence"
        ),
        authority=authority,
    )
    if record.deployment_state == "OPERATIONAL":
        raise MonitoringContractError(
            f"{agent_id} cannot be represented as OPERATIONAL before acceptance evidence"
        )
    return record


def load_maturity_catalog(path: str | Path) -> dict[str, AgentMaturityRecord]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != CATALOG_SCHEMA:
        raise MonitoringContractError("unsupported maturity catalog schema")
    if payload.get("contract") != MONITORING_CONTRACT:
        raise MonitoringContractError("unsupported monitoring contract")
    if payload.get("environment") not in {"LAB", "SHADOW"}:
        raise MonitoringContractError("maturity catalog must be LAB/SHADOW")
    if payload.get("production_activation_authorized") is not False:
        raise MonitoringContractError("production activation must remain false")
    _validate_authority(payload.get("global_authority"), scope="global")

    raw_agents = payload.get("agents")
    if not isinstance(raw_agents, Mapping):
        raise MonitoringContractError("catalog agents must be an object")
    if set(raw_agents) != CANONICAL_AGENT_IDS:
        missing = sorted(CANONICAL_AGENT_IDS.difference(raw_agents))
        extra = sorted(set(raw_agents).difference(CANONICAL_AGENT_IDS))
        raise MonitoringContractError(
            f"canonical roster mismatch; missing={missing}, extra={extra}"
        )
    definitions: dict[str, AgentMaturityRecord] = {}
    for agent_id, raw in raw_agents.items():
        if not isinstance(raw, Mapping):
            raise MonitoringContractError(f"{agent_id} must be an object")
        definitions[str(agent_id)] = record_from_mapping(str(agent_id), raw)
    return definitions


def project_agent_catalog(
    catalog: Mapping[str, AgentMaturityRecord],
) -> list[dict[str, Any]]:
    return [
        catalog[agent_id].as_read_model()
        for agent_id in sorted(catalog, key=lambda item: (catalog[item].display_name, item))
    ]


def fleet_summary(
    catalog: Mapping[str, AgentMaturityRecord],
    *,
    runs: Iterable[Mapping[str, Any]] = (),
    artifacts: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    lifecycle = Counter(record.deployment_state for record in catalog.values())
    run_states = Counter(str(item.get("status") or "UNKNOWN").upper() for item in runs)
    artifact_rows = list(artifacts)
    unreviewed = sum(not bool(item.get("reviewed")) for item in artifact_rows)
    unscored = sum(not bool(item.get("scored")) for item in artifact_rows)
    authority_ok = all(
        all(value == "DENIED" for value in record.authority.values())
        for record in catalog.values()
    )
    return {
        "contract": MONITORING_CONTRACT,
        "agent_count": len(catalog),
        "lifecycle_counts": {
            state: lifecycle.get(state, 0) for state in sorted(ALLOWED_DEPLOYMENT_STATES)
        },
        "run_counts": {state: run_states.get(state, 0) for state in RUN_STATES},
        "unknown_run_count": sum(
            count for state, count in run_states.items() if state not in RUN_STATES
        ),
        "artifact_counts": {
            "total": len(artifact_rows),
            "unreviewed": unreviewed,
            "unscored": unscored,
        },
        "authority": {
            "all_forbidden_capabilities_denied": authority_ok,
            "broker_order_approval_2fa_authority": "DENIED",
            "production_activation_authorized": False,
        },
    }


def fixture_snapshot(
    catalog: Mapping[str, AgentMaturityRecord],
    *,
    as_of: str,
) -> dict[str, Any]:
    """Fixture-backed snapshot that makes unavailable runtime evidence explicit."""
    payload = {
        "contract": MONITORING_CONTRACT,
        "source_kind": "FIXTURE",
        "environment": "SHADOW",
        "as_of": as_of,
        "data_state": "NOT_RUN",
        "summary": fleet_summary(catalog),
        "agents": project_agent_catalog(catalog),
        "runs": [],
        "artifacts": [],
        "reviews": [],
        "scores": [],
        "cases": [],
        "lessons": [],
        "limitations": [
            "authoritative Postgres read adapter is not integrated",
            "fixture data does not prove operational agent activity",
            "production activation is not authorized",
        ],
    }
    return {**payload, "snapshot_hash": canonical_hash(payload)}


def watch_context_panel(
    catalog: Mapping[str, AgentMaturityRecord],
) -> dict[str, Any]:
    """Bounded read-only agents panel for Watch; no page-decision authority."""
    agent_ids = ("sentinel", "argus", "darwin", "reflection", "iris")
    return {
        "contract": "watch-agent-context-v1",
        "source_kind": "FIXTURE",
        "read_only": True,
        "sovereign_decision_mutation": False,
        "actions": [],
        "agents": [catalog[agent_id].as_read_model() for agent_id in agent_ids],
        "runtime_state": "NOT_RUN",
        "limitations": [
            "no authoritative run/artifact/review/score rows are connected",
            "context panel cannot change Watch quality admission or ticket state",
        ],
    }
