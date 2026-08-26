"""Governed Hermes + independent-source evidence helpers.

Hermes is a research contributor, never the sole primary authority.  This
module is read-only: it normalizes promoted Hermes rows, applies freshness
policy, and creates a deterministic refresh request for the scheduler/outbox.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "HybridEvidenceRefreshRequest@v1"
HERMES_TTL_DAYS = 7  # SUPERSEDED as default-for-all; see EvidenceFreshnessPolicy@v1. Kept as news/promoted default.


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
    request_id = "refresh_" + _digest(key)
    trace_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:{request_id}"))
    return {
        "schema": SCHEMA,
        "request_id": request_id,
        "trace_id": trace_id,
        "symbol": symbol.upper(),
        "subject_key": f"ticker:{symbol.upper()}",
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


def enqueue_refresh_request(request: dict[str, Any], *, root: str | None = None) -> dict[str, Any]:
    """Persist a refresh request through the existing Hermes queue.

    This is deliberately an explicit side effect. Callers must opt in with an
    enqueue flag; the request remains research-only and cannot publish a thesis.
    """
    symbol = str(request.get("symbol") or "").upper()
    if not symbol:
        return {"ok": False, "error": "symbol_required"}
    try:
        from scripts.lib.cio_hermes_research import enqueue_research_request
    except ImportError:  # pragma: no cover
        from lib.cio_hermes_research import enqueue_research_request  # type: ignore
    plan = {
        "plan_id": str(request.get("request_id") or ""),
        "trace_id": str(request.get("trace_id") or ""),
        "symbols": [symbol],
        "situation_type": "SYMBOL_EVIDENCE_REFRESH",
        "reason": f"Evidence refresh required: {', '.join(request.get('gaps') or [])}",
        "thesis_version": "",
    }
    questions = [
        {"question_id": "q_support", "intent": "support", "text": f"Find fresh supporting evidence for {symbol}."},
        {"question_id": "q_counter", "intent": "counter", "text": f"Find fresh contradictory/risk evidence for {symbol}."},
        {"question_id": "q_primary", "intent": "primary", "text": f"Find an approved primary or independent source for {symbol}."},
    ]
    result = enqueue_research_request(
        plan,
        reason=plan["reason"],
        priority="high",
        questions=questions,
        force_refresh=True,
        actor_id="symbol_thesis_freshness",
    )
    memory_id = None
    if result.get("ok") and result.get("research_id"):
        try:
            from scripts.lib.agent_durable_memory import get_durable_provider
            provider = get_durable_provider(root)
            memory_id = provider.add_candidate({
                "memory_type": "RESEARCH_REFERENCE",
                "subject": f"Research refresh requested for {symbol}",
                "content": plan["reason"],
                "symbols": [symbol],
                "source_event_ids": [str(request.get("trace_id")), str(result.get("research_id"))],
                "source_refs": [f"hermes_request:{result.get('research_id')}", f"trace:{request.get('trace_id')}"],
                "plan_ids": [str(request.get("request_id"))],
                "trace_id": request.get("trace_id"),
                "subject_key": f"ticker:{symbol}",
                "status": "CANDIDATE",
                "confidence": 0.5,
                "authority_class": "NON_AUTHORITATIVE_CONTEXT",
            })
        except Exception:
            memory_id = None
    return {
        "ok": bool(result.get("ok")),
        "request_id": request.get("request_id"),
        "trace_id": request.get("trace_id"),
        "research_id": result.get("research_id"),
        "memory_id": memory_id,
        "result": result,
    }
