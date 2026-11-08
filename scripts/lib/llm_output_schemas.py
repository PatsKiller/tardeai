"""Strict structured-output contracts for DeepSeek process responses.

No prose stripping. No regex extraction of the first {...} block.
"""
from __future__ import annotations

from typing import Any, Literal

try:
    from pydantic import BaseModel, Field, ValidationError
except ImportError:  # pragma: no cover
    BaseModel = object  # type: ignore
    Field = lambda *a, **k: None  # type: ignore
    ValidationError = Exception  # type: ignore


class WatchNarrativeV1(BaseModel):
    schema_id: Literal["watch_narrative.v1"] = "watch_narrative.v1"
    symbol: str
    narrative: str
    stance: Literal["bullish", "bearish", "neutral", "mixed"] = "neutral"
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    drivers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class CioSynthesisV1(BaseModel):
    schema_id: Literal["cio_synthesis.v1"] = "cio_synthesis.v1"
    symbol: str
    thesis: str
    action: Literal["hold", "add", "trim", "exit", "watch", "research"] = "watch"
    conviction: float = Field(ge=0.0, le=1.0, default=0.5)
    contradictions: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    next_step: str = ""


class StrategyPlanV1(BaseModel):
    schema_id: Literal["strategy_plan.v1"] = "strategy_plan.v1"
    title: str
    summary: str
    steps: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidation: str = ""
    horizon: str = ""


class PipelineDiagnosisV1(BaseModel):
    schema_id: Literal["pipeline_diagnosis.v1"] = "pipeline_diagnosis.v1"
    status: Literal["ok", "degraded", "fail", "unknown"] = "unknown"
    summary: str
    findings: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    severity: Literal["info", "warn", "error", "critical"] = "info"


class ContradictionVerdictV1(BaseModel):
    """ContradictionVerdict@v1 as the model must return it (LQ-20261107-1010).

    The adjudicator used to accept any dict carrying a known ``verdict`` string and default every
    other field, so a truncated or loosely-shaped answer still became a row. The contract is the one
    the prompt states: a verdict, a bounded confidence, a rationale, the evidence refs relied on and
    what would resolve it.
    """

    schema_id: Literal["contradiction_verdict.v1"] = "contradiction_verdict.v1"
    verdict: Literal["LEFT", "RIGHT", "BOTH_STALE", "NOT_A_CONTRADICTION", "UNRESOLVED"]
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    rationale: str = ""
    decisive_evidence_refs: list[str] = Field(default_factory=list)
    what_would_resolve: str = ""


SCHEMA_MODELS: dict[str, type] = {
    "watch_narrative.v1": WatchNarrativeV1,
    "cio_synthesis.v1": CioSynthesisV1,
    "strategy_plan.v1": StrategyPlanV1,
    "pipeline_diagnosis.v1": PipelineDiagnosisV1,
    "contradiction_verdict.v1": ContradictionVerdictV1,
}


def validate_process_output(schema_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Validate a parsed dict against a named process schema. Raises ValueError on failure."""
    model = SCHEMA_MODELS.get(schema_id)
    if model is None:
        raise ValueError(f"unknown output schema: {schema_id}")
    try:
        obj = model.model_validate(data)  # type: ignore[attr-defined]
        return obj.model_dump()  # type: ignore[attr-defined]
    except ValidationError as e:
        raise ValueError(f"schema validation failed for {schema_id}: {e}") from e
    except Exception as e:
        # pydantic v1 fallback
        try:
            obj = model.parse_obj(data)  # type: ignore[attr-defined]
            return obj.dict()  # type: ignore[attr-defined]
        except Exception as e2:
            raise ValueError(f"schema validation failed for {schema_id}: {e2}") from e2


def schema_example(schema_id: str) -> dict[str, Any]:
    examples = {
        "watch_narrative.v1": {
            "schema_id": "watch_narrative.v1",
            "symbol": "AAPL",
            "narrative": "Setup remains constructive with higher lows.",
            "stance": "bullish",
            "confidence": 0.62,
            "drivers": ["trend"],
            "risks": ["earnings"],
        },
        "cio_synthesis.v1": {
            "schema_id": "cio_synthesis.v1",
            "symbol": "AAPL",
            "thesis": "Hold core; trim only on thesis break.",
            "action": "hold",
            "conviction": 0.7,
            "contradictions": [],
            "evidence": ["relative strength"],
            "next_step": "reassess after next catalyst",
        },
        "strategy_plan.v1": {
            "schema_id": "strategy_plan.v1",
            "title": "Pullback re-entry",
            "summary": "Wait for support reclaim.",
            "steps": ["mark support", "size small"],
            "risks": ["gap risk"],
            "invalidation": "daily close below support",
            "horizon": "1-3 weeks",
        },
        "pipeline_diagnosis.v1": {
            "schema_id": "pipeline_diagnosis.v1",
            "status": "degraded",
            "summary": "Quote feed lagging.",
            "findings": ["stale timestamps"],
            "recommended_actions": ["refresh quotes"],
            "severity": "warn",
        },
        "contradiction_verdict.v1": {
            "schema_id": "contradiction_verdict.v1",
            "verdict": "NOT_A_CONTRADICTION",
            "confidence": 0.6,
            "rationale": "The two artifacts address different horizons.",
            "decisive_evidence_refs": ["artifact-1"],
            "what_would_resolve": "A same-horizon restatement from the same source.",
        },
    }
    if schema_id not in examples:
        raise ValueError(f"no example for schema {schema_id}")
    return examples[schema_id]
