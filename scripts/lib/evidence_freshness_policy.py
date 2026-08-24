"""Evidence-class freshness vs retention.

Retention age (how long we keep a row) is not decision freshness (whether the
row may still answer a question). One universal Hermes TTL is not sufficient.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "EvidenceFreshnessPolicy@v1"

# Decision-freshness windows. Retention stays in hermes_librarian/retention.py.
DECISION_TTL = {
    "intraday_technical": timedelta(hours=6),
    "price_market_state": timedelta(hours=6),
    "breaking_news": timedelta(hours=12),
    "news_catalyst": timedelta(hours=36),
    "catalyst": timedelta(hours=36),
    "analyst_action": timedelta(days=14),
    "earnings_scheduled": timedelta(days=14),
    "earnings_result": timedelta(days=100),  # until next cycle typically
    "company_guidance": timedelta(days=180),
    "sec_filing": timedelta(days=400),
    "economic_release": timedelta(days=45),
    "fed_event": timedelta(days=45),
    "industry_structure": timedelta(days=365),
    "industry_classification": timedelta(days=365),
    "sector_membership": timedelta(days=365),
    "sector_classification": timedelta(days=365),
    "structural_relationship": timedelta(days=365),
    "supply_chain_relationship": timedelta(days=180),
    "methodology_canon": timedelta(days=3650),
    "hermes_promoted_default": timedelta(days=7),  # legacy hybrid_evidence window
}
POLICY_CLASSES = tuple(DECISION_TTL.keys())

RETENTION_DAYS = {
    "staged_research": 90,
    "promoted_research": 365,
    "score_history": 21,
}


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif value:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    else:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def classify_evidence_class(row: dict[str, Any] | None) -> str:
    r = row or {}
    src = str(r.get("source_type") or r.get("research_type") or r.get("kind") or r.get("evidence_class") or "").lower()
    title = str(r.get("title") or "").lower()
    if "sec" in src or "10-k" in src or "10-q" in src or "8-k" in src:
        return "sec_filing"
    if "scheduled" in src and "earn" in src:
        return "earnings_scheduled"
    if "earn" in src:
        return "earnings_result"
    if "guidance" in src:
        return "company_guidance"
    if "analyst" in src or "pt" in src or "price_target" in src:
        return "analyst_action"
    if "fed" in src or "fomc" in src:
        return "fed_event"
    if "economic" in src or "cpi" in src or "payroll" in src:
        return "economic_release"
    if "supply" in src or "vertical" in str(r.get("relationship") or "").lower():
        return "supply_chain_relationship"
    if "sector" in src:
        return "sector_classification"
    if "industry" in src:
        return "industry_classification"
    if "methodology" in src or "canon" in src:
        return "methodology_canon"
    if "technical" in src or "intraday" in src:
        return "intraday_technical"
    if "price" in src or "quote" in src or "market_state" in src:
        return "price_market_state"
    if "breaking" in src or "breaking" in title:
        return "breaking_news"
    if "news" in src or "catalyst" in src or "headline" in src:
        return "news_catalyst"
    if str(r.get("status") or "").lower() == "promoted":
        return "hermes_promoted_default"
    return "news_catalyst"


def freshness_state(observed_at: Any, *, evidence_class: str, now: datetime | None = None) -> str:
    """CURRENT / AGING / STALE. SUPERSEDED / RETRACTED are caller-supplied."""
    obs = _utc(observed_at)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if obs is None:
        return "STALE"
    ttl = DECISION_TTL.get(evidence_class, DECISION_TTL["hermes_promoted_default"])
    age = current - obs
    if age < timedelta(0):
        return "CURRENT"
    if age <= ttl / 2:
        return "CURRENT"
    if age <= ttl:
        return "AGING"
    return "STALE"


def is_decision_fresh(observed_at: Any, *, evidence_class: str | None = None, row: dict | None = None, now: datetime | None = None) -> bool:
    klass = evidence_class or classify_evidence_class(row)
    return freshness_state(observed_at, evidence_class=klass, now=now) in ("CURRENT", "AGING")
