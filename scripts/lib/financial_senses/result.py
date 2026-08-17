"""FinancialSenseResult@v1 — normalized read-only provider result envelope.

Every provider result carries provenance, as-of, quality, and a fixed
READ_ONLY_ADVISORY authority. No source may emit an unqualified fact without
provenance. The envelope now distinguishes:

  facts[]      deterministic / world observations (provenance + quality)
  claims[]     derived interpretations (source-typed, or UNSUPPORTED)
  estimates[]  model estimates / scenarios (MODEL_INFERENCE only)
  opinions[]   critic / specialist output (non-factual)

This module is pure and has no network or database access.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

from .source_governance import (
    SOURCE_MEMORY_CONTEXT,
    SOURCE_MODEL_INFERENCE,
    can_back_fact,
)

AUTHORITY = "READ_ONLY_ADVISORY"

STATUS_OK = "OK"
STATUS_PARTIAL = "PARTIAL"
STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_INVALID_REQUEST = "INVALID_REQUEST"
STATUS_STALE = "STALE"
STATUS_CONFLICT = "CONFLICT"

VALID_STATUSES = frozenset(
    {
        STATUS_OK,
        STATUS_PARTIAL,
        STATUS_NOT_CONFIGURED,
        STATUS_UNAVAILABLE,
        STATUS_INVALID_REQUEST,
        STATUS_STALE,
        STATUS_CONFLICT,
    }
)

# Distinct states for data that is missing rather than zero.
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
NOT_INGESTED = "NOT_INGESTED"
NOT_APPLICABLE = "NOT_APPLICABLE"
NOT_FOUND = "NOT_FOUND"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_request_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Subject:
    """The instrument or economic subject a result describes."""

    instrument_id: Optional[str] = None
    symbol: Optional[str] = None
    cik: Optional[str] = None
    figi: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Provenance:
    """Where a result's facts come from. Required for any fact-bearing result."""

    source_type: Optional[str] = None
    source_ids: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    source_digest: Optional[str] = None
    provider_version: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Quality:
    """Qualitative assessment of a result."""

    grade: str = "UNKNOWN"
    freshness: Optional[str] = None
    completeness: Optional[str] = None
    conflict: Optional[bool] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Fact:
    """A deterministic / world observation. Provenance is mandatory.

    A Fact MUST be backed by a fact-capable source (never MODEL_INFERENCE or
    MEMORY_CONTEXT) and MUST carry observed_at or as_of plus quality.
    """

    key: str
    value: Any
    units: Optional[str] = None
    source_type: Optional[str] = None
    source_ids: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    observed_at: Optional[str] = None
    as_of: Optional[str] = None
    quality: Optional[str] = None
    freshness: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def is_provenanced(self) -> bool:
        return bool(self.source_type) and bool(self.observed_at or self.as_of)


