"""
CIO Domain Evidence — Typed collection contract for evidence quality.

Provides the DomainEvidence dataclass, reason_code enumeration, and typed
collection result contract for all domain evidence collectors.

Gate-C component. Replaces bare dict returns and silent except:pass patterns
with structured DomainEvidence results.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


QUALITY_STATE_AVAILABLE = "AVAILABLE"
QUALITY_STATE_PARTIAL = "PARTIAL"
QUALITY_STATE_STALE = "STALE"
QUALITY_STATE_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
QUALITY_STATE_CONFLICTED = "CONFLICTED"
QUALITY_STATE_ERROR = "ERROR"
QUALITY_STATE_NOT_APPLICABLE = "NOT_APPLICABLE"

BLOCKING_QUALITY_STATES = frozenset({
    QUALITY_STATE_DATA_UNAVAILABLE,
    QUALITY_STATE_ERROR,
    QUALITY_STATE_STALE,
    QUALITY_STATE_CONFLICTED,
})


class ReasonCode:
    SOURCE_FILE_MISSING = "SOURCE_FILE_MISSING"
    SOURCE_PARSE_FAILED = "SOURCE_PARSE_FAILED"
    SOURCE_SCHEMA_MISMATCH = "SOURCE_SCHEMA_MISMATCH"
    DB_CONNECTION_FAILED = "DB_CONNECTION_FAILED"
    DB_QUERY_FAILED = "DB_QUERY_FAILED"
    COLLECTOR_EXCEPTION = "COLLECTOR_EXCEPTION"
    COLLECTOR_UNSUPPORTED = "COLLECTOR_UNSUPPORTED"
    NO_ADAPTER_REGISTERED = "NO_ADAPTER_REGISTERED"
    EMPTY_VALID_RESULT = "EMPTY_VALID_RESULT"
    CIRCULAR_DEPENDENCY = "CIRCULAR_DEPENDENCY"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    FRESHNESS_EXCEEDED = "FRESHNESS_EXCEEDED"
    PROVENANCE_INCOMPLETE = "PROVENANCE_INCOMPLETE"
    REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
    UNKNOWN_DOMAIN = "UNKNOWN_DOMAIN"

    ALL = frozenset({
        SOURCE_FILE_MISSING,
        SOURCE_PARSE_FAILED,
        SOURCE_SCHEMA_MISMATCH,
        DB_CONNECTION_FAILED,
        DB_QUERY_FAILED,
        COLLECTOR_EXCEPTION,
        COLLECTOR_UNSUPPORTED,
        NO_ADAPTER_REGISTERED,
        EMPTY_VALID_RESULT,
        CIRCULAR_DEPENDENCY,
        SCHEMA_VERSION_MISMATCH,
        FRESHNESS_EXCEEDED,
        PROVENANCE_INCOMPLETE,
        REQUIRED_FIELD_MISSING,
        UNKNOWN_DOMAIN,
    })


@dataclass
class DomainEvidence:
    """Typed evidence result for a single domain.

    Every collector must return this, never a bare dict or None.
    Replaces the legacy pattern of _load_json() -> {} on failure.
    """

    domain_id: str
    quality_state: str
    reason_code: Optional[str] = None
    source_ref: Optional[str] = None
    as_of: Optional[str] = None
    collected_at: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    partial_fields: Optional[list[str]] = None
    error_detail: Optional[dict[str, Any]] = None
    gap_reason: Optional[str] = None
    source_lineage: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.collected_at is None:
            self.collected_at = datetime.now(timezone.utc).isoformat()

    @property
    def is_blocking(self) -> bool:
        return self.quality_state in BLOCKING_QUALITY_STATES

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "domain_id": self.domain_id,
            "quality_state": self.quality_state,
            "collected_at": self.collected_at,
        }
        if self.reason_code:
            result["reason_code"] = self.reason_code
        if self.source_ref:
            result["source_ref"] = self.source_ref
        if self.as_of:
            result["as_of"] = self.as_of
        if self.data is not None:
            result["data"] = self.data
        if self.partial_fields:
            result["partial_fields"] = self.partial_fields
        if self.error_detail:
            result["error_detail"] = self.error_detail
        if self.gap_reason:
            result["gap_reason"] = self.gap_reason
        if self.source_lineage:
            result["source_lineage"] = self.source_lineage
        return result

    @classmethod
    def available(cls, domain_id: str, data: dict[str, Any], *,
                  source_ref: str = "", as_of: Optional[str] = None) -> "DomainEvidence":
        if not data:
            raise EvidenceIntegrityError(
                f"DomainEvidence.available({domain_id}): data must be non-empty"
            )
        return cls(domain_id=domain_id, quality_state=QUALITY_STATE_AVAILABLE,
                   source_ref=source_ref, as_of=as_of, data=data)

    @classmethod
    def partial(cls, domain_id: str, data: dict[str, Any], *,
                source_ref: str = "", as_of: Optional[str] = None,
                partial_fields: Optional[list[str]] = None,
                gap_reason: Optional[str] = None) -> "DomainEvidence":
        return cls(domain_id=domain_id, quality_state=QUALITY_STATE_PARTIAL,
                   source_ref=source_ref, as_of=as_of, data=data,
                   partial_fields=partial_fields, gap_reason=gap_reason)

    @classmethod
    def unavailable(cls, domain_id: str, *,
                    reason_code: str = ReasonCode.SOURCE_FILE_MISSING,
                    source_ref: str = "", gap_reason: str = "") -> "DomainEvidence":
        return cls(domain_id=domain_id, quality_state=QUALITY_STATE_DATA_UNAVAILABLE,
                   reason_code=reason_code, source_ref=source_ref, gap_reason=gap_reason)

    @classmethod
    def error(cls, domain_id: str, *,
              reason_code: str = ReasonCode.COLLECTOR_EXCEPTION,
              source_ref: str = "",
              error_detail: Optional[dict[str, Any]] = None) -> "DomainEvidence":
        return cls(domain_id=domain_id, quality_state=QUALITY_STATE_ERROR,
                   reason_code=reason_code, source_ref=source_ref, error_detail=error_detail)

    @classmethod
    def stale(cls, domain_id: str, data: dict[str, Any], *,
              source_ref: str = "", as_of: Optional[str] = None) -> "DomainEvidence":
        return cls(domain_id=domain_id, quality_state=QUALITY_STATE_STALE,
                   source_ref=source_ref, as_of=as_of, data=data,
                   reason_code=ReasonCode.FRESHNESS_EXCEEDED)

    @classmethod
    def conflicted(cls, domain_id: str, data: dict[str, Any], *,
                   source_ref: str = "", gap_reason: str = "") -> "DomainEvidence":
        return cls(domain_id=domain_id, quality_state=QUALITY_STATE_CONFLICTED,
                   source_ref=source_ref, data=data, gap_reason=gap_reason)

    @classmethod
    def not_applicable(cls, domain_id: str) -> "DomainEvidence":
        return cls(domain_id=domain_id, quality_state=QUALITY_STATE_NOT_APPLICABLE)


class EvidenceIntegrityError(ValueError):
    """Raised when an evidence result violates the typed contract."""


class UnknownDomainError(KeyError):
    """Raised when a domain is not declared in the capability registry."""


def load_json_evidence(domain_id: str, file_path: str, *,
                       source_ref: str = "",
                       as_of_field: str = "as_of") -> DomainEvidence:
    """Load JSON evidence from a file with typed error handling.

    Distinguishes: file missing -> DATA_UNAVAILABLE, parse error -> ERROR,
    empty valid -> AVAILABLE (caller validates schema).
    """
    if not os.path.exists(file_path):
        return DomainEvidence.unavailable(
            domain_id, reason_code=ReasonCode.SOURCE_FILE_MISSING,
            source_ref=source_ref, gap_reason=f"Source file not found: {file_path}")

    try:
        with open(file_path) as f:
            raw = f.read().strip()
    except OSError as exc:
        return DomainEvidence.error(
            domain_id, reason_code=ReasonCode.COLLECTOR_EXCEPTION,
            source_ref=source_ref, error_detail={"error": str(exc)})

    if not raw:
        return DomainEvidence.unavailable(
            domain_id, reason_code=ReasonCode.EMPTY_VALID_RESULT,
            source_ref=source_ref, gap_reason=f"Source file is empty: {file_path}")

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return DomainEvidence.error(
            domain_id, reason_code=ReasonCode.SOURCE_PARSE_FAILED,
            source_ref=source_ref, error_detail={"error": str(exc)})

    if not isinstance(data, (dict, list)):
        return DomainEvidence.error(
            domain_id, reason_code=ReasonCode.SOURCE_SCHEMA_MISMATCH,
            source_ref=source_ref,
            error_detail={"error": f"Expected dict/list, got {type(data).__name__}"})

    as_of = None
    if isinstance(data, dict) and as_of_field in data:
        as_of = data[as_of_field]

    if isinstance(data, list) and len(data) == 0:
        return DomainEvidence.available(domain_id, {"items": []}, source_ref=source_ref)

    return DomainEvidence.available(domain_id, data=data, source_ref=source_ref, as_of=as_of)


def safe_collect(domain_id: str, collector_fn, *args,
                 source_ref: str = "", **kwargs) -> DomainEvidence:
    """Wrap a collector so any exception becomes a typed ERROR result."""
    try:
        result = collector_fn(*args, **kwargs)
    except UnknownDomainError:
        raise
    except Exception as exc:
        return DomainEvidence.error(
            domain_id, reason_code=ReasonCode.COLLECTOR_EXCEPTION,
            source_ref=source_ref,
            error_detail={"error": str(exc), "exception_type": type(exc).__name__})

    if isinstance(result, DomainEvidence):
        if result.domain_id != domain_id:
            raise EvidenceIntegrityError(
                f"Collector for {domain_id} returned evidence for {result.domain_id}")
        return result
    if isinstance(result, dict):
        return DomainEvidence.available(domain_id, data=result, source_ref=source_ref)
    raise EvidenceIntegrityError(
        f"Collector for {domain_id} returned {type(result).__name__}")
