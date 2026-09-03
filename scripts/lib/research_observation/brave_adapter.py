#!/usr/bin/env python3
"""Wrap a Brave router :class:`Outcome` in a ``ResearchObservation@v1`` envelope.

Why a search result needs an envelope at all
--------------------------------------------
A Brave hit is a **discovery artifact**: someone's summary of a page, retrieved
by a keyword match. It is not a filing, not a native social post, and not a
verified fact. The provenance contract already has a vocabulary for exactly that
distinction, and this adapter is what stops a snippet from entering the system
as though it were evidence of the same standing as an 8-K.

The load-bearing choice here is ``QualityStatus.UNVERIFIED``.

``UNVERIFIED`` is in ``EligibilityPolicy.blocking_quality``, so a wrapped Brave
result is **never** ``ELIGIBLE``. With a ``degraded_label`` attached it resolves
to ``DISPLAY_ONLY`` for display consumers and ``INELIGIBLE`` for proposal and
agent consumers — which is precisely the contract's rule that low-quality
results "remain visible as degraded research but are not proposal-eligible".

That holds even for a 200 with five good results from ``sec.gov``. Discovering
a primary source is not the same as having ingested it: ``is_primary_source``
marks the URL as worth acquiring through the canonical filing lane, and until
that acquisition happens the snippet remains unverified.

Status mapping
--------------

===========================  ==================  ====================
Router status                Freshness           Meaning
===========================  ==================  ====================
``OK`` / ``CACHED`` /        ``FRESH``           served, results present
``COALESCED`` (w/ results)
``OK``/``CACHED`` (empty)    ``GAP``             served, nothing found
``EMPTY``                    ``GAP``             provider returned zero
``DENIED_*`` /               ``INELIGIBLE``      blocked by policy or budget —
``BUDGET_UNAVAILABLE``                           **not** a freshness claim
transport / HTTP / parse     ``ERROR``           producer failure
===========================  ==================  ====================

A denial maps to ``INELIGIBLE`` rather than ``NO_DATA`` deliberately: "we were
not allowed to ask" is a policy state, and recording it as absence would be the
same conflation the router's ``Status`` vocabulary exists to prevent.

``READ_ONLY_ADVISORY``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from .contract import ResearchObservation, make_research_observation
from .statuses import (
    EntitlementStatus,
    FallbackState,
    FreshnessStatus,
    QualityStatus,
)

SOURCE_IDENTITY = "brave_search_discovery"
PROVIDER = "brave"

#: Router statuses that mean the provider served an answer.
_SERVED = {"OK", "EMPTY", "CACHED", "COALESCED"}

#: Router statuses that mean we were refused before reaching the provider.
_DENIED = {
    "DENIED_NO_KEY",
    "DENIED_BUDGET",
    "DENIED_RESERVE",
    "DENIED_PURPOSE_QUOTA",
    "DENIED_POLICY",
    "DENIED_NO_EVIDENCE_GAP",
    "DENIED_WEEKEND",
    "BUDGET_UNAVAILABLE",
}


def _freshness_for(status: str, has_results: bool) -> FreshnessStatus:
    if status in _DENIED:
        return FreshnessStatus.INELIGIBLE
    if status in _SERVED:
        return FreshnessStatus.FRESH if has_results else FreshnessStatus.GAP
    return FreshnessStatus.ERROR


def wrap_brave_outcome(
    outcome: Any,
    *,
    run_id: str,
    trace_id: str,
    symbol_or_entity: Optional[str] = None,
    now: Optional[datetime] = None,
) -> ResearchObservation:
    """Wrap one router ``Outcome`` as a provenance-complete observation.

    ``outcome`` is duck-typed rather than imported, so this module does not
    create a circular dependency on the router.
    """
    now = now or datetime.now(timezone.utc)
    iso = now.replace(microsecond=0).isoformat()

    status = getattr(getattr(outcome, "status", None), "value", None) or str(getattr(outcome, "status", ""))
    results = list(getattr(outcome, "results", []) or [])
    has_results = bool(results)
    freshness = _freshness_for(status, has_results)

    payload = {
        "query": getattr(outcome, "query", ""),
        "fingerprint": getattr(outcome, "fingerprint", ""),
        "purpose": getattr(outcome, "purpose", ""),
        "priority": getattr(outcome, "priority", None),
        "caller": getattr(outcome, "caller", ""),
        "endpoint": getattr(outcome, "endpoint", "web"),
        "router_status": status,
        "provider_billed": bool(getattr(outcome, "provider_billed", False)),
        "cache_hit": bool(getattr(outcome, "cache_hit", False)),
        "http_status": getattr(outcome, "http_status", None),
        "latency_ms": getattr(outcome, "latency_ms", None),
        "results": [
            {
                "title": getattr(r, "title", ""),
                "url": getattr(r, "url", ""),
                "description": getattr(r, "description", ""),
                "age": getattr(r, "age", ""),
                "source_domain": getattr(r, "source_domain", ""),
                # Stamped on every result, at every layer, on purpose.
                "attribution": getattr(r, "attribution", "SEARCH_DISCOVERY"),
                "is_primary_source": bool(getattr(r, "is_primary_source", False)),
            }
            for r in results
        ],
    }

    note = ""
    try:
        note = outcome.degradation_note()
    except Exception:
        note = getattr(outcome, "reason", "") or ""

    # Always labelled, including on the happy path: a snippet is unverified even
    # when the request succeeded, so a display consumer must always be able to
    # show *why* this is not decision-grade.
    degraded_label = "SEARCH_DISCOVERY — unverified search snippet, not a filing, native social post, or verified fact"
    if note:
        degraded_label = f"{degraded_label}. {note}"

    return make_research_observation(
        source_identity=SOURCE_IDENTITY,
        provider=PROVIDER,
        symbol_or_entity=symbol_or_entity,
        freshness_status=freshness,
        # UNVERIFIED is blocking for proposal eligibility by design — see the
        # module docstring. Do not "upgrade" this to OK for a 200 response.
        quality_status=QualityStatus.UNVERIFIED,
        entitlement_status=(EntitlementStatus.LICENSED if status not in _DENIED else EntitlementStatus.UNAVAILABLE),
        provider_at=getattr(outcome, "as_of", None) or iso,
        observed_at=getattr(outcome, "as_of", None) or iso,
        received_at=iso,
        normalized_at=iso,
        run_id=run_id,
        trace_id=trace_id,
        payload=payload,
        calculation_or_model_version="BraveResearchRouter@v1",
        # The fingerprint versions the *request* (normalised query + endpoint +
        # freshness + count). Two observations sharing it answered the same
        # question, which is what replay suppression keys on.
        sequence_or_version=getattr(outcome, "fingerprint", "") or "unversioned",
        freshness_age_seconds=0.0,
        fallback_state=FallbackState.NONE,
        raw_evidence_ref=f"brave:{getattr(outcome, 'fingerprint', '')}",
        degraded_label=degraded_label,
        # A denial or an error produced no durable research output. Claiming
        # otherwise is the LOG_ONLY_SUCCESS_WITHOUT_DURABLE_OUTPUT failure the
        # join rule exists to catch.
        durable_output_present=has_results,
        log_success_claimed=status in _SERVED,
    )


def evidence_gap_signature(query: str, symbol: Optional[str] = None) -> str:
    """Stable id for "this specific question was asked".

    Lets a caller record that a gap was closed, and lets a replay of identical
    evidence be recognised as ``NO_NEW_INFO`` rather than a new finding.
    """
    basis = f"{(symbol or '').upper()}|{' '.join((query or '').lower().split())}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]
