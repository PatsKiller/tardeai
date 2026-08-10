"""
Gate-B: Legacy Watch CIO Authority Gate.

This module provides the gating mechanism for the legacy Watch CIO synthesis
pipeline. During Gate-B, the legacy automatic final CIO synthesis is DISABLED.
Specialist evidence (Maria/Steph/Risk/Tax agent reviews) continues to be
gathered. Historical watchlist_final_synthesis and cio_view records are
preserved.

To be imported by:
  - scripts/process_watchlist_agent_jobs.py
  - scripts/api_v2.py
  - Downstream consumers that read cio_view
"""
from __future__ import annotations

import os
from enum import Enum


class LegacyCIOAuthority(Enum):
    """Gate-B: Legacy Watch CIO authority levels."""
    SPECIALIST_EVIDENCE_ONLY = "specialist_evidence_only"  # Default in Gate-B
    INDEPENDENT_REVIEW_ARTIFACT = "independent_review_artifact"  # Optional future
    FULL_CIO_AUTHORITY = "full_cio_authority"  # Pre-Gate-B legacy mode


# Default during Gate-B: specialist evidence only, no final CIO synthesis
_LEGACY_CIO_MODE = os.environ.get(
    "LEGACY_WATCH_CIO_MODE",
    LegacyCIOAuthority.SPECIALIST_EVIDENCE_ONLY.value,
)


def legacy_cio_authority() -> LegacyCIOAuthority:
    """Return the current legacy Watch CIO authority level."""
    try:
        return LegacyCIOAuthority(_LEGACY_CIO_MODE)
    except ValueError:
        return LegacyCIOAuthority.SPECIALIST_EVIDENCE_ONLY


def legacy_cio_synthesis_enabled() -> bool:
    """Check if legacy Watch automatic final CIO synthesis is enabled."""
    return legacy_cio_authority() == LegacyCIOAuthority.FULL_CIO_AUTHORITY


def legacy_cio_independent_review_enabled() -> bool:
    """Check if legacy Watch independent secondary review is enabled."""
    return legacy_cio_authority() in (
        LegacyCIOAuthority.INDEPENDENT_REVIEW_ARTIFACT,
        LegacyCIOAuthority.FULL_CIO_AUTHORITY,
    )


def classify_cio_view_origin(source: str) -> str:
    """Classify the origin of a cio_view value.

    Returns:
        "AUTHORITATIVE_CIO_ACTION" — from the durable Alex/CIO lifecycle
        "LEGACY_CIO_REVIEW" — from the legacy Watch synthesis pipeline
        "UNKNOWN" — origin cannot be determined
    """
    if source in ("cio_run_worker", "cio_run_store", "alex_cio_synthesis"):
        return "AUTHORITATIVE_CIO_ACTION"
    if source in ("watchlist_cio_synthesis", "process_watchlist_agent_jobs", "legacy_watch"):
        return "LEGACY_CIO_REVIEW"
    return "UNKNOWN"
