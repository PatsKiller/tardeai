"""Read-only agent maturity observability contract.

This module normalizes repository evidence into a versioned maturity scoreboard.
It intentionally performs no broker calls, no provider calls, no database writes,
no runtime-state writes, and no authority changes.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import FORBIDDEN_TOOL_PREFIXES

SCHEMA_VERSION = "agent-maturity-observation-v1"
API_CONTRACT = "agent-maturity-read-api-v1"
PROMOTION_AUTHORITY = "HUMAN_ONLY"
AUTOMATIC_PROMOTION_PERMITTED = False

REVIEW_PROVENANCE = {
    "MODEL_REVIEW",
    "DETERMINISTIC_FALLBACK",
    "CACHED_MODEL_REVIEW",
    "MANUAL_REVIEW",
    "NOT_RUN",
    "UNKNOWN",
}
REVIEW_HEALTH = {
    "HEALTHY",
    "DEGRADED_FALLBACK",
    "TIMEOUT",
    "STALE_CACHE",
    "MISSING_REVIEWER",
    "INCOMPLETE_CONSENSUS",
    "PROVIDER_UNAVAILABLE",
    "INVALID_OUTPUT",
    "NOT_RUN",
    "UNKNOWN",
}
GATE_STATE = {
    "PASSED",
    "FAILED",
    "CAPPED_BY_SAMPLE_SIZE",
    "INSUFFICIENT_EVIDENCE",
    "STALE",
    "NOT_RUN",
    "NOT_APPLICABLE",
    "UNKNOWN",
}
PROMOTION_ELIGIBILITY = {
    "NOT_ELIGIBLE",
    "ELIGIBLE_FOR_HUMAN_REVIEW",
    "HUMAN_REVIEW_REQUIRED",
    "RESTRICTED",
    "UNKNOWN",
}

NO_FINANCIAL_AUTHORITY = "NO FINANCIAL AUTHORITY"
RUNTIME_STATUS_UNVERIFIED = "RUNTIME STATUS UNVERIFIED"

CATALOG_PATH = Path("config/agent_maturity_catalog.json")
MVL_PATH = Path("config/agent_runtime_mvl.json")
HERMES_MATURITY_PATH = Path("config/hermes_maturity.yaml")
HERMES_REACTIONS_PATH = Path("config/hermes_reactions.yaml")
HERMES_THRESHOLDS_PATH = Path("config/hermes_thresholds.yaml")

ZERO_AUTHORITY = {
    "mutation": False,
    "provider_call": False,
    "service_control": False,
    "schedule_change": False,
    "financial_action": False,
}


@dataclass
class ReviewEvidence:
    review_provenance: str = "NOT_RUN"
    review_health: str = "NOT_RUN"
    review_model: str | None = None
    review_provider: str | None = None
    review_route: str | None = None
    review_prompt_version: str | None = None
    review_input_hash: str | None = None
    review_response_hash: str | None = None
    last_successful_review_at: str | None = None
    last_degraded_review_at: str | None = None


@dataclass
class MaturityObservation:
    schema_version: str
    observed_at: str
    agent_id: str
    display_name: str
    subsystem: str
    agent_kind: str
    environment: str
    declared_lifecycle_state: str
    effective_authority_state: str
    allowed_authorities: list[str]
    denied_authorities: list[str]
    production_activation_authorized: bool | None
    declared_production_activation_authorized: bool | None
    effective_production_activation_verified: bool
    activation_evidence_state: str
    maturity_framework: str
    maturity_framework_version: str | None
    maturity_score: float | None
    maturity_tier: str | None
    component_scores: dict[str, Any]
    sample_size: int | None
    required_sample_size: int | None
    sample_progress_state: str
    sample_cap_reason: str | None
    next_gate_id: str | None
    next_gate_description: str | None
    next_gate_state: str
    promotion_eligibility: str
    promotion_authority: str
    automatic_promotion_permitted: bool
    review_provenance: str
    review_health: str
    review_model: str | None
    review_provider: str | None
    review_route: str | None
    review_prompt_version: str | None
    review_input_hash: str | None
    review_response_hash: str | None
    last_successful_review_at: str | None
    last_degraded_review_at: str | None
    last_human_authority_change_at: str | None
    last_restriction_or_demotion_at: str | None
    freshness_state: str
    source_class: str
    evidence_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    operator_checks_required: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _authority_summary(allowed: Iterable[str], denied: Iterable[str]) -> tuple[list[str], list[str], list[str]]:
    allowed_list = _dedupe(allowed)
    denied_list = _dedupe([*denied, *FORBIDDEN_TOOL_PREFIXES])
    warnings: list[str] = []
    for tool in allowed_list:
        name = tool.lower()
        if any(name == prefix.rstrip(".") or name.startswith(prefix) for prefix in FORBIDDEN_TOOL_PREFIXES):
            warnings.append(f"forbidden authority appears in allowed tools: {tool}")
    if not warnings:
        denied_list.append(NO_FINANCIAL_AUTHORITY)
    return allowed_list, _dedupe(denied_list), warnings


def _review_evidence_from_record(record: Mapping[str, Any] | None) -> ReviewEvidence:
    if not record:
        return ReviewEvidence()
    provenance = str(record.get("review_provenance") or record.get("narrative_source") or "UNKNOWN").upper()
    health = str(record.get("review_health") or "UNKNOWN").upper()
    cached = bool(record.get("cached"))
    stale = bool(record.get("stale"))
    status = str(record.get("status") or "").lower()
    model = record.get("model") or record.get("model_used")

    if provenance in {"LOCAL_LLM", "MODEL", "LLM"}:
        provenance = "MODEL_REVIEW"
    elif provenance in {"DETERMINISTIC_FALLBACK", "FALLBACK"}:
        provenance = "DETERMINISTIC_FALLBACK"
    elif cached:
        provenance = "CACHED_MODEL_REVIEW"
    elif status == "not_run":
        provenance = "NOT_RUN"
    if provenance not in REVIEW_PROVENANCE:
        provenance = "UNKNOWN"

    if health == "UNKNOWN" or health not in REVIEW_HEALTH:
        if provenance == "DETERMINISTIC_FALLBACK":
            health = "DEGRADED_FALLBACK"
        elif cached and stale:
            health = "STALE_CACHE"
        elif status in {"missing", "not_run"}:
            health = "MISSING_REVIEWER" if status == "missing" else "NOT_RUN"
        elif status in {"timeout", "timed_out"}:
            health = "TIMEOUT"
        elif status in {"invalid", "parse_error"}:
            health = "INVALID_OUTPUT"
        elif status in {"incomplete", "partial"}:
            health = "INCOMPLETE_CONSENSUS"
        elif provenance == "MODEL_REVIEW":
            health = "HEALTHY"
        else:
            health = "UNKNOWN"

    return ReviewEvidence(
        review_provenance=provenance,
        review_health=health,
        review_model=str(model) if model else None,
        review_provider=str(record.get("provider")) if record.get("provider") else None,
        review_route=str(record.get("route")) if record.get("route") else None,
        review_prompt_version=str(record.get("prompt_version")) if record.get("prompt_version") else None,
        review_input_hash=str(record.get("input_hash")) if record.get("input_hash") else None,
        review_response_hash=str(record.get("response_hash")) if record.get("response_hash") else None,
        last_successful_review_at=str(record.get("reviewed_at")) if record.get("reviewed_at") and health == "HEALTHY" else None,
        last_degraded_review_at=str(record.get("reviewed_at")) if record.get("reviewed_at") and health != "HEALTHY" else None,
    )


def _sample_progress_state(sample_size: int | None, required: int | None) -> str:
    if sample_size is None or required is None:
        return "UNKNOWN"
    if sample_size < required:
        return "CAPPED_BY_SAMPLE_SIZE"
    return "MEASURED"


def _gate_state(
    sample_size: int | None,
    required: int | None,
    review: ReviewEvidence,
    *,
    framework_gates_complete: bool = False,
) -> tuple[str, str | None, str]:
    if required is None:
        return "UNKNOWN", "exact framework gate is not available from the current source", "UNKNOWN"
    if sample_size is None:
        return "INSUFFICIENT_EVIDENCE", "sample size is not available", "HUMAN_REVIEW_REQUIRED"
    health = review.review_health
    if health == "NOT_RUN":
        return "NOT_RUN", "review has not run", "NOT_ELIGIBLE"
    if health == "UNKNOWN":
        return "UNKNOWN", "review health is unknown", "UNKNOWN"
    if health == "STALE_CACHE":
        return "STALE", "review evidence is a stale cached result", "HUMAN_REVIEW_REQUIRED"
    if health in {"DEGRADED_FALLBACK", "MISSING_REVIEWER", "INCOMPLETE_CONSENSUS", "PROVIDER_UNAVAILABLE"}:
        return "INSUFFICIENT_EVIDENCE", f"review health is {health}", "HUMAN_REVIEW_REQUIRED"
    if health in {"TIMEOUT", "INVALID_OUTPUT"}:
        return "FAILED", f"review health is {health}", "NOT_ELIGIBLE"
    if health != "HEALTHY":
        return "UNKNOWN", f"review health is {health}", "UNKNOWN"
    if sample_size < required:
        return "CAPPED_BY_SAMPLE_SIZE", f"{sample_size}/{required} reviewed samples", "NOT_ELIGIBLE"
    if not framework_gates_complete:
        return "INSUFFICIENT_EVIDENCE", "remaining framework gates are not measured as passed", "HUMAN_REVIEW_REQUIRED"
    return "PASSED", None, "ELIGIBLE_FOR_HUMAN_REVIEW"


def _observation(
    *,
    observed_at: str,
    agent_id: str,
    display_name: str,
    subsystem: str,
    agent_kind: str,
    environment: str,
    lifecycle: str,
    allowed: Iterable[str],
    denied: Iterable[str],
    framework: str,
    framework_version: str | None,
    sample_size: int | None,
    required_sample_size: int | None = None,
    maturity_score: float | None = None,
    maturity_tier: str | None = None,
    component_scores: Mapping[str, Any] | None = None,
    review: ReviewEvidence | None = None,
    declared_production_activation_authorized: bool | None = None,
    effective_production_activation_verified: bool = False,
    framework_gates_complete: bool = False,
    next_gate_id: str | None = None,
    next_gate_description: str | None = None,
    source_class: str = "REPOSITORY_EVIDENCE",
    evidence_refs: Iterable[str] = (),
    warnings: Iterable[str] = (),
    operator_checks_required: Iterable[str] = (),
) -> MaturityObservation:
    review = review or ReviewEvidence()
    allowed_authorities, denied_authorities, authority_warnings = _authority_summary(allowed, denied)
    gate_state, cap_reason, eligibility = _gate_state(
        sample_size, required_sample_size, review, framework_gates_complete=framework_gates_complete
    )
    sample_progress = _sample_progress_state(sample_size, required_sample_size)
    if lifecycle == "RESTRICTED":
        eligibility = "RESTRICTED"
    if source_class == "UNVERIFIED":
        eligibility = "UNKNOWN"
    effective_authority = "NO_FINANCIAL_AUTHORITY"
    if lifecycle == "RESTRICTED":
        effective_authority = "RESTRICTED"
    elif environment == "SHADOW":
        effective_authority = "SHADOW_READ_OR_ADVISORY_ONLY"
    return MaturityObservation(
        schema_version=SCHEMA_VERSION,
        observed_at=observed_at,
        agent_id=agent_id,
        display_name=display_name,
        subsystem=subsystem,
        agent_kind=agent_kind,
        environment=environment,
        declared_lifecycle_state=lifecycle,
        effective_authority_state=effective_authority,
        allowed_authorities=allowed_authorities,
        denied_authorities=denied_authorities,
        production_activation_authorized=declared_production_activation_authorized,
        declared_production_activation_authorized=declared_production_activation_authorized,
        effective_production_activation_verified=effective_production_activation_verified,
        activation_evidence_state=source_class if declared_production_activation_authorized is not None else "UNVERIFIED",
        maturity_framework=framework,
        maturity_framework_version=framework_version,
        maturity_score=maturity_score,
        maturity_tier=maturity_tier,
        component_scores=dict(component_scores or {}),
        sample_size=sample_size,
        required_sample_size=required_sample_size,
        sample_progress_state=sample_progress,
        sample_cap_reason=cap_reason,
        next_gate_id=next_gate_id,
        next_gate_description=next_gate_description,
        next_gate_state=gate_state,
        promotion_eligibility=eligibility,
        promotion_authority=PROMOTION_AUTHORITY,
        automatic_promotion_permitted=AUTOMATIC_PROMOTION_PERMITTED,
        review_provenance=review.review_provenance,
        review_health=review.review_health,
        review_model=review.review_model,
        review_provider=review.review_provider,
        review_route=review.review_route,
        review_prompt_version=review.review_prompt_version,
        review_input_hash=review.review_input_hash,
        review_response_hash=review.review_response_hash,
        last_successful_review_at=review.last_successful_review_at,
        last_degraded_review_at=review.last_degraded_review_at,
        last_human_authority_change_at=None,
        last_restriction_or_demotion_at=None,
        freshness_state="CURRENT_REPOSITORY_EVIDENCE" if source_class != "UNVERIFIED" else RUNTIME_STATUS_UNVERIFIED,
        source_class=source_class,
        evidence_refs=_dedupe(evidence_refs),
        warnings=_dedupe([*warnings, *authority_warnings]),
        operator_checks_required=_dedupe(operator_checks_required),
    )


def _catalog_payload(root: Path) -> dict[str, Any]:
    path = root / CATALOG_PATH
    if not path.exists():
        return {}
    return _read_json(path)


def _catalog_records(root: Path) -> dict[str, Any]:
    return (_catalog_payload(root).get("agents") or {})


def _mvl_records(root: Path) -> dict[str, Any]:
    path = root / MVL_PATH
    if not path.exists():
        return {}
    payload = _read_json(path)
    return payload.get("agents") or {}


def _declared_sample_size(*sources: Mapping[str, Any]) -> int | None:
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        evidence = source.get("evidence")
        if isinstance(evidence, Mapping):
            for key in ("reviewed_artifacts", "sample_size", "sample_count"):
                if key in evidence and evidence[key] is not None:
                    return int(evidence[key])
        for key in ("sample_size", "sample_count"):
            if key in source and source[key] is not None:
                return int(source[key])
    return None


def _load_agent_runtime_min_artifact_gate() -> dict[str, Any] | None:
    try:
        from .agents.maturity_gates import GATE_SPECS

        gate = next(g for g in GATE_SPECS if g.gate_id == "min_artifact_population")
        return {
            "required_sample_size": int(gate.threshold),
            "next_gate_id": gate.gate_id,
            "next_gate_description": gate.description,
        }
    except Exception:
        return None


def _definition_records() -> dict[str, Any]:
    from .agents.definitions import fleet

    out: dict[str, Any] = {}
    for agent_id, spec in fleet().items():
        definition = spec.definition
        out[agent_id] = {
            "display_name": definition.display_name,
            "subsystem": "agent_runtime_mvl",
            "agent_kind": "shadow_agent",
            "environment": "SHADOW" if definition.enabled else "LAB",
            "lifecycle": str(definition.deployment_state.value),
            "allowed": [*definition.allowed_job_types, *definition.allowed_tools],
            "denied": list(definition.denied_tools),
            "version": definition.version,
        }
    return out


def build_observations(
    root: Path,
    *,
    observed_at: str | None = None,
    review_records: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return canonical maturity observations from safe repository evidence."""
    observed_at = observed_at or utc_now()
    root = Path(root)
    catalog_payload = _catalog_payload(root)
    catalog = catalog_payload.get("agents") or {}
    declared_catalog_activation = (
        bool(catalog_payload["production_activation_authorized"])
        if "production_activation_authorized" in catalog_payload
        else None
    )
    mvl = _mvl_records(root)
    definitions = _definition_records()
    review_records = review_records or {}
    agent_ids = sorted({*catalog.keys(), *mvl.keys(), *definitions.keys(), "hermes", "concierge", "broker_cloud_oversight", "defense_adjudication"})

    observations: list[MaturityObservation] = []
    for agent_id in agent_ids:
        cat = catalog.get(agent_id) or {}
        mvl_agent = mvl.get(agent_id) or {}
        defined = definitions.get(agent_id) or {}
        display = cat.get("display_name") or mvl_agent.get("display_name") or defined.get("display_name") or agent_id.replace("_", " ").title()
        subsystem = defined.get("subsystem") or cat.get("subsystem") or ("hermes" if agent_id == "hermes" else "proposal_review" if agent_id in {"maria", "risk_agent", "steph", "broker_cloud_oversight"} else "agent_runtime")
        lifecycle = str(cat.get("lifecycle") or mvl_agent.get("state") or defined.get("lifecycle") or "DESIGNED").upper()
        enabled = bool(mvl_agent.get("enabled", defined.get("environment") == "SHADOW"))
        environment = str(cat.get("environment") or mvl_agent.get("environment") or ("SHADOW" if enabled else "LAB")).upper()
        allowed = cat.get("allowed_tools") or defined.get("allowed") or []
        denied = [*(cat.get("denied_tools") or []), *(defined.get("denied") or [])]
        sample_size = _declared_sample_size(cat, mvl_agent)
        framework = "agent-runtime-mvl"
        framework_version = "mvl-v1"
        maturity_score = None
        maturity_tier = None
        component_scores: dict[str, Any] = {}
        warnings: list[str] = []
        operator_checks: list[str] = []
        required_sample_size: int | None = None
        next_gate_id: str | None = None
        next_gate_description: str | None = None
        declared_activation = declared_catalog_activation if agent_id in catalog else None
        evidence_refs = [str(CATALOG_PATH), str(MVL_PATH), "scripts/agent_runtime/agents/definitions.py"]

        if framework == "agent-runtime-mvl":
            gate = _load_agent_runtime_min_artifact_gate()
            if gate:
                required_sample_size = gate["required_sample_size"]
                next_gate_id = gate["next_gate_id"]
                next_gate_description = gate["next_gate_description"]
                operator_checks.append("Remaining Agent Runtime MVL gates must be measured and passed before human review eligibility.")
            else:
                required_sample_size = None
                next_gate_id = None
                next_gate_description = None
                operator_checks.append("Agent Runtime minimum artifact gate could not be verified from the authoritative source.")

        if agent_id == "hermes":
            cfg = _read_yaml(root / HERMES_MATURITY_PATH)
            framework = "hermes"
            framework_version = str(cfg.get("version") or "maturity-v2")
            component_scores = {"weights": cfg.get("weights") or {}, "tiers": cfg.get("tiers") or {}}
            evidence_refs = [str(HERMES_MATURITY_PATH), str(HERMES_REACTIONS_PATH), str(HERMES_THRESHOLDS_PATH), "scripts/hermes_maturity_gates.py", "scripts/lib/hermes_outcome_bus/maturity.py"]
            warnings.append("Hermes maturity v2 is framework-specific and is not averaged with Agent Runtime MVL gates.")
            required_sample_size = None
            next_gate_id = None
            next_gate_description = None
            operator_checks.append("Live Hermes DB-computed gate board is OPERATOR_CHECK_REQUIRED in this clone-safe read model.")
            operator_checks.append("Exact Hermes next-rung sample gate is not available from repository config alone.")
        if agent_id == "broker_cloud_oversight":
            framework = "broker-oversight-provenance"
            framework_version = "read-visible-v1"
            lifecycle = "DESIGNED"
            environment = "LAB"
            evidence_refs = ["scripts/broker_promote_oversight.py"]
            required_sample_size = None
            next_gate_id = None
            next_gate_description = None
            declared_activation = None
            warnings.append("Cloud oversight review provenance is visible, but cloud requirement policy is unchanged.")
            operator_checks.append("Exact broker oversight maturity sample gate is not available from the current source.")
        if agent_id == "defense_adjudication":
            framework = "defense-deterministic-adjudication"
            framework_version = "v9"
            lifecycle = "DESIGNED"
            environment = "LAB"
            evidence_refs = ["scripts/defense_adjudication.py", "config/promote_criteria.json"]
            required_sample_size = None
            next_gate_id = None
            next_gate_description = None
            declared_activation = None
            warnings.append("Defense adjudication includes write-capable functions outside this read model; this adapter is repository evidence only.")
            operator_checks.append("Exact defense adjudication maturity sample gate is not available from the current source.")
        if agent_id == "concierge":
            framework = "openclaw-runtime-inventory"
            framework_version = "openclaw-runtime-inventory-v1"
            sample_size = None
            required_sample_size = None
            next_gate_id = None
            next_gate_description = None
            operator_checks.append("OpenClaw runtime status requires sanitized operator inventory; raw OpenClaw config is intentionally not read.")
            operator_checks.append("Exact OpenClaw runtime sample gate is not available from repository evidence alone.")

        observations.append(_observation(
            observed_at=observed_at,
            agent_id=agent_id,
            display_name=str(display),
            subsystem=str(subsystem),
            agent_kind=str(cat.get("agent_kind") or defined.get("agent_kind") or "agent_like_subsystem"),
            environment=environment,
            lifecycle=lifecycle,
            allowed=allowed,
            denied=denied,
            framework=framework,
            framework_version=framework_version,
            maturity_score=maturity_score,
            maturity_tier=maturity_tier,
            component_scores=component_scores,
            sample_size=sample_size,
            required_sample_size=required_sample_size,
            review=_review_evidence_from_record(review_records.get(agent_id)),
            declared_production_activation_authorized=declared_activation,
            effective_production_activation_verified=False,
            framework_gates_complete=False,
            next_gate_id=next_gate_id,
            next_gate_description=next_gate_description,
            source_class="REPOSITORY_EVIDENCE",
            evidence_refs=evidence_refs,
            warnings=warnings,
            operator_checks_required=operator_checks,
        ))
    return [item.to_dict() for item in observations]


