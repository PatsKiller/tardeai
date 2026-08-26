"""Read-only Command Center control-plane projections (R21).

This module deliberately contains no business decisions or mutation methods.  It
projects inexpensive metadata from canonical stores and returns an explicit
evidence/data-quality envelope for UI consumers.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_CLASS = "CURRENT_SMOKE"
ROUTES = (
    "/api/v3/control-plane/system",
    "/api/v3/control-plane/agents",
    "/api/v3/control-plane/workflows",
    "/api/v3/control-plane/research",
    "/api/v3/control-plane/stores",
    "/api/v3/control-plane/identity",
    "/api/v3/control-plane/notifications",
    "/api/v3/control-plane/learning",
    "/api/v3/control-plane/maturity",
    "/api/v3/control-plane/audit",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha() -> str | None:
    for name in ("SOURCE_COMMIT", "BUILD_SHA", "GIT_SHA"):
        value = os.environ.get(name)
        if value:
            return value
    for path in (PROJECT_ROOT / "SOURCE_COMMIT", PROJECT_ROOT / "BUILD_SHA"):
        try:
            value = path.read_text().strip()
            if value:
                return value
        except OSError:
            pass
    return None


def _envelope(data: Any, *, quality: str = "AVAILABLE", evidence: str = EVIDENCE_CLASS) -> dict[str, Any]:
    return {
        "ok": quality not in {"BROKEN", "INVALID_SCHEMA"},
        "as_of": _now(),
        "source_sha": _sha(),
        "freshness": "CURRENT_SMOKE",
        "data_quality": quality,
        "evidence_class": evidence,
        "data": data,
    }


def _read_json(path: Path) -> tuple[Any | None, str]:
    try:
        with path.open() as handle:
            return json.load(handle), "AVAILABLE"
    except FileNotFoundError:
        return None, "UNAVAILABLE"
    except (OSError, ValueError):
        return None, "INVALID_SCHEMA"


def _bounded(query: dict[str, Any]) -> tuple[int, int]:
    def integer(key: str, default: int) -> int:
        value = query.get(key, default)
        if isinstance(value, list):
            value = value[0] if value else default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return max(1, min(200, integer("limit", 50))), max(0, integer("offset", 0))


def _paged(rows: list[dict[str, Any]], query: dict[str, Any]) -> dict[str, Any]:
    limit, offset = _bounded(query)
    return {"items": rows[offset : offset + limit], "pagination": {"limit": limit, "offset": offset, "total": len(rows)}}


def _rows_from_json(paths: tuple[Path, ...], query: dict[str, Any]) -> tuple[dict[str, Any], str]:
    for path in paths:
        value, quality = _read_json(path)
        if quality == "AVAILABLE":
            if isinstance(value, list):
                return _paged([dict(row) for row in value if isinstance(row, dict)], query), quality
            if isinstance(value, dict):
                rows = value.get("items") or value.get("rows") or value.get("data")
                if isinstance(rows, list):
                    return _paged([dict(row) for row in rows if isinstance(row, dict)], query), quality
                return {"items": [], "pagination": {"limit": _bounded(query)[0], "offset": _bounded(query)[1], "total": 0}}, quality
        if quality == "INVALID_SCHEMA":
            return {"items": [], "pagination": {"limit": _bounded(query)[0], "offset": _bounded(query)[1], "total": 0}}, quality
    return {"items": [], "pagination": {"limit": _bounded(query)[0], "offset": _bounded(query)[1], "total": 0}}, "UNAVAILABLE"


def _load_rows(paths: tuple[Path, ...]) -> tuple[list[dict[str, Any]], str]:
    """Load bounded projection inputs without replaying or mutating domain state."""
    for path in paths:
        value, quality = _read_json(path)
        if quality != "AVAILABLE":
            if quality == "INVALID_SCHEMA":
                return [], quality
            continue
        rows = value if isinstance(value, list) else (value.get("items") or value.get("rows") or value.get("data") if isinstance(value, dict) else [])
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, dict)], quality
        return [], "INVALID_SCHEMA"
    return [], "UNAVAILABLE"


def _agent_detail(agent_id: str, query: dict[str, Any]) -> tuple[dict[str, Any], str]:
    rows, quality = _load_rows((PROJECT_ROOT / "data" / "runtime" / "agent_registry.json",))
    match = next((row for row in rows if str(row.get("agent_id") or row.get("id")) == agent_id), None)
    if match is None:
        if quality == "UNAVAILABLE":
            return {"status": "UNAVAILABLE_BACKEND", "agent_id": agent_id}, quality
        return {"status": "UNKNOWN_AGENT", "agent_id": agent_id}, "NO_RELEVANT_EVENTS"
    detail = {
        "agent_id": agent_id,
        "role": match.get("role"),
        "runtime_state": match.get("runtime_state", "REGISTERED_NO_RUNTIME"),
        "trigger_classes": match.get("trigger_classes", []),
        "last_wake": match.get("last_wake"), "wake_reason": match.get("wake_reason"),
        "current_task": match.get("current_task"), "entity_refs": match.get("entity_refs", []),
        "queue_depth": match.get("queue_depth"), "last_success": match.get("last_success"),
        "last_failure": match.get("last_failure"), "last_artifact": match.get("last_artifact"),
        "recent_artifacts": _paged([a for a in match.get("recent_artifacts", []) if isinstance(a, dict)], query),
        "research_route": match.get("research_route"), "model_route": match.get("model_route"),
        "process_route": match.get("process_route"), "latency": match.get("latency"),
        "cost": match.get("cost"), "next_eligible_wake": match.get("next_eligible_wake"),
        "evidence_class": match.get("evidence_class", "CURRENT_SMOKE"),
        "source_sha": match.get("source_sha", _sha()), "as_of": match.get("as_of", _now()),
        "data_quality": match.get("data_quality", "AVAILABLE"),
    }
    return detail, quality


NODE_TYPES = {
    "event": "SOURCE_EVENT", "source_event": "SOURCE_EVENT", "entity": "ENTITY",
    "materiality": "MATERIALITY", "graph_impact": "GRAPH_IMPACT", "research_gap": "RESEARCH_GAP",
    "research": "RESEARCH", "specialist": "SPECIALIST_DISPATCH", "specialist_dispatch": "SPECIALIST_DISPATCH",
    "artifact": "SPECIALIST_ARTIFACT", "specialist_artifact": "SPECIALIST_ARTIFACT", "council": "COUNCIL",
    "cio": "CIO_PRODUCT", "cio_product": "CIO_PRODUCT", "notification": "NOTIFICATION",
    "checkpoint": "CHECKPOINT", "outcome": "OUTCOME", "lesson": "LESSON", "hypothesis": "HYPOTHESIS",
}


def _workflow_detail(workflow_id: str, query: dict[str, Any]) -> tuple[dict[str, Any], str]:
    rows, quality = _load_rows((PROJECT_ROOT / "data" / "runtime" / "workflow_traces.json",))
    aliases = {"workflow_id", "event_id", "decision_id", "generation_id", "artifact_id", "notification_id", "checkpoint_id", "outcome_id"}
    matches = [r for r in rows if any(str(r.get(k)) == workflow_id for k in aliases)]
    if not matches:
        return {"workflow_id": workflow_id, "status": "UNAVAILABLE" if quality == "UNAVAILABLE" else "NO_RELEVANT_EVENTS", "nodes": [], "edges": []}, quality
    row = matches[0]
    raw_nodes = row.get("nodes", [])
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, n in enumerate(raw_nodes if isinstance(raw_nodes, list) else []):
        if not isinstance(n, dict):
            continue
        nid = str(n.get("node_id") or n.get("id") or f"{workflow_id}:node:{idx}")
        if nid in seen:
            continue
        seen.add(nid)
        nodes.append({"node_id": nid, "node_type": NODE_TYPES.get(str(n.get("node_type", "")).lower(), n.get("node_type", "UNKNOWN")),
                      "entity_refs": n.get("entity_refs", []), "timestamp": n.get("timestamp") or n.get("ts"),
                      "status": n.get("status", "UNKNOWN"), "evidence_class": n.get("evidence_class", "HISTORICAL_REPLAY"),
                      "source_ref": n.get("source_ref"), "source_sha": n.get("source_sha", _sha()),
                      "data_quality": n.get("data_quality", "AVAILABLE"), "summary": n.get("summary")})
    raw_edges = row.get("edges", [])
    edges = []
    for e in raw_edges if isinstance(raw_edges, list) else []:
        if not isinstance(e, dict):
            continue
        frm, to = str(e.get("from") or e.get("source") or ""), str(e.get("to") or e.get("target") or "")
        if not frm or not to:
            continue
        certainty = e.get("certainty", "SUPPORTED" if frm in seen and to in seen else "UNRESOLVED_LINK")
        edges.append({"from": frm, "to": to, "relationship": e.get("relationship", "RELATED"), "evidence": e.get("evidence"), "certainty": certainty, "status": e.get("status", "AVAILABLE")})
    missing = []
    for edge in edges:
        if edge["from"] not in seen or edge["to"] not in seen:
            edge["certainty"] = "UNRESOLVED_LINK"
            missing.append(edge)
    cutoff = query.get("as_of") or query.get("until")
    if cutoff:
        nodes = [n for n in nodes if not n.get("timestamp") or str(n["timestamp"]) <= str(cutoff)]
        allowed = {n["node_id"] for n in nodes}
        edges = [e for e in edges if e["from"] in allowed and e["to"] in allowed]
    dq = "AVAILABLE" if not missing else "PARTIAL"
    canonical_id = str(row.get("workflow_id") or workflow_id)
    return {"workflow_id": canonical_id, "resolved_from": workflow_id if canonical_id != workflow_id else None,
            "status": "AVAILABLE", "nodes": nodes, "edges": edges,
            "unresolved_links": missing, "pagination": {"nodes": _bounded(query)[0], "edges": _bounded(query)[0]}}, dq if quality == "AVAILABLE" else quality


def _system() -> dict[str, Any]:
    return {
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
        "runtime": {"source_sha": _sha(), "state": "UNKNOWN", "persistent_state": "UNKNOWN"},
        "services": [], "timers": [], "workers": [], "queues": [],
        "research": {"state": "UNKNOWN"}, "notifications": {"state": "UNKNOWN"},
    }


def _stores() -> tuple[dict[str, Any], str]:
    candidates = (PROJECT_ROOT / "data" / "runtime" / "canonical_store_registry.json", PROJECT_ROOT / "data" / "runtime" / "store_registry.json")
    return _rows_from_json(candidates, {})


def handle(path: str, *, method: str = "GET", query: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]] | None:
    """Dispatch one control-plane request; returns ``None`` for non-R21 paths."""
    if not path.startswith("/api/v3/control-plane"):
        return None
    if method.upper() != "GET":
        return 405, _envelope({"error": "control-plane is read-only"}, quality="UNAVAILABLE")
    query = query or {}
    base = path.rstrip("/")
    if base == "/api/v3/control-plane/system":
        return 200, _envelope(_system())
    if base == "/api/v3/control-plane/stores":
        data, quality = _stores(); return 200, _envelope(data, quality=quality)
    if base.startswith("/api/v3/control-plane/agents/"):
        detail, quality = _agent_detail(base.rsplit("/", 1)[-1], query)
        return 200, _envelope(detail, quality=quality)
    if base.startswith("/api/v3/control-plane/workflows/"):
        detail, quality = _workflow_detail(base.rsplit("/", 1)[-1], query)
        return 200, _envelope(detail, quality=quality)
    mapping = {
        "/api/v3/control-plane/agents": ((PROJECT_ROOT / "data" / "runtime" / "agent_registry.json",), "agents"),
        "/api/v3/control-plane/workflows": ((PROJECT_ROOT / "data" / "runtime" / "workflow_traces.json",), "workflows"),
        "/api/v3/control-plane/research": ((PROJECT_ROOT / "data" / "runtime" / "research_attention.json",), "research"),
        "/api/v3/control-plane/identity": ((PROJECT_ROOT / "data" / "runtime" / "identity_registry.json",), "identity"),
        "/api/v3/control-plane/notifications": ((PROJECT_ROOT / "data" / "runtime" / "notification_receipts.json",), "notifications"),
        "/api/v3/control-plane/learning": ((PROJECT_ROOT / "data" / "runtime" / "learning_evidence.json",), "learning"),
        "/api/v3/control-plane/maturity": ((PROJECT_ROOT / "data" / "runtime" / "maturity.json",), "maturity"),
        "/api/v3/control-plane/audit": ((PROJECT_ROOT / "data" / "runtime" / "audit_capability_claims.json",), "audit"),
    }
    if base in mapping:
        paths, _ = mapping[base]
        data, quality = _rows_from_json(paths, query)
        return 200, _envelope(data, quality=quality)
    return 404, _envelope({"error": "unknown control-plane route"}, quality="NO_RELEVANT_EVENTS")


def handle_query_string(path: str, *, method: str = "GET", query_string: str = "") -> tuple[int, dict[str, Any]] | None:
    query = {k: (v[0] if len(v) == 1 else v) for k, v in parse_qs(query_string).items()}
    return handle(path, method=method, query=query)
