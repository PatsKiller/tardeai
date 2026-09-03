"""Research observation provenance + fail-closed eligibility (additive).

Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0.
Does not authorize orders, mutate production stores, or change schedulers.

Reuse existing research products/stores via adapters; do not rewrite the
research platform. Backend owns ``canonical_observation`` (portfolio/overview);
this package is the research-boundary contract for Command Center and
downstream agent consumers.
"""

from __future__ import annotations

from .contract import (
    SCHEMA_VERSION,
    AUTHORITY,
    ResearchObservation,
    make_research_observation,
    payload_source_hash,
    required_provenance_fields,
)
from .statuses import (
    FreshnessStatus,
    QualityStatus,
    EntitlementStatus,
    FallbackState,
    EligibilityDecision,
)
from .eligibility import (
    evaluate_eligibility,
    EligibilityPolicy,
    DEFAULT_POLICY,
)
from .join import (
    JoinResult,
    join_run_artifacts,
    correlate_run,
)
from .adapters import (
    wrap_research_record,
    wrap_no_data,
    wrap_gap,
    wrap_error,
    project_to_canonical_clocks,
)
from .consumer_gate import (
    ConsumerGateResult,
    gate_for_consumer,
    assert_eligible_or_raise,
)

__all__ = [
    "SCHEMA_VERSION",
    "AUTHORITY",
    "ResearchObservation",
    "make_research_observation",
    "payload_source_hash",
    "required_provenance_fields",
    "FreshnessStatus",
    "QualityStatus",
    "EntitlementStatus",
    "FallbackState",
    "EligibilityDecision",
    "evaluate_eligibility",
    "EligibilityPolicy",
    "DEFAULT_POLICY",
    "JoinResult",
    "join_run_artifacts",
    "correlate_run",
    "wrap_research_record",
    "wrap_no_data",
    "wrap_gap",
    "wrap_error",
    "project_to_canonical_clocks",
    "ConsumerGateResult",
    "gate_for_consumer",
    "assert_eligible_or_raise",
]
