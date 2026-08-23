"""Persistent ticker-first research graph.

This is an additive projection over existing research/RAG stores. It preserves
the originating ticker and relationship context without becoming financial
truth or a second vector database.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

AUTHORITY = "READ_ONLY_ADVISORY"
PROFILE_SCHEMA = "TickerKnowledgeProfile@v1"
ARTIFACT_SCHEMA = "TickerResearchArtifact@v1"
GRAPH_RELATIONSHIPS = ("LINEAR", "LATERAL", "VERTICAL", "MACRO", "CALENDAR")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _digest(*values: Any) -> str:
    value = values[0] if len(values) == 1 else values
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _uuid(value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:ticker:{value}"))


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def graph_path(root: Path | str) -> Path:
    return Path(root) / "data" / "cio" / "ticker_research_graph.jsonl"


def build_profile(symbol: str, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = metadata or {}
    sym = normalize_symbol(symbol)
    return {
        "schema": PROFILE_SCHEMA,
        "ticker_id": _uuid(sym),
        "symbol": sym,
        "classification": meta.get("classification") or meta.get("asset_type") or "UNKNOWN",
        "company": meta.get("company") or meta.get("name"),
        "sector": meta.get("sector"),
        "industry": meta.get("industry"),
        "subindustry": meta.get("subindustry"),
        "themes": sorted(set(str(x) for x in (meta.get("themes") or meta.get("research_tags") or []))),
        "peers": sorted(set(normalize_symbol(x) for x in (meta.get("peers") or []))),
        "holdings": sorted(set(normalize_symbol(x) for x in (meta.get("holdings") or []))),
        "relationships": list(meta.get("relationships") or []),
        "memberships": sorted(set(str(x) for x in (meta.get("memberships") or []))),
        "updated_at": _now(),
        "authority": AUTHORITY,
        "financial_action": False,
    }


def classify_artifact(symbol: str, artifact: dict[str, Any], *, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify one artifact while retaining explicit ticker provenance."""
    sym = normalize_symbol(symbol)
    profile = profile or build_profile(sym)
    related = [normalize_symbol(x) for x in (artifact.get("related_tickers") or artifact.get("peers") or [])]
    tags = set(str(x) for x in (artifact.get("tags") or artifact.get("content_tags") or []))
    if profile.get("sector"):
        tags.add(str(profile["sector"]))
    if profile.get("industry"):
        tags.add(str(profile["industry"]))
    if profile.get("themes"):
        tags.update(str(x) for x in profile["themes"])
    relationship = str(artifact.get("relationship") or "LINEAR").upper()
    if relationship not in GRAPH_RELATIONSHIPS:
        relationship = "LINEAR"
    source_id = str(artifact.get("source_id") or artifact.get("research_id") or artifact.get("id") or "")
    content_hash = str(artifact.get("content_hash") or _digest(artifact.get("title"), artifact.get("summary"), source_id))
    artifact_key = f"{sym}|{source_id}|{content_hash}|{relationship}"
    return {
        "schema": ARTIFACT_SCHEMA,
        "artifact_id": _uuid(artifact_key),
        "trace_id": str(artifact.get("trace_id") or uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:artifact:{artifact_key}")),
        "ticker_id": profile["ticker_id"],
        "symbol": sym,
        "subject_key": f"ticker:{sym}",
        "relationship": relationship,
        "related_tickers": sorted(set(x for x in related if x and x != sym)),
        "tags": sorted(tags),
        "source_type": str(artifact.get("source_type") or "research"),
        "source_id": source_id or None,
        "source_url": artifact.get("source_url") or artifact.get("url"),
        "title": str(artifact.get("title") or "")[:240],
        "summary": str(artifact.get("summary") or artifact.get("fact") or "")[:1000],
        "as_of": artifact.get("as_of") or artifact.get("observed_at") or _now(),
        "provenance": artifact.get("provenance") or {},
        "authority": AUTHORITY,
        "financial_action": False,
    }


def append_record(root: Path | str, record: dict[str, Any]) -> str:
    """Append idempotently to the graph projection using a process lock."""
    path = graph_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact_id = str(record.get("artifact_id") or record.get("ticker_id") or "")
    existing = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
                if row.get("artifact_id"):
                    existing.add(str(row["artifact_id"]))
            except json.JSONDecodeError:
                continue
    if artifact_id in existing:
        return artifact_id
    with path.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        fh.flush()
        fcntl.flock(fh, fcntl.LOCK_UN)
    return artifact_id


def ingest_hermes_result(
    root: Path | str,
    request: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Consume a completed Hermes result into the ticker graph.

    This is deliberately a projection only: Hermes remains the intelligence
    producer and canonical research store.  The projection preserves ticker,
    relationship, source type and trace identity so downstream agents can
    retrieve prior intelligence without re-running research.
    """
    symbol = normalize_symbol(
        result.get("symbol")
        or request.get("symbol")
        or (request.get("metadata") or {}).get("symbol")
    )
    if not symbol:
        return {"ok": False, "error": "symbol_required", "artifacts": 0}
    profile = build_profile(symbol, metadata=request.get("ticker_metadata") or {})
    records: list[str] = []
    base = {
        "research_id": result.get("research_id") or request.get("research_id"),
        "trace_id": request.get("trace_id") or result.get("trace_id"),
        "as_of": result.get("as_of") or result.get("completed_ts"),
        "provenance": {
            "producer": "hermes",
            "request_id": request.get("request_id") or request.get("plan_id"),
            "research_id": result.get("research_id") or request.get("research_id"),
            "source_event_ids": request.get("source_event_ids") or [],
        },
    }
    sources = result.get("sources") or result.get("source_refs") or []
    if isinstance(sources, dict):
        sources = [sources]
    for idx, source in enumerate(sources[:24]):
        if isinstance(source, str):
            source = {"url": source}
        if not isinstance(source, dict):
            continue
        url = source.get("url") or source.get("source_url")
        stype = str(source.get("source_type") or source.get("type") or "hermes_web").lower()
        if "youtube" in stype or "youtu.be" in str(url).lower() or "youtube.com" in str(url).lower():
            stype = "hermes_youtube_transcript"
        elif any(x in stype for x in ("social", "reddit", "x.com", "twitter")):
            stype = "hermes_social"
        artifact = {
            **base,
            "source_id": source.get("source_id") or source.get("id") or url or f"source-{idx}",
            "source_type": stype,
            "source_url": url,
            "title": source.get("title") or result.get("summary") or f"Hermes {symbol} source",
            "summary": source.get("summary") or source.get("snippet") or result.get("summary") or "",
            "tags": source.get("tags") or source.get("content_tags") or [],
            "relationship": source.get("relationship") or "LINEAR",
            "related_tickers": source.get("related_tickers") or [],
        }
        records.append(append_record(root, classify_artifact(symbol, artifact, profile=profile)))
    if not records:
        artifact = {
            **base,
            "source_id": result.get("result_id") or result.get("research_id") or request.get("research_id"),
            "source_type": "hermes_research",
            "title": f"Hermes research {symbol}",
            "summary": result.get("summary") or result.get("reason_summary") or "",
            "tags": result.get("tags") or [],
            "relationship": "LINEAR",
        }
        records.append(append_record(root, classify_artifact(symbol, artifact, profile=profile)))
    return {"ok": True, "symbol": symbol, "artifacts": len(records), "artifact_ids": records}


def ingest_existing_hermes_context(root: Path | str, symbol: str) -> dict[str, Any]:
    """Project already-produced Hermes DB intelligence without re-researching."""
    sym = normalize_symbol(symbol)
    if not sym:
        return {"ok": False, "error": "symbol_required", "artifacts": 0}
    try:
        try:
            from scripts.hermes_data_access import get_hermes_context
        except Exception:
            from hermes_data_access import get_hermes_context  # type: ignore
        context = get_hermes_context(sym, research_limit=12, external_limit=6)
    except Exception as exc:
        return {"ok": False, "error": f"context:{type(exc).__name__}:{exc}", "artifacts": 0}
    records: list[str] = []
    for row in context.get("research") or []:
        urls = row.get("source_urls") or []
        sources = urls or [None]
        for url in sources:
            stype = str(row.get("type") or "hermes_research").lower()
            if "youtube" in stype or "youtube.com" in str(url).lower() or "youtu.be" in str(url).lower():
                stype = "hermes_youtube_transcript"
            elif any(x in stype for x in ("social", "reddit", "twitter", "x_")):
                stype = "hermes_social"
            artifact = classify_artifact(sym, {
                "source_id": f"{row.get('type')}:{url or row.get('topic')}",
                "source_type": stype,
                "source_url": url,
                "title": row.get("topic") or f"Hermes {sym}",
                "summary": row.get("thesis") or row.get("summary"),
                "as_of": row.get("as_of"),
                "relationship": "LINEAR",
                "provenance": {"producer": "hermes_research_intelligence", "status": row.get("status")},
            })
            records.append(append_record(root, artifact))
    for row in context.get("external_lanes") or []:
        artifact = classify_artifact(sym, {
            "source_id": f"external:{row.get('lane')}:{row.get('as_of')}",
            "source_type": f"hermes_external_{str(row.get('lane') or 'lane').lower()}",
            "title": f"Hermes external {row.get('lane') or 'lane'}",
            "summary": row.get("recommendation") or "",
            "as_of": row.get("as_of"),
            "relationship": "LATERAL",
            "provenance": {"producer": "hermes_external_research", "dissent": row.get("dissent")},
        })
        records.append(append_record(root, artifact))
    return {"ok": True, "symbol": sym, "artifacts": len(records), "source": "existing_hermes_intelligence"}


def retrieve_context(root: Path | str, symbol: str, *, limit: int = 50) -> dict[str, Any]:
    sym = normalize_symbol(symbol)
    rows = []
    path = graph_path(root)
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("symbol") == sym or sym in (row.get("related_tickers") or []):
                rows.append(row)
    rows = rows[-max(1, int(limit)):]
    return {
        "schema": "TickerKnowledgeContext@v1",
        "symbol": sym,
        "subject_key": f"ticker:{sym}",
        "linear": [r for r in rows if r.get("relationship") == "LINEAR"],
        "lateral": [r for r in rows if r.get("relationship") == "LATERAL"],
        "vertical": [r for r in rows if r.get("relationship") == "VERTICAL"],
        "macro": [r for r in rows if r.get("relationship") == "MACRO"],
        "calendar": [r for r in rows if r.get("relationship") == "CALENDAR"],
        "artifact_count": len(rows),
        "authority": AUTHORITY,
    }


def seed_profiles(root: Path | str, rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Persist ticker profiles for every tracked universe row."""
    profiles = 0
    path = graph_path(root)
    existing = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
                existing.add(row.get("ticker_id"))
            except json.JSONDecodeError:
                continue
    for row in rows:
        sym = normalize_symbol(row.get("symbol") or row.get("ticker"))
        if not sym:
            continue
        profile = build_profile(sym, metadata=row)
        if profile["ticker_id"] in existing:
            continue
        append_record(root, profile)
        existing.add(profile["ticker_id"])
        profiles += 1
    return {"profiles_created": profiles, "path": str(path), "authority": AUTHORITY}
