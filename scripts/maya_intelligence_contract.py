#!/usr/bin/env python3
"""Read-only evidence contract for Maya-sourced and adjacent intelligence.

This module standardizes provenance, freshness, authority, and bounded news
quality across Watch, Proposal, Defense, Sector, and Industry research. It does
not fetch data, persist state, call models, or authorize any downstream action.

Analyst opinions and model outputs are advisory. They can request review but
can never repair missing deterministic evidence or override a failed gate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

CONTRACT_VERSION = "maya-intelligence-evidence-v1"
DOMAINS = ("WATCH", "PROPOSAL", "DEFENSE", "SECTOR", "INDUSTRY")

# authority values:
# deterministic_input: may be consumed by named deterministic checks when current.
# contextual_input: may shape context/ranking, but cannot release or repair a gate.
# display_only: presentation/provenance only.
FIELD_AUTHORITY = {
    "pe": {
        "label": "Trailing P/E",
        "authority": "deterministic_input",
        "domains": {d: "quality_or_valuation_context" for d in DOMAINS},
    },
    "forward_pe": {
        "label": "Forward P/E",
        "authority": "contextual_input",
        "domains": {d: "display_and_independent_review_context" for d in DOMAINS},
    },
    "pb": {
        "label": "Price / Book",
        "authority": "contextual_input",
        "domains": {d: "display_and_valuation_context" for d in DOMAINS},
    },
    "ps": {
        "label": "Price / Sales",
        "authority": "deterministic_input",
        "domains": {d: "preprofit_quality_gate_or_context" for d in DOMAINS},
    },
    "support": {
        "label": "Support",
        "authority": "deterministic_input",
        "domains": {
            "WATCH": "entry_stop_and_invalidation_evidence",
            "PROPOSAL": "proposal_risk_evidence",
            "DEFENSE": "protect_or_reduce_trigger_context",
            "SECTOR": "constituent_entry_context",
            "INDUSTRY": "candidate_entry_context",
        },
    },
    "resistance": {
        "label": "Resistance",
        "authority": "deterministic_input",
        "domains": {
            "WATCH": "entry_target_and_reentry_evidence",
            "PROPOSAL": "proposal_reward_evidence",
            "DEFENSE": "recovery_or_trim_context",
            "SECTOR": "constituent_entry_context",
            "INDUSTRY": "candidate_entry_context",
        },
    },
    "catalysts": {
        "label": "Catalysts",
        "authority": "deterministic_input",
        "domains": {d: "event_block_materiality_and_freshness" for d in DOMAINS},
    },
    "news_quality": {
        "label": "News evidence quality",
        "authority": "contextual_input",
        "domains": {d: "evidence_confidence_and_review_priority" for d in DOMAINS},
    },
    "analyst_rating": {
        "label": "Analyst consensus",
        "authority": "display_only",
        "domains": {d: "corroborative_only_no_release_authority" for d in DOMAINS},
    },
    "analyst_upgrade": {
        "label": "Analyst upgrade",
        "authority": "contextual_input",
        "domains": {d: "time_bounded_catalyst_context_only" for d in DOMAINS},
    },
    "analyst_downgrade": {
        "label": "Analyst downgrade",
        "authority": "contextual_input",
        "domains": {d: "time_bounded_risk_context_only" for d in DOMAINS},
    },
}

_REQUIRED_EVIDENCE_FIELDS = ("provider", "as_of", "provenance_ref")


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_evidence(field: str, record: dict | None, *, now: datetime | None = None,
                       max_age_hours: float | None = None) -> dict:
    """Normalize one evidence item without inventing values or timestamps."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    spec = FIELD_AUTHORITY.get(field)
    source = record if isinstance(record, dict) else {}
    missing = [name for name in _REQUIRED_EVIDENCE_FIELDS if not source.get(name)]
    has_value = source.get("value") is not None
    if not has_value:
        missing.append("value")
    as_of = _parse_time(source.get("as_of"))
    if source.get("as_of") and as_of is None:
        missing.append("valid_as_of")
    age_hours = None
    stale = None
    if as_of is not None:
        age_hours = max(0.0, (now - as_of).total_seconds() / 3600.0)
        stale = bool(max_age_hours is not None and age_hours > max_age_hours)
    state = "MISSING" if missing else "STALE" if stale else "CURRENT"
    return {
        "contract": CONTRACT_VERSION,
        "field": field,
        "label": (spec or {}).get("label", field),
        "authority": (spec or {}).get("authority", "display_only"),
        "value": source.get("value") if has_value else None,
        "provider": source.get("provider"),
        "as_of": as_of.isoformat() if as_of else source.get("as_of"),
        "provenance_ref": source.get("provenance_ref"),
        "methodology_version": source.get("methodology_version"),
        "quality": source.get("quality"),
        "age_hours": round(age_hours, 2) if age_hours is not None else None,
        "max_age_hours": max_age_hours,
        "state": state,
        "missing": sorted(set(missing)),
        "deterministic_usable": bool(
            spec and spec["authority"] == "deterministic_input" and state == "CURRENT"
        ),
        "may_override_gate": False,
    }


def bounded_news_quality(*, source_reliability: int | None, freshness: int | None,
                         primary_source_proximity: int | None, corroboration: int | None,
                         materiality: int | None) -> dict:
    """Return an explainable 1-5 evidence-quality rating, or INSUFFICIENT.

    Inputs are ordinal integers from 1 to 5. The result measures evidence
    quality—not bullishness, expected return, or trade readiness.
    """
    dimensions = {
        "source_reliability": source_reliability,
        "freshness": freshness,
        "primary_source_proximity": primary_source_proximity,
        "corroboration": corroboration,
        "materiality": materiality,
    }
    invalid = [name for name, value in dimensions.items()
               if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 5]
    if invalid:
        return {
            "contract": CONTRACT_VERSION,
            "state": "INSUFFICIENT_EVIDENCE",
            "rating": None,
            "dimensions": dimensions,
            "missing_or_invalid": invalid,
            "meaning": "news evidence quality only; not sentiment or trade authority",
            "may_override_gate": False,
        }
    raw = sum(dimensions.values()) / len(dimensions)
    rating = max(1, min(5, int(raw + 0.5)))
    return {
        "contract": CONTRACT_VERSION,
        "state": "RATED",
        "rating": rating,
        "raw_average": round(raw, 2),
        "dimensions": dimensions,
        "explanation": [f"{name}={value}/5" for name, value in dimensions.items()],
        "meaning": "news evidence quality only; not sentiment or trade authority",
        "may_override_gate": False,
    }


def domain_authority_matrix() -> list[dict]:
    """Return a stable read-only matrix for API/UI presentation and audits."""
    rows: list[dict] = []
    for field, spec in FIELD_AUTHORITY.items():
        for domain in DOMAINS:
            rows.append({
                "contract": CONTRACT_VERSION,
                "domain": domain,
                "field": field,
                "label": spec["label"],
                "authority": spec["authority"],
                "consumption": spec["domains"][domain],
                "may_override_deterministic_gate": False,
            })
    return rows
