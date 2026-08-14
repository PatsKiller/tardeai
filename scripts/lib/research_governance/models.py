"""Research governance — canonical record models (PR-R1, additive-only).

Pure data contracts. No I/O, no provider calls, no DB writes. These are the
durable shapes the trial registry, statistical layer, and promotion gate operate
over. Reproducibility is enforced via content hashes (protocol/dataset/code).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from .enums import (
    EvidenceGrade,
    EvidenceType,
    InfluenceClass,
    ResearchStatus,
)


def _stable_hash(obj: Any) -> str:
    """Deterministic sha256 of a JSON-canonicalized object (sorted keys)."""
    canonical = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class ResearchSource:
    source_id: str
    source_type: str
    title: str
    authors: list[str] = field(default_factory=list)
    edition: Optional[str] = None
    publication_date: Optional[str] = None
    publisher_or_journal: Optional[str] = None
    doi_or_isbn: Optional[str] = None
    license_class: str = "UNKNOWN"
    full_text_status: str = "NOT_FOUND_IN_FILE_LIBRARY"
    source_location: Optional[str] = None
    source_hash: Optional[str] = None
    verified_at: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class ResearchClaim:
    claim_id: str
    source_id: str
    claim: str
    claim_type: str
    page_or_section: Optional[str] = None
    scope: Optional[str] = None
    conditions: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    source_status: ResearchStatus = ResearchStatus.SOURCE_CLAIM_INCOMPLETE

    def __post_init__(self) -> None:
        if isinstance(self.source_status, str):
            self.source_status = ResearchStatus(self.source_status)


@dataclass
class ResearchHypothesis:
    """Frozen BEFORE confirmatory testing. `protocol_hash` binds the definition."""

    hypothesis_id: str
    source_claim_ids: list[str] = field(default_factory=list)
    universe: Optional[str] = None
    signal_definition: Optional[str] = None
    benchmark: Optional[str] = None
    primary_metric: Optional[str] = None
    secondary_metrics: list[str] = field(default_factory=list)
    entry_time: Optional[str] = None
    exit_time: Optional[str] = None
    holding_period: Optional[str] = None
    transaction_cost_model: Optional[str] = None
    tax_model_if_relevant: Optional[str] = None
    sample_start: Optional[str] = None
    sample_end: Optional[str] = None
    oos_design: Optional[str] = None
    subperiods: list[str] = field(default_factory=list)
    regime_tests: list[str] = field(default_factory=list)
    lookahead_controls: list[str] = field(default_factory=list)
    survivorship_controls: list[str] = field(default_factory=list)
    multiple_test_family_id: Optional[str] = None
    planned_variants: list[dict[str, Any]] = field(default_factory=list)
    preregistered_at: Optional[str] = None
    protocol_hash: Optional[str] = None

    def compute_protocol_hash(self) -> str:
        d = asdict(self)
        d.pop("protocol_hash", None)
        self.protocol_hash = _stable_hash(d)
        return self.protocol_hash


@dataclass
class TrialRecord:
    """One attempted variant — including losers. Never register only winners."""

    trial_id: str
    family_id: str
    hypothesis_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    code_sha: Optional[str] = None
    dataset_hash: Optional[str] = None
    result_hash: Optional[str] = None
    selected_for_followup: bool = False
    selection_reason: Optional[str] = None


@dataclass
class OOSWindow:
    """An out-of-sample segment. Once exposed and used for tuning it is consumed."""

    oos_window_id: str
    oos_generation: int
    segment_start: Optional[str] = None
    segment_end: Optional[str] = None
    oos_consumed_at: Optional[str] = None


@dataclass
class ReproductionResult:
    reproduction_id: str
    hypothesis_id: str
    trial_family_id: str
    dataset_ids: list[str] = field(default_factory=list)
    dataset_hashes: list[str] = field(default_factory=list)
    code_sha: Optional[str] = None
    protocol_hash: Optional[str] = None
    sample_n: Optional[int] = None
    return_metrics: dict[str, Any] = field(default_factory=dict)
    risk_metrics: dict[str, Any] = field(default_factory=dict)
    cost_metrics: dict[str, Any] = field(default_factory=dict)
    dsr: Optional[Any] = None
    pbo: Optional[Any] = None
    multiple_testing: Optional[Any] = None
    reality_check: Optional[Any] = None
    oos: Optional[Any] = None
    subperiods: list[Any] = field(default_factory=list)
    regimes: list[Any] = field(default_factory=list)
    implementation_capacity: Optional[str] = None
    result_status: ResearchStatus = ResearchStatus.IN_SAMPLE_REPRODUCED
    limitations: list[str] = field(default_factory=list)
    created_at: Optional[str] = None


@dataclass
class ResearchEvidence:
    """The normalized object a retriever returns (retrieval contract)."""

    fact_id: str
    fact: str
    source_id: str
    source_date: Optional[str] = None
    evidence_type: EvidenceType = EvidenceType.SOURCE_NARRATIVE
    research_status: ResearchStatus = ResearchStatus.SOURCE_CLAIM
    evidence_grade: EvidenceGrade = EvidenceGrade.D
    influence_class: InfluenceClass = InfluenceClass.CONTEXT_MODIFIER
    reproduction_ids: list[str] = field(default_factory=list)
    sample_n: Optional[int] = None
    period: Optional[str] = None
    current_applicability: Optional[str] = None
    caveat: Optional[str] = None
    role_in_decision: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    counterevidence_refs: list[str] = field(default_factory=list)
    contradicts_refs: list[str] = field(default_factory=list)
