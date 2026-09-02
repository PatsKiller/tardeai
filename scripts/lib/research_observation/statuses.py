"""Research observation status vocabularies.

FreshnessStatus distinguishes NO_DATA / GAP / STALE / PARTIAL / INELIGIBLE /
ERROR / FRESH. A gap or missing durable output must never be relabeled FRESH.
"""

from __future__ import annotations

from enum import Enum


class FreshnessStatus(str, Enum):
    """Canonical freshness / availability status for research records."""

    NO_DATA = "NO_DATA"  # no durable record exists for the requested key
    GAP = "GAP"  # known missing coverage / category empty (not "current")
    STALE = "STALE"  # durable record exists but exceeds freshness SLA
    PARTIAL = "PARTIAL"  # some fields present; required subset incomplete
    INELIGIBLE = "INELIGIBLE"  # present but blocked by policy (not a freshness claim)
    ERROR = "ERROR"  # producer/join failure; do not treat as current
    FRESH = "FRESH"  # durable output present, within SLA, provenance complete


# Statuses that must NEVER be presented as FRESH or proposal-eligible.
NON_FRESH_STATUSES = frozenset(
    {
        FreshnessStatus.NO_DATA,
        FreshnessStatus.GAP,
        FreshnessStatus.STALE,
        FreshnessStatus.PARTIAL,
        FreshnessStatus.INELIGIBLE,
        FreshnessStatus.ERROR,
    }
)


class QualityStatus(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"


class EntitlementStatus(str, Enum):
    LICENSED = "LICENSED"
    INTERNAL = "INTERNAL"  # first-party / synthetic internal product
    DELAYED_OK = "DELAYED_OK"
    RESTRICTED = "RESTRICTED"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class FallbackState(str, Enum):
    NONE = "NONE"
    VISIBLE_FALLBACK = "VISIBLE_FALLBACK"
    SILENT_FORBIDDEN = "SILENT_FORBIDDEN"  # detected silent path → ineligible


class EligibilityDecision(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    DISPLAY_ONLY = "DISPLAY_ONLY"  # may show with degraded label; never proposal
