"""Provider protocol and base class for financial_senses providers.

A provider is a read-only capability surface. It exposes `health`,
`capabilities`, and `query(capability, request) -> FinancialSenseResult`.

This is NOT an MCP server. It is the provider contract the future governed MCP
gateway (built by the Agent Intelligence Foundation) will register. Providers
must function standalone with no MCP dependency.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

from .result import (
    FinancialSenseResult,
    Provenance,
    Quality,
    STATUS_INVALID_REQUEST,
    STATUS_NOT_CONFIGURED,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    make_result,
    utcnow_iso,
)

MUTABILITY_READ_ONLY = "READ_ONLY"


@dataclass
class ProviderHealth:
    name: str
    version: str
    status: str = STATUS_OK
    checked_at: str = field(default_factory=utcnow_iso)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Capability:
    name: str
    mutability: str = MUTABILITY_READ_ONLY
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    source_policy: dict = field(default_factory=dict)
    timeout_seconds: Optional[float] = None
    rate_limit: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@runtime_checkable
class FinancialSenseProvider(Protocol):
    name: str
    version: str

    def health(self) -> ProviderHealth: ...

    def capabilities(self) -> list[Capability]: ...

    def query(self, capability: str, request: dict) -> FinancialSenseResult: ...


class BaseProvider:
    """Common behavior for all financial-sense providers.

    Subclasses set `name` and `version`, implement `_capabilities()` and
    `_query(capability, request)`, and inherit result-building helpers that
    enforce provenance and the fixed READ_ONLY_ADVISORY authority.
    """

    name: str = "base"
    version: str = "1.0.0"
    source_type: Optional[str] = None
    _configured: bool = True
    _config_detail: str = ""

    def health(self) -> ProviderHealth:
        status = STATUS_OK if self._configured else STATUS_NOT_CONFIGURED
        return ProviderHealth(
            name=self.name,
            version=self.version,
            status=status,
            details={"configured": self._configured, "detail": self._config_detail},
        )

    def capabilities(self) -> list[Capability]:
        return self._capabilities()

    def _capabilities(self) -> list[Capability]:
        return []

    def query(self, capability: str, request: dict) -> FinancialSenseResult:
        request = request or {}
        caps = {c.name: c for c in self.capabilities()}
        if capability not in caps:
            r = self._new(STATUS_UNAVAILABLE, capability)
            r.add_warning(f"capability {capability!r} is not exposed by {self.name}")
            return r.complete()
        if caps[capability].mutability != MUTABILITY_READ_ONLY:
            r = self._new(STATUS_UNAVAILABLE, capability)
            r.add_warning(f"capability {capability!r} is not READ_ONLY")
            return r.complete()
        if not self._configured:
            r = self._new(STATUS_NOT_CONFIGURED, capability)
            r.add_warning(f"{self.name} is not configured: {self._config_detail}")
            return r.complete()
        try:
            return self._query(capability, request).complete()
        except Exception as exc:  # fail-soft: never raise out of query()
            r = self._new(STATUS_UNAVAILABLE, capability)
            r.add_warning(f"{self.name}.{capability} failed: {exc}")
            return r.complete()

    def _query(self, capability: str, request: dict) -> FinancialSenseResult:
        raise NotImplementedError

    # ── helpers ──────────────────────────────────────────────────────────────
    def _new(
        self,
        status: str,
        capability: str,
        provenance: Optional[Provenance] = None,
        quality: Optional[Quality] = None,
    ) -> FinancialSenseResult:
        r = make_result(self.name, capability, status)
        if provenance is not None:
            r.provenance = provenance
        elif self.source_type:
            r.provenance = Provenance(
                source_type=self.source_type,
                provider_version=self.version,
            )
        if quality is not None:
            r.quality = quality
        return r

    def _ok(self, capability: str) -> FinancialSenseResult:
        return self._new(STATUS_OK, capability)

    def _unavailable(self, capability: str, reason: str) -> FinancialSenseResult:
        r = self._new(STATUS_UNAVAILABLE, capability)
        r.add_warning(reason)
        return r

    def _not_configured(self, capability: str, reason: str = "") -> FinancialSenseResult:
        r = self._new(STATUS_NOT_CONFIGURED, capability)
        r.add_warning(reason or f"{self.name} not configured")
        return r

    def _invalid(self, capability: str, reason: str) -> FinancialSenseResult:
        r = self._new(STATUS_INVALID_REQUEST, capability)
        r.add_warning(reason)
        return r


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
