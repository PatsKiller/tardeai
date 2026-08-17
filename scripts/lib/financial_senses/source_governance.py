"""Source quality and financial-advisory policy for financial_senses.

Defines the source classes a provider may emit, quality ordering keyed by claim
type (not one global ranking), and validation helpers that keep MODEL_INFERENCE
from being silently promoted to FACT. Pure module: no network, no database.
"""
from __future__ import annotations

from typing import Optional

# ── Source classes ───────────────────────────────────────────────────────────
SOURCE_PRIMARY_REGULATORY = "PRIMARY_REGULATORY"
SOURCE_PRIMARY_GOVERNMENT = "PRIMARY_GOVERNMENT"
SOURCE_CANONICAL_INTERNAL = "CANONICAL_INTERNAL"
SOURCE_APPROVED_MARKET_DATA = "APPROVED_MARKET_DATA"
SOURCE_SECONDARY_RESEARCH = "SECONDARY_RESEARCH"
SOURCE_MEMORY_CONTEXT = "MEMORY_CONTEXT"
SOURCE_MODEL_INFERENCE = "MODEL_INFERENCE"

VALID_SOURCE_TYPES = frozenset(
    {
        SOURCE_PRIMARY_REGULATORY,
        SOURCE_PRIMARY_GOVERNMENT,
        SOURCE_CANONICAL_INTERNAL,
        SOURCE_APPROVED_MARKET_DATA,
        SOURCE_SECONDARY_RESEARCH,
        SOURCE_MEMORY_CONTEXT,
        SOURCE_MODEL_INFERENCE,
    }
)

# A fact must come from one of these. MODEL_INFERENCE and MEMORY_CONTEXT can
# never back a FACT node on their own.
FACT_CAPABLE_SOURCES = frozenset(
    {
        SOURCE_PRIMARY_REGULATORY,
        SOURCE_PRIMARY_GOVERNMENT,
        SOURCE_CANONICAL_INTERNAL,
        SOURCE_APPROVED_MARKET_DATA,
        SOURCE_SECONDARY_RESEARCH,
    }
)

# Quality grades.
QUALITY_HIGH = "HIGH"
QUALITY_MEDIUM = "MEDIUM"
QUALITY_LOW = "LOW"
QUALITY_UNKNOWN = "UNKNOWN"
VALID_QUALITY = frozenset({QUALITY_HIGH, QUALITY_MEDIUM, QUALITY_LOW, QUALITY_UNKNOWN})

# Freshness labels.
FRESHNESS_FRESH = "FRESH"
FRESHNESS_STALE = "STALE"
FRESHNESS_UNKNOWN = "UNKNOWN"

# Completeness labels.
COMPLETENESS_COMPLETE = "COMPLETE"
COMPLETENESS_PARTIAL = "PARTIAL"
COMPLETENESS_UNKNOWN = "UNKNOWN"


# ── Quality ordering by claim type ───────────────────────────────────────────
# Ranking is contextual: the same source may be authoritative for one claim type
# and merely supporting for another. Each list is ordered best → worst.
QUALITY_ORDER: dict[str, list[str]] = {
    "company_filing_fact": [
        SOURCE_PRIMARY_REGULATORY,
        SOURCE_APPROVED_MARKET_DATA,
        SOURCE_SECONDARY_RESEARCH,
        SOURCE_MEMORY_CONTEXT,
        SOURCE_MODEL_INFERENCE,
    ],
    "portfolio_holding": [
        SOURCE_CANONICAL_INTERNAL,
        SOURCE_PRIMARY_REGULATORY,
        SOURCE_MEMORY_CONTEXT,
        SOURCE_MODEL_INFERENCE,
    ],
    "macro_vintage": [
        SOURCE_PRIMARY_GOVERNMENT,
        SOURCE_APPROVED_MARKET_DATA,
        SOURCE_SECONDARY_RESEARCH,
        SOURCE_MODEL_INFERENCE,
    ],
    "instrument_identity": [
        SOURCE_CANONICAL_INTERNAL,
        SOURCE_APPROVED_MARKET_DATA,
        SOURCE_PRIMARY_REGULATORY,
        SOURCE_SECONDARY_RESEARCH,
        SOURCE_MODEL_INFERENCE,
    ],
}


def is_valid_source_type(source_type: str) -> bool:
    return source_type in VALID_SOURCE_TYPES


def can_back_fact(source_type: str) -> bool:
    """True if a source type may back a canonical FACT node."""
    return source_type in FACT_CAPABLE_SOURCES


def quality_rank(source_type: str, claim_type: str) -> int:
    """Return the 0-based rank of source_type for claim_type (lower = better).

    Returns a large value for unknown sources so they sort last.
    """
    order = QUALITY_ORDER.get(claim_type, [])
    try:
        return order.index(source_type)
    except ValueError:
        return len(order) + 100


def best_source(sources: list[str], claim_type: str) -> Optional[str]:
    """Return the highest-quality source for a claim type among candidates."""
    ranked = [s for s in sources if is_valid_source_type(s)]
    if not ranked:
        return None
    return min(ranked, key=lambda s: quality_rank(s, claim_type))


def grade_for_source(source_type: str) -> str:
    """Map a source type to a coarse quality grade."""
    if source_type == SOURCE_PRIMARY_REGULATORY:
        return QUALITY_HIGH
    if source_type in (SOURCE_PRIMARY_GOVERNMENT, SOURCE_CANONICAL_INTERNAL):
        return QUALITY_HIGH
    if source_type == SOURCE_APPROVED_MARKET_DATA:
        return QUALITY_MEDIUM
    if source_type == SOURCE_SECONDARY_RESEARCH:
        return QUALITY_LOW
    if source_type == SOURCE_MEMORY_CONTEXT:
        return QUALITY_LOW
    return QUALITY_UNKNOWN


def validate_source_type(source_type: Optional[str]) -> Optional[str]:
    """Return an error string if source_type is invalid/None, else None."""
    if not source_type:
        return "source_type is required"
    if not is_valid_source_type(source_type):
        return f"unknown source_type {source_type!r}"
    return None


def assert_no_inference_as_fact(source_type: Optional[str]) -> Optional[str]:
    """Return an error if a source type is being promoted to a FACT improperly."""
    if source_type in (SOURCE_MODEL_INFERENCE, SOURCE_MEMORY_CONTEXT):
        return f"{source_type} may not back a FACT node"
    return None
