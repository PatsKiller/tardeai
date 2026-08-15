"""Research governance — canonical record models (PR-R1, additive-only).

Pure data contracts. No I/O, no provider calls, no DB writes. These are the
durable shapes the trial registry, statistical layer, and promotion gate operate
over. Reproducibility is enforced via content hashes (protocol/dataset/code).

Anti-gaming invariants encoded here:

  * `FrozenHypothesis` is DEEPLY immutable: every nested list/dict is converted
    to tuples / `FrozenDict` so a frozen protocol cannot be mutated in place.
  * `verify_protocol_integrity(frozen)` recomputes the protocol hash from the
    immutable snapshot and proves it matches the stored `protocol_hash`.
  * `TrialRecord` retains external-artifact verification lineage (ref/size/alg/
    verified_at/verification_status) plus terminal-disposition reasons.
  * `OOSWindow` carries dataset lineage (dataset_id/dataset_hash) so a consumed
    economic segment cannot be recharacterized as fresh by changing the snapshot.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

from .enums import (
    EvidenceGrade,
    EvidenceType,
    InfluenceClass,
    ResearchStatus,
)


class FrozenDict(Mapping):
    """An immutable, hashable mapping used inside frozen protocol snapshots."""

    __slots__ = ("_items", "_hash")

    def __init__(self, mapping: Mapping | Any = None, /, **kwargs: Any) -> None:
        data: dict = {}
        if mapping is not None:
            if isinstance(mapping, Mapping):
                data.update(mapping)
            else:
                raise TypeError(f"FrozenDict expects a Mapping, got {type(mapping)!r}")
        data.update(kwargs)
        self._items = tuple(
            sorted(((k, _deep_freeze(v)) for k, v in data.items()), key=lambda kv: str(kv[0]))
        )
        self._hash = hash(self._items)

    def __getitem__(self, key: str) -> Any:
        for k, v in self._items:
            if k == key:
                return v
        raise KeyError(key)

    def __iter__(self):
        return (k for k, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __hash__(self) -> int:
        return self._hash

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, FrozenDict):
            return self._items == other._items
        if isinstance(other, Mapping):
            return dict(self._items) == dict(other)
        return NotImplemented

    def __repr__(self) -> str:
        return f"FrozenDict({dict(self._items)!r})"

    def to_dict(self) -> dict:
        return {k: _thaw(v) for k, v in self._items}


def _deep_freeze(obj: Any) -> Any:
    """Convert mutable containers to immutable equivalents, recursively.

    Frozen dataclasses and scalars pass through unchanged: a frozen dataclass is
    already immutable, and converting it to a dict would destroy its methods/fields.
    """
    if isinstance(obj, Mapping):
        return FrozenDict(obj)
    if isinstance(obj, (list, tuple)):
        return tuple(_deep_freeze(v) for v in obj)
    if isinstance(obj, set):
        return frozenset(_deep_freeze(v) for v in obj)
    if isinstance(obj, Enum):
        return obj.value
    return obj


def _thaw(obj: Any) -> Any:
    """Convert deeply-frozen values back to plain JSON-safe structures."""
    if isinstance(obj, FrozenDict):
        return obj.to_dict()
    if isinstance(obj, (tuple, list)):
        return [_thaw(v) for v in obj]
    if isinstance(obj, (frozenset, set)):
        return sorted(_thaw(v) for v in obj)
    return obj


def _canon(obj: Any) -> Any:
    """JSON-safe canonical form for stable hashing (tuples -> list, Mapping -> sorted dict)."""
    if isinstance(obj, FrozenDict):
        return {k: _canon(v) for k, v in obj._items}
    if isinstance(obj, Mapping):
        return {k: _canon(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_canon(v) for v in obj]
    if isinstance(obj, (frozenset, set)):
        return sorted(_canon(v) for v in obj)
    if is_dataclass(obj) and not isinstance(obj, type):
        return _canon(asdict(obj))
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _stable_hash(obj: Any) -> str:
    """Deterministic sha256 of a JSON-canonicalized object (sorted keys)."""
    canonical = json.dumps(_canon(obj), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        """Return the deterministic protocol hash WITHOUT mutating this object."""
        d = asdict(self)
        d.pop("protocol_hash", None)
        return _stable_hash(d)

    def freeze(self) -> "FrozenHypothesis":
        """Return a DEEPLY immutable snapshot with a bound protocol hash."""
        d = asdict(self)
        d.pop("protocol_hash", None)
        protocol_hash = _stable_hash(d)
        return FrozenHypothesis(
            protocol_hash=protocol_hash,
            hypothesis_id=self.hypothesis_id,
            source_claim_ids=tuple(self.source_claim_ids),
            universe=self.universe,
            signal_definition=self.signal_definition,
            benchmark=self.benchmark,
            primary_metric=self.primary_metric,
            secondary_metrics=tuple(self.secondary_metrics),
            entry_time=self.entry_time,
            exit_time=self.exit_time,
            holding_period=self.holding_period,
            transaction_cost_model=self.transaction_cost_model,
            tax_model_if_relevant=self.tax_model_if_relevant,
            sample_start=self.sample_start,
            sample_end=self.sample_end,
            oos_design=self.oos_design,
            subperiods=tuple(self.subperiods),
            regime_tests=tuple(self.regime_tests),
            lookahead_controls=tuple(self.lookahead_controls),
            survivorship_controls=tuple(self.survivorship_controls),
            multiple_test_family_id=self.multiple_test_family_id,
            planned_variants=tuple(FrozenDict(v) for v in self.planned_variants),
            preregistered_at=self.preregistered_at,
        )


@dataclass(frozen=True)
class FrozenHypothesis:
    """DEEPLY immutable protocol snapshot.

    All nested lists are tuples and all nested dicts are `FrozenDict`, so a
    frozen protocol cannot be mutated in place. `protocol_hash` is bound to the
    canonical snapshot; `verify_protocol_integrity` recomputes it to detect any
    tampering (including after serialization round-trips).
    """

    protocol_hash: str
    hypothesis_id: str
    source_claim_ids: Tuple[str, ...] = ()
    universe: Optional[str] = None
    signal_definition: Optional[str] = None
    benchmark: Optional[str] = None
    primary_metric: Optional[str] = None
    secondary_metrics: Tuple[str, ...] = ()
    entry_time: Optional[str] = None
    exit_time: Optional[str] = None
    holding_period: Optional[str] = None
    transaction_cost_model: Optional[str] = None
    tax_model_if_relevant: Optional[str] = None
    sample_start: Optional[str] = None
    sample_end: Optional[str] = None
    oos_design: Optional[str] = None
    subperiods: Tuple[str, ...] = ()
    regime_tests: Tuple[str, ...] = ()
    lookahead_controls: Tuple[str, ...] = ()
    survivorship_controls: Tuple[str, ...] = ()
    multiple_test_family_id: Optional[str] = None
    planned_variants: Tuple[FrozenDict, ...] = ()
    preregistered_at: Optional[str] = None

    def protocol_payload(self) -> dict:
        """JSON-canonical protocol content WITHOUT the stored protocol_hash."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "source_claim_ids": list(self.source_claim_ids),
            "universe": self.universe,
            "signal_definition": self.signal_definition,
            "benchmark": self.benchmark,
            "primary_metric": self.primary_metric,
            "secondary_metrics": list(self.secondary_metrics),
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "holding_period": self.holding_period,
            "transaction_cost_model": self.transaction_cost_model,
            "tax_model_if_relevant": self.tax_model_if_relevant,
            "sample_start": self.sample_start,
            "sample_end": self.sample_end,
            "oos_design": self.oos_design,
            "subperiods": list(self.subperiods),
            "regime_tests": list(self.regime_tests),
            "lookahead_controls": list(self.lookahead_controls),
            "survivorship_controls": list(self.survivorship_controls),
            "multiple_test_family_id": self.multiple_test_family_id,
            "planned_variants": [v.to_dict() for v in self.planned_variants],
            "preregistered_at": self.preregistered_at,
        }

    def recompute_protocol_hash(self) -> str:
        return _stable_hash(self.protocol_payload())


