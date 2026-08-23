"""Governed Hermes + independent-source evidence helpers.

Hermes is a research contributor, never the sole primary authority.  This
module is read-only: it normalizes promoted Hermes rows, applies freshness
policy, and creates a deterministic refresh request for the scheduler/outbox.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "HybridEvidenceRefreshRequest@v1"
HERMES_TTL_DAYS = 7


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    elif value:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    else:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def is_fresh(value: Any, *, now: datetime | None = None, ttl_days: int = HERMES_TTL_DAYS) -> bool:
    observed = _utc(value)
    current = now or datetime.now(timezone.utc)
    if observed is None:
        return False
    return observed <= current.astimezone(timezone.utc) and current.astimezone(timezone.utc) - observed <= timedelta(days=ttl_days)


def _urls(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [value]
    if isinstance(value, dict):
        value = list(value.values())
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, str) and item.startswith(("http://", "https://")):
            out.append(item)
        elif isinstance(item, dict):
            url = item.get("url") or item.get("href")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                out.append(url)
    return list(dict.fromkeys(out))


def normalize_hermes_row(row: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any] | None:
    """Return a curated evidence item, or ``None`` when it is not admissible."""
    symbol = str(row.get("symbol") or "").upper().strip()
    status = str(row.get("status") or "").lower()
    urls = _urls(row.get("source_urls_json") or row.get("source_urls"))
    freshness = row.get("freshness_date") or row.get("created_at")
    thesis_type = str(row.get("thesis_type") or "mixed").lower()
    if not symbol or status != "promoted" or not urls or not is_fresh(freshness, now=now):
        return None
    polarity = {"bullish": "SUPPORTING", "bearish": "CONTRADICTORY"}.get(thesis_type, "CONTEXT")
    source_id = row.get("id")
    return {
        "source_type": "hermes_research",
        "source_id": str(source_id) if source_id is not None else None,
        "symbol": symbol,
        "title": str(row.get("topic") or "Hermes research")[:200],
        "fact": str(row.get("summary") or row.get("thesis") or "")[:500],
        "polarity": polarity,
        "quality": "HERMES_CURATED",
        "rag_status": "approved",
        "observed_at": str(freshness),
        "url": urls[0],
        "provenance": {
            "source_family": "hermes",
            "independence_group": "hermes",
            "source_urls": urls,
            "confidence_score": row.get("confidence_score"),
            "curation_status": status,
        },
        "authority": AUTHORITY,
    }


def build_refresh_request(
    symbol: str,
    *,
    gaps: list[str],
    now: datetime | None = None,
    reason: str = "evidence_gap",
) -> dict[str, Any]:
    """Build an idempotent request; callers decide whether/how to enqueue it."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    normalized = sorted(set(str(g) for g in gaps if g))
    key = {"symbol": symbol.upper(), "gaps": normalized, "reason": reason}
    return {
        "schema": SCHEMA,
        "request_id": "refresh_" + _digest(key),
        "symbol": symbol.upper(),
        "reason": reason,
        "gaps": normalized,
        "source_families": ["hermes", "primary", "structured", "independent_news"],
        "requested_at": current.isoformat(),
        "expires_at": (current + timedelta(hours=24)).isoformat(),
        "status": "PLANNED",
        "enqueue": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }
