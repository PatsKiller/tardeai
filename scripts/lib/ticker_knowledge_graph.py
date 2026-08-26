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

from scripts.lib.security_identity import attach_identity_v2

AUTHORITY = "READ_ONLY_ADVISORY"
PROFILE_SCHEMA = "TickerKnowledgeProfile@v1"
ARTIFACT_SCHEMA = "TickerResearchArtifact@v1"
GRAPH_RELATIONSHIPS = ("LINEAR", "LATERAL", "VERTICAL", "MACRO", "CALENDAR")
ENTITY_KINDS = ("ticker", "issuer", "sector", "industry", "subindustry", "theme", "catalyst", "calendar")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _digest(*values: Any) -> str:
    value = values[0] if len(values) == 1 else values
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _uuid(value: str) -> str:
    """Legacy ticker UUID helper retained for stable ticker_id values."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:ticker:{value}"))


def entity_guid(kind: str, value: Any) -> str | None:
    """Return a deterministic identity for a non-financial graph entity.

    UUIDv5 makes re-ingestion and source replay idempotent without using a
    mutable database-generated identifier.  These IDs identify context only;
    they never represent financial truth or execution authority.
    """
    k = str(kind or "").strip().lower()
    normalized = str(value or "").strip().casefold()
    if k not in ENTITY_KINDS or not normalized:
        return None
    if k == "ticker":
        # Ticker IDs predate the richer graph schema. Preserve that namespace
        # so migration and profile seeding remain idempotent across releases.
        return _uuid(normalized.upper())
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:entity:{k}:{normalized}"))


def relationship_guid(source_guid: str, target_guid: str, relationship: str, *, valid_from: Any = None) -> str:
    """Stable identity for one directed ticker-knowledge edge."""
    payload = "|".join((str(source_guid), str(target_guid), str(relationship).upper(), str(valid_from or "")))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:relationship:{payload}"))


def _values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        return [str(value).strip()]
    if isinstance(value, dict):
        value = value.get("name") or value.get("label") or value.get("value") or value.get("symbol")
        return [str(value).strip()] if value else []
    return [str(x).strip() for x in value if str(x).strip()]


def _entity_refs(kind: str, values: Any) -> list[dict[str, str]]:
    refs = []
    for value in _values(values):
        guid = entity_guid(kind, value)
        if guid:
            refs.append({"guid": guid, "label": value})
    return refs


def _edge(
    source: str,
    target: str,
    rel: str,
    kind: str,
    *,
    confirmed: bool,
    producer: str = "ticker_knowledge_graph",
    source_type: str = "ticker_knowledge_profile",
    source_id: str | None = None,
    evidence_artifact_guid: str | None = None,
    source_refs: list | None = None,
) -> dict[str, Any]:
    now = _now()
    return {
        "relationship_guid": relationship_guid(source, target, rel),
        "source_guid": source,
        "target_guid": target,
        "relationship": rel,
        "target_kind": kind,
        "valid_from": None,
        "valid_to": None,
        "observed_at": now,
        "recorded_at": now,
        "last_confirmed_at": now if confirmed else None,
        "status": "CONFIRMED" if confirmed else "CANDIDATE",
        "confidence": 0.8 if confirmed else 0.3,
        "source_entity_guid": source,
        "target_entity_guid": target,
        "relationship_type": rel,
        "relationship_class": kind,
        "source_id": source_id,
        "source_type": source_type,
        "producer": producer,
        "evidence_artifact_guid": evidence_artifact_guid,
        "source_refs": list(source_refs or []),
    }


def _profile_edges(profile: dict[str, Any]) -> list[dict[str, Any]]:
    source = profile["ticker_guid"]
    confirmed = bool(profile.get("company"))
    prov = profile.get("edge_provenance") if isinstance(profile.get("edge_provenance"), dict) else {}
    kw = {
        "confirmed": confirmed,
        "producer": str(prov.get("producer") or "ticker_knowledge_graph"),
        "source_type": str(prov.get("source_type") or "ticker_knowledge_profile"),
        "source_id": prov.get("source_id"),
        "evidence_artifact_guid": prov.get("evidence_artifact_guid"),
        "source_refs": list(prov.get("source_refs") or []),
    }
    edges: list[dict[str, Any]] = []
    for kind, field, rel in (
        ("issuer", "issuer_guid", "LINEAR"),
        ("sector", "sector_guid", "LATERAL"),
        ("industry", "industry_guid", "VERTICAL"),
        ("subindustry", "subindustry_guid", "VERTICAL"),
    ):
        target = profile.get(field)
        if target:
            edges.append(_edge(source, target, rel, kind, **kw))
    for ref in profile.get("theme_refs") or []:
        edges.append(_edge(source, ref["guid"], "MACRO", "theme", **kw))
    for ref in profile.get("peer_refs") or []:
        edges.append(_edge(source, ref["guid"], "LATERAL", "ticker", **kw))
    for ref in profile.get("catalyst_refs") or []:
        edges.append(_edge(source, ref["guid"], "MACRO", "catalyst", **kw))
    for ref in profile.get("calendar_event_refs") or []:
        edges.append(_edge(source, ref["guid"], "CALENDAR", "calendar", **kw))
    return edges


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def graph_path(root: Path | str) -> Path:
    return Path(root) / "data" / "cio" / "ticker_research_graph.jsonl"


def build_profile(symbol: str, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = metadata or {}
    sym = normalize_symbol(symbol)
    ticker_guid = entity_guid("ticker", sym)
    company = meta.get("company") or meta.get("name")
    sector = meta.get("sector")
    industry = meta.get("industry")
    subindustry = meta.get("subindustry")
    themes = sorted(set(_values(meta.get("themes") or meta.get("research_tags"))))
    peers = sorted(set(normalize_symbol(x) for x in _values(meta.get("peers"))))
    catalysts = sorted(set(_values(meta.get("catalysts") or meta.get("catalyst"))))
    calendar_events = sorted(set(_values(meta.get("calendar_events") or meta.get("calendar_event"))))
    profile = {
        "schema": PROFILE_SCHEMA,
        "ticker_id": ticker_guid,  # compatibility alias
        "ticker_guid": ticker_guid,
        "symbol": sym,
        "classification": meta.get("classification") or meta.get("asset_type") or "UNKNOWN",
        "company": company,
        "issuer_guid": meta.get("issuer_guid") or entity_guid("issuer", company),
        "sector": sector,
        "sector_guid": entity_guid("sector", sector),
        "industry": industry,
        "industry_guid": entity_guid("industry", industry),
        "subindustry": subindustry,
        "subindustry_guid": entity_guid("subindustry", subindustry),
        "themes": themes,
        "theme_refs": _entity_refs("theme", themes),
        "theme_guids": [x["guid"] for x in _entity_refs("theme", themes)],
        "peers": peers,
        "peer_refs": [{"guid": entity_guid("ticker", x), "label": x} for x in peers if entity_guid("ticker", x)],
        "peer_guids": [entity_guid("ticker", x) for x in peers if entity_guid("ticker", x)],
        "holdings": sorted(set(normalize_symbol(x) for x in _values(meta.get("holdings")))),
        "holding_guids": [entity_guid("ticker", x) for x in _values(meta.get("holdings")) if entity_guid("ticker", x)],
        "catalysts": catalysts,
        "catalyst_refs": _entity_refs("catalyst", catalysts),
        "catalyst_guids": [x["guid"] for x in _entity_refs("catalyst", catalysts)],
        "calendar_events": calendar_events,
        "calendar_event_refs": _entity_refs("calendar", calendar_events),
        "calendar_event_guids": [x["guid"] for x in _entity_refs("calendar", calendar_events)],
        "memberships": sorted(set(str(x) for x in (meta.get("memberships") or []))),
        "updated_at": _now(),
        "authority": AUTHORITY,
        "financial_action": False,
    }
    if meta.get("security_guid"):
        profile["security_guid"] = meta.get("security_guid")
    if meta.get("listing_guid"):
        profile["listing_guid"] = meta.get("listing_guid")
    if meta.get("edge_provenance"):
        profile["edge_provenance"] = meta.get("edge_provenance")
    profile["relationships"] = _profile_edges(profile)
    profile["relationship_guids"] = [x["relationship_guid"] for x in profile["relationships"]]
    return attach_identity_v2(profile)


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
    # Preserve the existing artifact_id derivation so old JSONL projections
    # remain idempotent when the richer GUID fields are added.
    artifact_guid = _uuid(artifact_key)
    related_refs = _entity_refs("ticker", related)
    sector_refs = _entity_refs("sector", artifact.get("sectors") or artifact.get("sector"))
    industry_refs = _entity_refs("industry", artifact.get("industries") or artifact.get("industry"))
    theme_refs = _entity_refs("theme", artifact.get("themes") or artifact.get("theme") or tags)
    catalyst_refs = _entity_refs("catalyst", artifact.get("catalysts") or artifact.get("catalyst"))
    calendar_refs = _entity_refs("calendar", artifact.get("calendar_events") or artifact.get("calendar_event"))
    edge_targets = [(x["guid"], relationship) for x in related_refs + sector_refs + industry_refs + theme_refs + catalyst_refs + calendar_refs]
    edge_guids = [relationship_guid(profile["ticker_guid"], target, rel) for target, rel in edge_targets]
    return {
        "schema": ARTIFACT_SCHEMA,
        "artifact_id": artifact_guid,  # compatibility alias
        "research_artifact_guid": artifact_guid,
        "trace_id": str(artifact.get("trace_id") or uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:artifact:{artifact_key}")),
        "trace_guid": str(artifact.get("trace_guid") or artifact.get("trace_id") or uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:trace:{artifact_key}")),
        "ticker_id": profile["ticker_guid"],  # compatibility alias
        "ticker_guid": profile["ticker_guid"],
        "symbol": sym,
        "subject_key": f"ticker:{sym}",
        "relationship": relationship,
        "related_tickers": sorted(set(x for x in related if x and x != sym)),
        "related_ticker_guids": [x["guid"] for x in related_refs if x["label"] != sym],
        "sector_guids": [x["guid"] for x in sector_refs],
        "industry_guids": [x["guid"] for x in industry_refs],
        "theme_guids": [x["guid"] for x in theme_refs],
        "catalyst_guids": [x["guid"] for x in catalyst_refs],
        "calendar_event_guids": [x["guid"] for x in calendar_refs],
        "relationship_guid": edge_guids[0] if edge_guids else relationship_guid(profile["ticker_guid"], artifact_guid, relationship),
        "relationship_guids": edge_guids or [relationship_guid(profile["ticker_guid"], artifact_guid, relationship)],
        "tags": sorted(tags),
        "source_type": str(artifact.get("source_type") or "research"),
        "source_id": source_id or None,
        "source_url": artifact.get("source_url") or artifact.get("url"),
        "content_hash": content_hash,
        "title": str(artifact.get("title") or "")[:240],
        "summary": str(artifact.get("summary") or artifact.get("fact") or "")[:1000],
        "as_of": artifact.get("as_of") or artifact.get("observed_at") or _now(),
        "provenance": artifact.get("provenance") or {},
        "authority": AUTHORITY,
        "financial_action": False,
    }


def upgrade_record_guids(record: dict[str, Any]) -> dict[str, Any]:
    """Add the GUID contract to a legacy profile or artifact in memory.

    This function is intentionally non-destructive.  The migration utility can
    persist its output, while readers can safely enrich older rows during a
    rolling deployment.
    """
    row = dict(record or {})
    symbol = normalize_symbol(row.get("symbol"))
    if not symbol:
        return row
    if row.get("schema") == PROFILE_SCHEMA or row.get("ticker_guid") and not row.get("research_artifact_guid"):
        fresh = build_profile(symbol, metadata=row)
        for key, value in fresh.items():
            row.setdefault(key, value)
        row["ticker_guid"] = row.get("ticker_id") or row["ticker_guid"]
        row["ticker_id"] = row["ticker_guid"]
        return row
    profile = build_profile(symbol, metadata=row)
    upgraded = classify_artifact(symbol, {
        **row,
        "source_id": row.get("source_id") or row.get("research_id") or row.get("artifact_id"),
        "content_hash": row.get("content_hash"),
        "relationship": row.get("relationship") or "LINEAR",
        "source_url": row.get("source_url") or row.get("url"),
        "summary": row.get("summary") or row.get("fact"),
    }, profile=profile)
    # Preserve historical values where present and add only missing lineage.
    for key, value in upgraded.items():
        row.setdefault(key, value)
    row["artifact_id"] = row.get("artifact_id") or row.get("research_artifact_guid")
    row["ticker_guid"] = row.get("ticker_guid") or row.get("ticker_id")
    row["ticker_id"] = row["ticker_guid"]
    return row


def append_record(root: Path | str, record: dict[str, Any]) -> str:
    """Append idempotently to the graph projection using a process lock."""
    path = graph_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact_id = str(record.get("artifact_id") or record.get("ticker_id") or "")
    existing = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = upgrade_record_guids(json.loads(line))
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
                row = upgrade_record_guids(json.loads(line))
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
    path = graph_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
                existing.add(row.get("ticker_id") or row.get("ticker_guid"))
            except json.JSONDecodeError:
                continue
    created: list[dict[str, Any]] = []
    for row in rows:
        sym = normalize_symbol(row.get("symbol") or row.get("ticker"))
        if not sym:
            continue
        profile = build_profile(sym, metadata=row)
        if profile["ticker_id"] in existing:
            continue
        created.append(profile)
        existing.add(profile["ticker_id"])
    if created:
        with path.open("a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            for profile in created:
                fh.write(json.dumps(profile, sort_keys=True, default=str) + "\n")
            fh.flush()
            fcntl.flock(fh, fcntl.LOCK_UN)
    return {"profiles_created": len(created), "path": str(path), "authority": AUTHORITY}
