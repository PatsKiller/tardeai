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
    material = (not duplicate) and source_ok and recency in ("CURRENT", "AGING")
    what_changed = "duplicate" if duplicate else ("stale" if recency == "STALE" else ("new_hash" if material else "insufficient"))
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "source_valid": source_ok,
        "duplicate": duplicate,
        "primary_or_derived": "derived" if derived else "primary_or_unknown",
        "corroborated": None,  # requires peer artifacts; not guessed
        "contradicted": None,
        "material": material,
        "still_current": recency == "CURRENT",
        "freshness_state": recency,
        "superseded": False,
        "retraction_present": "retract" in str(row.get("title") or "").lower(),
        "relevant_to_current_thesis": None if not prior_conclusion else True,
        "what_changed_since_last_curation": what_changed,
        "content_hash": content_hash,
        "evidence_class": klass,
        "as_of": (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat(),
    }
