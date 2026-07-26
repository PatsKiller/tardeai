from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .contracts import assert_no_secret_material, canonical_hash
from .journal import ShadowRunJournal


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    run_id: str
    title: str
    claim: str
    frozen_inputs: Mapping[str, Any]
    evaluation_plan: Mapping[str, Any]
    success_metrics: tuple[str, ...]
    failure_metrics: tuple[str, ...]
    rollback_plan: str
    status: str = "PREREGISTERED_SHADOW"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def hypothesis_hash(self) -> str:
        return canonical_hash(asdict(self))

    def validate(self) -> None:
        if self.status != "PREREGISTERED_SHADOW":
            raise ValueError("Hermes may only create preregistered shadow hypotheses")
        if not self.title.strip() or not self.claim.strip():
            raise ValueError("title and claim are required")
        if not self.success_metrics or not self.failure_metrics:
            raise ValueError("success and failure metrics are required before evaluation")
        if not self.rollback_plan.strip():
            raise ValueError("rollback plan is required")
        assert_no_secret_material(self.frozen_inputs)
        assert_no_secret_material(self.evaluation_plan)


class HermesHypothesisGateway:
    """Hermes writes hypotheses, never production configuration."""

    def __init__(self, journal: ShadowRunJournal) -> None:
        self.journal = journal

    def preregister(
        self,
        *,
        run_id: str,
        title: str,
        claim: str,
        frozen_inputs: Mapping[str, Any],
        evaluation_plan: Mapping[str, Any],
        success_metrics: Sequence[str],
        failure_metrics: Sequence[str],
        rollback_plan: str,
    ) -> Hypothesis:
        hypothesis = Hypothesis(
            hypothesis_id=f"hypothesis_{uuid.uuid4().hex}",
            run_id=run_id,
            title=title,
            claim=claim,
            frozen_inputs=dict(frozen_inputs),
            evaluation_plan=dict(evaluation_plan),
            success_metrics=tuple(success_metrics),
            failure_metrics=tuple(failure_metrics),
            rollback_plan=rollback_plan,
        )
        hypothesis.validate()
        self.journal.append(run_id, "HYPOTHESIS_PREREGISTERED", {
            "hypothesis": asdict(hypothesis),
            "hypothesis_hash": hypothesis.hypothesis_hash,
            "promotion_authority": "NONE",
            "checkpoint": "hypothesis_preregistered",
        })
        return hypothesis

    @staticmethod
    def promote(*_: Any, **__: Any) -> None:
        raise PermissionError("Hermes cannot promote or activate production configuration")
