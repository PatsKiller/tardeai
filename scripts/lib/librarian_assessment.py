"""LibrarianAssessment@v1 — deterministic artifact critique before any LLM.

Housekeeping (taxonomy/graph/freshness/retention/RAG/backlog) stays in
hermes_librarian. This module answers: does this evidence change what we
already thought?
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from scripts.lib.evidence_freshness_policy import classify_evidence_class, freshness_state

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "LibrarianAssessment@v1"


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def assess_artifact(
    artifact: dict[str, Any] | None,
    *,
    prior_hashes: set[str] | None = None,
    prior_conclusion: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Rule-first critique. Never classifies price/cash/position truth."""
    row = dict(artifact or {})
    content_hash = str(row.get("content_hash") or _digest((row.get("title"), row.get("summary"), row.get("source_url"))))
    prior = prior_hashes or set()
    duplicate = content_hash in prior
    url = str(row.get("source_url") or row.get("url") or "")
    source_ok = bool(url.startswith(("http://", "https://")) or row.get("source_id"))
    klass = classify_evidence_class(row)
    recency = freshness_state(row.get("as_of") or row.get("observed_at") or row.get("created_at"), evidence_class=klass, now=now)
    derived = any(x in url.lower() for x in ("news.google.", "finance.yahoo.com/news", "seekingalpha.com/amp"))
    social = any(x in url.lower() for x in ("twitter.com", "x.com", "reddit.com", "stocktwits.com"))
    aggregator = derived
    primary = source_ok and not derived and not social
    retracted = "retract" in str(row.get("title") or "").lower() or str(row.get("status") or "").lower() == "retracted"
    superseded = str(row.get("status") or "").lower() in ("superseded", "expired")
    material = (not duplicate) and source_ok and recency in ("CURRENT", "AGING") and not retracted
    what_changed = "duplicate" if duplicate else ("stale" if recency == "STALE" else ("new_hash" if material else "insufficient"))
    if duplicate:
        decision = "IGNORE_DUPLICATE"
    elif retracted:
        decision = "ARCHIVE_HISTORY"
    elif recency == "STALE" and not material:
        decision = "NO_NEW_INFO"
    elif material and prior_conclusion:
        decision = "CURATION_REVIEW_REQUIRED"
    elif material:
        decision = "CURRENT_SUPPORT"
    else:
        decision = "NO_NEW_INFO"
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "source_valid": source_ok,
        "source_active": source_ok and not retracted,
        "primary_source": primary,
        "secondary": (not primary) and source_ok and not social,
        "aggregator": aggregator,
        "social": social,
        "duplicate": duplicate,
        "near_duplicate": duplicate,
        "primary_or_derived": "derived" if derived else ("primary" if primary else "primary_or_unknown"),
        "corroborated": None,  # requires peer artifacts; not guessed
        "contradicted": None,
        "material": material,
        "material_to_security": material,
        "material_to_current_thesis": None if not prior_conclusion else material,
        "material_to_portfolio": False,
        "closes_open_gap": False,
        "creates_new_gap": (not source_ok) or recency == "STALE",
        "still_current": recency == "CURRENT",
        "freshness_state": recency,
        "fresh_for_evidence_class": recency in ("CURRENT", "AGING"),
        "superseded": superseded,
        "retraction_present": retracted,
        "retracted": retracted,
        "relevant_to_current_thesis": None if not prior_conclusion else True,
        "what_changed_since_last_curation": what_changed,
        "decision": decision,
        "content_hash": content_hash,
        "evidence_class": klass,
        "source_reputation": None,
        "artifact_quality": "ok" if material else "weak",
        "as_of": (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat(),
    }
