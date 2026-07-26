from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping

_AGENT_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class Environment(str, Enum):
    LAB = "LAB"
    SHADOW = "SHADOW"


class DeploymentState(str, Enum):
    DESIGNED = "DESIGNED"
    SHADOW = "SHADOW"
    OPERATIONAL = "OPERATIONAL"
    RESTRICTED = "RESTRICTED"
    RETOOL = "RETOOL"
    RETIRED = "RETIRED"


class RunStatus(str, Enum):
    CREATED = "CREATED"
    RETRIEVING = "RETRIEVING"
    READY_TO_REASON = "READY_TO_REASON"
    REASONING = "REASONING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class ReviewVerdict(str, Enum):
    PASS = "PASS"
    CAUTION = "CAUTION"
    REJECT = "REJECT"
    QUARANTINE = "QUARANTINE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ToolDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


FORBIDDEN_TOOL_PREFIXES = (
    "broker.",
    "order.",
    "trade.",
    "execution.",
    "position.write",
    "account.write",
    "approval.",
    "2fa.",
    "secret.",
    "secrets.",
    "credential.",
    "production.",
    "prod_db.write",
    "config.promote",
    "config.activate",
    "shell.",
    "systemd.",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BudgetPolicy:
    max_model_calls: int = 3
    max_tool_calls: int = 12
    max_cost_usd: float = 0.0
    deadline_seconds: int = 360

    def validate(self) -> None:
        if self.max_model_calls < 0 or self.max_tool_calls < 0:
            raise ValueError("call budgets must be non-negative")
        if self.max_cost_usd < 0:
            raise ValueError("cost budget must be non-negative")
        if not 1 <= self.deadline_seconds <= 86_400:
            raise ValueError("deadline_seconds must be between 1 and 86400")


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    display_name: str
    role: str
    version: str
    owner: str
    allowed_job_types: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    denied_tools: tuple[str, ...] = ()
    retrieval_required: bool = True
    budget: BudgetPolicy = field(default_factory=BudgetPolicy)
    deployment_state: DeploymentState = DeploymentState.DESIGNED
    enabled: bool = False

    def validate(self) -> None:
        if not _AGENT_ID.fullmatch(self.agent_id):
            raise ValueError(f"invalid agent_id: {self.agent_id}")
        if not self.version or not self.owner or not self.role:
            raise ValueError("version, owner, and role are required")
        if not self.allowed_job_types:
            raise ValueError("at least one allowed_job_type is required")
        overlap = set(self.allowed_tools).intersection(self.denied_tools)
        if overlap:
            raise ValueError(f"tools cannot be both allowed and denied: {sorted(overlap)}")
        for tool in self.allowed_tools:
            if any(tool == prefix.rstrip(".") or tool.startswith(prefix) for prefix in FORBIDDEN_TOOL_PREFIXES):
                raise ValueError(f"forbidden tool cannot be allowlisted: {tool}")
        if self.deployment_state is DeploymentState.OPERATIONAL and not self.enabled:
            raise ValueError("OPERATIONAL agents must be enabled")
        self.budget.validate()


@dataclass(frozen=True)
class RunEnvelope:
    run_id: str
    agent_id: str
    agent_version: str
    job_type: str
    environment: Environment
    objective: str
    input_hash: str
    validation_hash: str
    created_at: str = field(default_factory=utc_now)

    def validate(self, definition: AgentDefinition) -> None:
        definition.validate()
        if self.agent_id != definition.agent_id or self.agent_version != definition.version:
            raise ValueError("run envelope does not match agent definition")
        if self.job_type not in definition.allowed_job_types:
            raise ValueError(f"job type not allowed: {self.job_type}")
        if self.environment not in {Environment.LAB, Environment.SHADOW}:
            raise ValueError("MVL runtime is LAB/SHADOW only")
        if not self.objective.strip():
            raise ValueError("objective is required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.input_hash):
            raise ValueError("input_hash must be sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", self.validation_hash):
            raise ValueError("validation_hash must be sha256")


@dataclass(frozen=True)
class ToolRequest:
    run_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    environment: Environment

    @property
    def arguments_hash(self) -> str:
        return canonical_hash(self.arguments)


@dataclass(frozen=True)
class ToolEvaluation:
    decision: ToolDecision
    reason: str


class ToolPolicy:
    """Deterministic tool authority. Models never decide tool permission."""

    @staticmethod
    def evaluate(definition: AgentDefinition, request: ToolRequest) -> ToolEvaluation:
        definition.validate()
        if request.environment not in {Environment.LAB, Environment.SHADOW}:
            return ToolEvaluation(ToolDecision.DENY, "environment is not LAB/SHADOW")
        name = request.tool_name.strip().lower()
        if not name:
            return ToolEvaluation(ToolDecision.DENY, "tool name is empty")
        if any(name == prefix.rstrip(".") or name.startswith(prefix) for prefix in FORBIDDEN_TOOL_PREFIXES):
            return ToolEvaluation(ToolDecision.DENY, "tool belongs to a constitutionally denied authority")
        denied = {tool.lower() for tool in definition.denied_tools}
        if name in denied or any(name.startswith(f"{tool}.") for tool in denied):
            return ToolEvaluation(ToolDecision.DENY, "tool is denied by the agent contract")
        allowed = {tool.lower() for tool in definition.allowed_tools}
        if name not in allowed:
            return ToolEvaluation(ToolDecision.DENY, "tool is not explicitly allowlisted")
        return ToolEvaluation(ToolDecision.ALLOW, "explicit LAB/SHADOW allowlist match")


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    run_id: str
    producer_agent_id: str
    artifact_type: str
    payload: Mapping[str, Any]
    input_hash: str
    validation_hash: str
    retrieval_refs: tuple[str, ...]
    prompt_version: str
    provider_family: str
    model: str
    created_at: str = field(default_factory=utc_now)

    @property
    def payload_hash(self) -> str:
        return canonical_hash(self.payload)

    def validate(self, retrieval_required: bool = True) -> None:
        if retrieval_required and not self.retrieval_refs:
            raise ValueError("retrieval-before-reasoning requirement not satisfied")
        if not self.prompt_version or not self.provider_family or not self.model:
            raise ValueError("model provenance is required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.input_hash):
            raise ValueError("invalid artifact input hash")
        if not re.fullmatch(r"[0-9a-f]{64}", self.validation_hash):
            raise ValueError("invalid artifact validation hash")


@dataclass(frozen=True)
class Review:
    review_id: str
    artifact_id: str
    producer_agent_id: str
    reviewer_agent_id: str
    verdict: ReviewVerdict
    findings: tuple[str, ...]
    artifact_hash: str
    created_at: str = field(default_factory=utc_now)

    def validate(self) -> None:
        if self.producer_agent_id == self.reviewer_agent_id:
            raise ValueError("an agent may not review its own artifact")
        if not re.fullmatch(r"[0-9a-f]{64}", self.artifact_hash):
            raise ValueError("artifact_hash must be sha256")


@dataclass(frozen=True)
class Score:
    score_id: str
    artifact_id: str
    producer_agent_id: str
    scorer_agent_id: str
    dimensions: Mapping[str, float]
    outcome_ref: str | None = None
    created_at: str = field(default_factory=utc_now)

    def validate(self) -> None:
        if self.producer_agent_id == self.scorer_agent_id:
            raise ValueError("an agent may not score its own artifact")
        if not self.dimensions:
            raise ValueError("at least one score dimension is required")
        for key, value in self.dimensions.items():
            if not key or not -1.0 <= float(value) <= 1.0:
                raise ValueError("score dimensions must be named and within [-1, 1]")


def dataclass_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    raise TypeError("expected dataclass instance")


def assert_no_secret_material(value: Any, forbidden_keys: Iterable[str] = ()) -> None:
    keys = {key.lower() for key in forbidden_keys}.union({
        "password", "token", "secret", "api_key", "private_key", "totp", "credential", "authorization"
    })

    # Substring-match every sensitive word, not just a subset: a guard must only ever reject
    # more. Exact-key-only matching for "token"/"api_key"/"credential"/"authorization" let
    # compound keys like "api_token" or "access_token" slip through.
    fragments = tuple(keys)

    def walk(item: Any, path: str = "root") -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                lowered = str(key).lower()
                if lowered in keys or any(fragment in lowered for fragment in fragments):
                    raise ValueError(f"secret-like field prohibited at {path}.{key}")
                walk(child, f"{path}.{key}")
        elif isinstance(item, (list, tuple, set)):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]")

    walk(value)
