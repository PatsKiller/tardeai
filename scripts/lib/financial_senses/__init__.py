"""financial_senses — read-only financial intelligence providers for Trade AI.

This package holds provider-side financial "senses" that can later be
registered against the governed read-only MCP gateway being built by the
separate Agent Intelligence Foundation. It is deliberately NOT a second
SEC ingestion pipeline, NOT a second MCP gateway, and NOT a memory layer.

Authority is fixed to READ_ONLY_ADVISORY: providers enrich evidence, they
never mutate live decisions, holdings, orders, or production state.

Namespaces (all new work lives here, isolated from the other agent):
    scripts/lib/financial_senses/
    tests/financial_senses/
    docs/financial-senses/
    config/financial_senses/
"""
from __future__ import annotations

from .result import (
    AUTHORITY,
    Claim,
    Fact,
    FinancialSenseResult,
    Provenance,
    Quality,
    Subject,
    STATUS_CONFLICT,
    STATUS_INVALID_REQUEST,
    STATUS_NOT_CONFIGURED,
    STATUS_OK,
    STATUS_PARTIAL,
    STATUS_STALE,
    STATUS_UNAVAILABLE,
    VALID_STATUSES,
)
from .provider import (
    BaseProvider,
    Capability,
    FinancialSenseProvider,
    ProviderHealth,
)

__all__ = [
    "AUTHORITY",
    "BaseProvider",
    "Capability",
    "Claim",
    "Fact",
    "FinancialSenseProvider",
    "FinancialSenseResult",
    "Provenance",
    "ProviderHealth",
    "Quality",
    "Subject",
    "STATUS_CONFLICT",
    "STATUS_INVALID_REQUEST",
    "STATUS_NOT_CONFIGURED",
    "STATUS_OK",
    "STATUS_PARTIAL",
    "STATUS_STALE",
    "STATUS_UNAVAILABLE",
    "VALID_STATUSES",
]

__version__ = "1.0.0"