@dataclass
class Claim:
    """A derived, non-authoritative statement that must trace to facts/evidence."""

    text: str
    claim_type: str
    source_type: Optional[str] = None
    as_of: Optional[str] = None
    quality: Optional[str] = None
    confidence: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ModelEstimate:
    """A model-produced estimate / scenario. Explicitly NOT a world fact.

    source_type is fixed to MODEL_INFERENCE; it can never be promoted to Fact.
    """

    key: str
    value: Any
    method: Optional[str] = None
    source_type: str = SOURCE_MODEL_INFERENCE
    as_of: Optional[str] = None
    quality: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Opinion:
    """Critic / specialist output. Non-factual by construction."""

    text: str
    source_type: Optional[str] = None
    as_of: Optional[str] = None
    quality: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FinancialSenseResult:
    """The single normalized envelope returned by every provider query."""

    version: str = "1.0"
    provider: str = ""
    capability: str = ""
    request_id: str = field(default_factory=new_request_id)
    requested_at: str = field(default_factory=utcnow_iso)
    completed_at: Optional[str] = None
    status: str = STATUS_OK
    subject: Subject = field(default_factory=Subject)
    as_of: Optional[str] = None
    observed_at: Optional[str] = None
    source_age_seconds: Optional[float] = None
    facts: list[Fact] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    estimates: list[ModelEstimate] = field(default_factory=list)
    opinions: list[Opinion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provenance: Optional[Provenance] = None
    quality: Quality = field(default_factory=Quality)
    authority: str = AUTHORITY
    data: dict = field(default_factory=dict)

    def set_status(self, status: str) -> "FinancialSenseResult":
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        self.status = status
        return self

    def complete(self) -> "FinancialSenseResult":
        self.completed_at = utcnow_iso()
        return self

    def add_fact(self, fact: Fact) -> "FinancialSenseResult":
        self.facts.append(fact)
        return self

    def add_warning(self, warning: str) -> "FinancialSenseResult":
        self.warnings.append(warning)
        return self

    def add_claim(self, claim: Claim) -> "FinancialSenseResult":
        self.claims.append(claim)
        return self

    def add_estimate(self, estimate: ModelEstimate) -> "FinancialSenseResult":
        self.estimates.append(estimate)
        return self

    def validate(self) -> list[str]:
        """Return a list of violations. Empty list == valid.

        Enforced here (fail closed):
          * status must be a known status
          * authority is fixed to READ_ONLY_ADVISORY
          * a FACT must be backed by a fact-capable source (NOT MODEL_INFERENCE /
            MEMORY_CONTEXT), and must carry observed_at or as_of AND quality
          * a CLAIM must carry a source_type (or be explicitly UNSUPPORTED)
          * a ModelEstimate must be MODEL_INFERENCE (never a Fact)
        """
        errors: list[str] = []
        if self.status not in VALID_STATUSES:
            errors.append(f"invalid status {self.status!r}")
        if self.authority != AUTHORITY:
            errors.append(f"authority must be {AUTHORITY}, got {self.authority!r}")
        for i, fact in enumerate(self.facts):
            if not fact.source_type:
                errors.append(f"facts[{i}] ({fact.key}) lacks source_type")
            elif not can_back_fact(fact.source_type):
                errors.append(
                    f"facts[{i}] ({fact.key}) source_type {fact.source_type!r} "
                    f"cannot back a FACT"
                )
            if not (fact.observed_at or fact.as_of):
                errors.append(f"facts[{i}] ({fact.key}) lacks observed_at/as_of")
            if not fact.quality:
                errors.append(f"facts[{i}] ({fact.key}) lacks quality")
        for i, claim in enumerate(self.claims):
            if not claim.source_type and claim.claim_type != "UNSUPPORTED":
                errors.append(f"claims[{i}] lacks source_type")
        for i, est in enumerate(self.estimates):
            if est.source_type != SOURCE_MODEL_INFERENCE:
                errors.append(
                    f"estimates[{i}] ({est.key}) must be MODEL_INFERENCE, got "
                    f"{est.source_type!r}"
                )
        return errors

    def to_dict(self) -> dict:
        d = {
            "version": self.version,
            "provider": self.provider,
            "capability": self.capability,
            "request_id": self.request_id,
            "requested_at": self.requested_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "subject": self.subject.to_dict(),
            "as_of": self.as_of,
            "observed_at": self.observed_at,
            "source_age_seconds": self.source_age_seconds,
            "facts": [f.to_dict() for f in self.facts],
            "claims": [c.to_dict() for c in self.claims],
            "estimates": [e.to_dict() for e in self.estimates],
            "opinions": [o.to_dict() for o in self.opinions],
            "warnings": list(self.warnings),
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "quality": self.quality.to_dict(),
            "authority": self.authority,
            "data": self.data,
        }
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


def make_result(
    provider: str,
    capability: str,
    status: str = STATUS_OK,
    subject: Optional[Subject] = None,
    provenance: Optional[Provenance] = None,
) -> FinancialSenseResult:
    """Convenience constructor that validates the status up front."""
    r = FinancialSenseResult(provider=provider, capability=capability)
    r.set_status(status)
    if subject is not None:
        r.subject = subject
    if provenance is not None:
        r.provenance = provenance
    return r