def verify_protocol_integrity(frozen: FrozenHypothesis) -> bool:
    """Recompute the protocol hash from the immutable snapshot and compare.

    Returns True only if the stored `protocol_hash` equals the hash of the
    current (deeply frozen) snapshot content. Tampering or a stale hash fails.
    """
    return frozen.protocol_hash == frozen.recompute_protocol_hash()


@dataclass(frozen=True)
class TrialRecord:
    """One attempted variant — including losers. IMMUTABLE once recorded.

    `result_hash` hashes the ACTUAL result artifact; it is never a parameter
    hash. Selection status is NOT a field here — it is a separate append-only
    `SelectionEvent`, so a loser cannot be rewritten as a winner.

    Result lineage: either `result_storage=INLINE_PAYLOAD_HASH` (the registry
    computed `result_hash` from the supplied payload) or `EXTERNAL_ARTIFACT`
    (a verifier proved the referenced bytes hash to `result_hash`). The external
    case retains `result_artifact_ref`, `result_artifact_size`, `hash_algorithm`,
    `result_verified_at`, and `result_verification_status`.
    """

    trial_id: str
    config_hash: str
    result_hash: str
    terminal_status: str
    result_storage: str = "INLINE_PAYLOAD_HASH"
    result_artifact_ref: Optional[str] = None
    result_artifact_size: Optional[int] = None
    hash_algorithm: str = "sha256"
    result_verified_at: Optional[str] = None
    result_verification_status: Optional[str] = None
    terminal_reason: Optional[str] = None
    failure_stage: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    code_sha: Optional[str] = None
    dataset_hash: Optional[str] = None


@dataclass(frozen=True)
class SelectionEvent:
    """Append-only selection disposition for a single trial."""

    selection_event_id: str
    trial_id: str
    selected: bool
    reason: Optional[str] = None
    timestamp: Optional[str] = None