def summarize_observations(observations: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(observations)

    def counts(field: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in rows:
            key = str(row.get(field) or "UNKNOWN")
            out[key] = out.get(key, 0) + 1
        return dict(sorted(out.items()))

    return {
        "total_agents": len(rows),
        "by_lifecycle_state": counts("declared_lifecycle_state"),
        "by_authority_state": counts("effective_authority_state"),
        "by_gate_state": counts("next_gate_state"),
        "by_review_health": counts("review_health"),
        "sample_size_capped_agents": sum(1 for r in rows if r.get("sample_progress_state") == "CAPPED_BY_SAMPLE_SIZE"),
        "eligible_for_human_review": sum(1 for r in rows if r.get("promotion_eligibility") == "ELIGIBLE_FOR_HUMAN_REVIEW"),
        "unverified_runtime_status": sum(1 for r in rows if RUNTIME_STATUS_UNVERIFIED in str(r.get("freshness_state") or "")),
        "frameworks": sorted({str(r.get("maturity_framework")) for r in rows}),
    }


def maturity_payload(root: Path, *, observed_at: str | None = None) -> dict[str, Any]:
    observations = build_observations(root, observed_at=observed_at)
    generated_at = observed_at or utc_now()
    return {
        "contract": API_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "freshness": "repository evidence current at request time; live runtime status unverified unless an adapter says otherwise",
        "source_availability": {
            "repository_config": "available",
            "agent_runtime_db": "UNVERIFIED",
            "openclaw_runtime": "OPERATOR_CHECK_REQUIRED",
            "production_runtime": "UNVERIFIED",
        },
        "unverified_source_warnings": [
            "No production secrets or raw OpenClaw config are read by this endpoint.",
            "Repository configuration is not proof of live runtime activation.",
        ],
        "read_only": True,
        "authority": dict(ZERO_AUTHORITY),
        "summary": summarize_observations(observations),
        "data": observations,
        "evidence_refs": [
            "docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md",
            str(CATALOG_PATH),
            str(MVL_PATH),
        ],
    }


def maturity_summary_payload(root: Path, *, observed_at: str | None = None) -> dict[str, Any]:
    payload = maturity_payload(root, observed_at=observed_at)
    return {k: payload[k] for k in ("contract", "schema_version", "generated_at", "freshness", "source_availability", "unverified_source_warnings", "read_only", "authority", "summary", "evidence_refs")}


def maturity_agent_payload(root: Path, agent_id: str, *, observed_at: str | None = None) -> dict[str, Any] | None:
    safe_id = str(agent_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", safe_id):
        return None
    payload = maturity_payload(root, observed_at=observed_at)
    for row in payload["data"]:
        if row.get("agent_id") == safe_id:
            return {**payload, "data": row, "summary": None}
    return None


SECRET_FIELD_RE = re.compile(r"(token|secret|password|credential|key|oauth|totp|cookie|session)", re.I)
RUNTIME_INVENTORY_ALLOWED_FIELDS = {
    "schema_version",
    "source_hash",
    "installed_version",
    "service_unit_name",
    "config_schema_version",
    "declared_agent_ids",
    "declared_soul_ids",
    "declared_skill_ids",
    "enabled",
    "last_verified_at",
    "verification_status",
}


def sanitize_runtime_inventory(raw: Mapping[str, Any]) -> dict[str, Any]:
    blocked = sorted(k for k in raw if SECRET_FIELD_RE.search(str(k)))
    if blocked:
        raise ValueError("secret-like fields are not allowed in sanitized runtime inventory")
    sanitized = {k: raw[k] for k in sorted(RUNTIME_INVENTORY_ALLOWED_FIELDS) if k in raw}
    if "schema_version" not in sanitized:
        sanitized["schema_version"] = "openclaw-runtime-inventory-v1"
    sanitized.setdefault("verification_status", "UNVERIFIED")
    return sanitized


def analyze_outcome_completeness(records: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    rows = list(records or [])
    missing = {
        "outcome": 0,
        "immutable_source_id": 0,
        "decision_timestamp": 0,
        "outcome_timestamp": 0,
        "agent_model_provenance": 0,
        "prompt_version_hash": 0,
    }
    conflicts: list[dict[str, Any]] = []
    seen: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        sid = row.get("source_id")
        if not row.get("outcome"):
            missing["outcome"] += 1
        if not sid:
            missing["immutable_source_id"] += 1
        if not row.get("decision_timestamp"):
            missing["decision_timestamp"] += 1
        if not row.get("outcome_timestamp"):
            missing["outcome_timestamp"] += 1
        if not (row.get("agent_id") and (row.get("model") or row.get("provider"))):
            missing["agent_model_provenance"] += 1
        if not (row.get("prompt_version") and (row.get("input_hash") or row.get("response_hash"))):
            missing["prompt_version_hash"] += 1
        if sid:
            prior = seen.get(str(sid))
            if prior and prior.get("outcome") != row.get("outcome"):
                conflicts.append({"source_id": sid, "reason": "conflicting outcome"})
            seen[str(sid)] = row
    return {
        "schema_version": "agent-maturity-outcome-completeness-dry-run-v1",
        "dry_run": True,
        "write_attempted": False,
        "source_dataset": "fixtures" if rows else "NOT_AVAILABLE",
        "time_range": "NOT_AVAILABLE",
        "record_count": len(rows),
        "records_with_outcome": sum(1 for r in rows if r.get("outcome")),
        "records_missing": missing,
        "records_excluded": [{"reason": "OPERATOR_DATA_REQUIRED", "count": 0 if rows else 1}],
        "candidate_derived_records": [
            {
                "source_ids": [r.get("source_id")],
                "original_timestamps": [r.get("decision_timestamp"), r.get("outcome_timestamp")],
                "derivation_version": "dry-run-v1",
                "dry_run": True,
                "write_attempted": False,
            }
            for r in rows
            if r.get("source_id") and r.get("outcome")
        ],
        "conflicts_or_duplicates": conflicts,
        "estimated_sample_size_impact": sum(1 for r in rows if r.get("outcome") and r.get("source_id")),
    }


def identity_namespace_report(root: Path) -> dict[str, Any]:
    observations = build_observations(root)
    by_display: dict[str, list[Mapping[str, Any]]] = {}
    for row in observations:
        by_display.setdefault(str(row.get("display_name") or "").lower(), []).append(row)
    collision_rows = []
    for display, rows in by_display.items():
        if len(rows) < 2:
            continue
        for row in rows:
            collision_rows.append({
                "current_id": row["agent_id"],
                "display_name": row["display_name"],
                "subsystem": row["subsystem"],
                "runtime_owner": "repository",
                "authority": row["effective_authority_state"],
                "storage_tables_fields": "OPERATOR_CHECK_REQUIRED",
                "api_ui_references": "apps/command-center-v3/src/pages/AgentRuntimeHub.tsx",
                "configuration_references": row["evidence_refs"],
                "collision_risk": f"display-name collision: {display}",
                "recommended_future_id": f"{row['subsystem']}:{row['agent_id']}",
                "migration_impact": "defer broad rename; add aliases and compatibility plan first",
            })
    return {
        "schema_version": "agent-identity-namespace-recommendation-v1",
        "collisions": collision_rows,
        "namespace_plan": "Use subsystem-qualified stable IDs for new storage while preserving current IDs as aliases.",
    }