@dataclass(frozen=True)
class ArtifactVerification:
    """Result of an injectable external-artifact verification."""

    verified: bool
    sha256: str
    size: int
    ref: str
    verified_at: str
    error: Optional[str] = None


class ArtifactVerifier:
    """Injectable protocol for verifying an external result artifact.

    R1 keeps the registry pure (no I/O); production supplies a real verifier
    that reads bytes and recomputes the sha256. Tests inject `FakeArtifactVerifier`.
    """

    def verify(self, ref: str, expected_size: Optional[int],
               expected_sha256: str) -> ArtifactVerification:
        raise NotImplementedError


class FakeArtifactVerifier(ArtifactVerifier):
    """Deterministic test verifier: verifies iff the sha256 ends with the expected tag."""

    def __init__(self, known: Optional[dict] = None) -> None:
        self._known = known or {}

    def verify(self, ref: str, expected_size: Optional[int],
               expected_sha256: str) -> ArtifactVerification:
        rec = self._known.get(ref)
        if rec is None:
            return ArtifactVerification(False, expected_sha256, expected_size or 0, ref,
                                        _now_iso(), error="artifact not found")
        size = rec.get("size")
        sha = rec.get("sha256")
        ok = (sha == expected_sha256 and (expected_size is None or size == expected_size))
        return ArtifactVerification(ok, sha, size, ref, _now_iso(),
                                    error=None if ok else "size/hash mismatch")


@dataclass(frozen=True)
class OOSWindow:
    """An out-of-sample segment. Once exposed and used for tuning it is consumed.

    Segment identity = economic/time window (dataset identity + segment start/end
    + protocol family). Dataset snapshot lineage = `dataset_hash` (exact bytes).
    A consumed economic segment cannot become untouched merely by changing the
    snapshot hash; corrected-data reproductions are `CORRECTED_DATA_RERUN`.
    """

    oos_window_id: str
    oos_generation: int
    segment_start: Optional[str] = None
    segment_end: Optional[str] = None
    dataset_id: Optional[str] = None
    dataset_hash: Optional[str] = None
    protocol_hash: Optional[str] = None
    family_definition_hash: Optional[str] = None
    registered_at: Optional[str] = None
    oos_consumed_at: Optional[str] = None
    rerun_classification: Optional[str] = None


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


@dataclass(frozen=True)
class SampleTimingContract:
    """Canonical sample-timing provenance for no-lookahead validation.

    `feature_as_of` is when the feature would have been knowable; `decision_as_of`
    is when the decision is made. Timestamps must be ISO-8601; datetime values
    must be timezone-aware and are normalized to UTC before comparison.
    """

    event_start: Optional[str] = None
    event_end: Optional[str] = None
    label_end: Optional[str] = None
    feature_as_of: Optional[str] = None
    decision_as_of: Optional[str] = None


def _parse_iso(value: str):
    """Strict ISO-8601 parse. Returns (datetime, is_aware, is_date_only).

    Raises ValueError on malformed/non-canonical strings. Date-only values are
    returned as date objects (naive) so they cannot be mixed with datetimes.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("empty timestamp")
    v = value.strip()
    # Date-only: YYYY-MM-DD (exactly 10 chars, digits and dashes).
    if len(v) == 10 and v[4] == "-" and v[7] == "-" and v.replace("-", "").isdigit():
        from datetime import date
        return date.fromisoformat(v), False, True
    # Datetime: must carry an explicit timezone (offset or Z) for timestamp studies.
    try:
        dt = datetime.fromisoformat(v)
    except ValueError as exc:
        raise ValueError(f"malformed timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        raise ValueError(f"naive timestamp (timezone required): {value!r}")
    return dt, True, False


def validate_no_lookahead(timing: SampleTimingContract) -> list[str]:
    """Return problems ([] = OK). Fail-closed on missing/malformed fields.

    Parses ISO-8601; requires timezone-aware datetimes for timestamp studies;
    normalizes to UTC before comparison. Malformed or mixed-precision values are
    rejected (fail-closed).
    """
    problems: list[str] = []
    if not timing.feature_as_of:
        problems.append("feature_as_of missing")
    if not timing.decision_as_of:
        problems.append("decision_as_of missing")
    if problems:
        return problems

    try:
        f, f_aware, f_date = _parse_iso(timing.feature_as_of)
        d, d_aware, d_date = _parse_iso(timing.decision_as_of)
    except ValueError as exc:
        return [str(exc)]

    if f_date != d_date:
        return ["cannot compare date-only and datetime timestamps (mixed precision)"]
    if f_date:
        # date-only comparison is safe and unambiguous.
        if f > d:
            return [f"lookahead: feature_as_of={timing.feature_as_of} > decision_as_of={timing.decision_as_of}"]
        return []
    # datetimes: normalize to UTC.
    fu = f.astimezone(timezone.utc)
    du = d.astimezone(timezone.utc)
    if fu > du:
        return [f"lookahead: feature_as_of={timing.feature_as_of} > decision_as_of={timing.decision_as_of}"]
    return []
