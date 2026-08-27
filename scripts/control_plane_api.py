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


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]] | None, str]:
    """Read an append-only projection without failing the whole endpoint on one bad row."""
    try:
        rows: list[dict[str, Any]] = []
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except ValueError:
                return None, "INVALID_SCHEMA"
            if not isinstance(value, dict):
                return None, "INVALID_SCHEMA"
            rows.append(value)
        return rows, "AVAILABLE"
    except FileNotFoundError:
        return None, "UNAVAILABLE"
    except OSError:
        return None, "UNAVAILABLE"


def _state_root() -> Path:
    """Resolve the runtime state root; deployment may override the code directory."""
    for key in ("TRADEAI_STATE_ROOT", "TRADEAI_ROOT", "TRADEAI_PERSISTENT_STATE_ROOT"):
        value = os.environ.get(key)
        if value:
            return Path(value)
    return PROJECT_ROOT


def _canonical_paths(store_ids: tuple[str, ...], fallbacks: tuple[str, ...] = ()) -> tuple[Path, ...]:
    """Resolve logical stores through CanonicalStoreRegistry, retaining test fallbacks."""
    root = _state_root()
    paths: list[Path] = []
    try:
        from scripts.lib.canonical_store_registry import resolve_store
        for store_id in store_ids:
            loc = resolve_store(store_id, root=root)
            spec = loc.get("spec") or {}
            path = loc.get("path") if loc.get("exists") else loc.get("primary_path")
            if path:
                paths.append(Path(path))
            for alias in spec.get("aliases") or []:
                paths.append(root / alias)
    except Exception:
        pass
    paths.extend(root / p for p in fallbacks)
    # Preserve the historical PROJECT_ROOT fixture behavior when monkeypatched.
    if root != PROJECT_ROOT:
        paths.extend(PROJECT_ROOT / p for p in fallbacks)
    return tuple(dict.fromkeys(paths))


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
        value, quality = _read_jsonl(path) if path.suffix.lower() == ".jsonl" else _read_json(path)
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
        if path.suffix.lower() == ".jsonl":
            value, quality = _read_jsonl(path)
        else:
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
    "event": "SOURCE_EVENT", "source_event": "SOURCE_EVENT", "material_event": "SOURCE_EVENT",
    "entity": "ENTITY",
    "materiality": "MATERIALITY", "graph": "GRAPH_IMPACT", "graph_impact": "GRAPH_IMPACT",
    "research_gap": "RESEARCH_GAP", "research": "RESEARCH", "free_first": "FREE_FIRST",
    "specialist": "SPECIALIST_DISPATCH", "specialist_dispatch": "SPECIALIST_DISPATCH",
    "artifact": "SPECIALIST_ARTIFACT", "specialist_artifact": "SPECIALIST_ARTIFACT",
    "council": "COUNCIL", "cio": "CIO_PRODUCT", "cio_product": "CIO_PRODUCT",
    "notification": "NOTIFICATION", "checkpoint": "CHECKPOINT", "outcome": "OUTCOME",
    "lesson": "LESSON", "learning": "LEARNING", "hypothesis": "HYPOTHESIS",
}

WORKFLOW_ID_ALIASES = (
    "workflow_id", "event_id", "decision_id", "generation_id", "artifact_id",
    "notification_id", "checkpoint_id", "outcome_id", "research_id", "council_id",
    "entity_guid",
)

PARTIAL_CERTAINTY = {
    "UNRESOLVED_LINK", "LEGACY_REFERENCE", "MISSING_PARENT", "UNAVAILABLE_STORE", "QUARANTINED_RECORD",
}


def _identifiers(row: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    nested = row.get("identifiers")
    if isinstance(nested, dict):
        for key, value in nested.items():
            if value is not None and str(value):
                out[str(key)] = str(value)
    for key in WORKFLOW_ID_ALIASES:
        value = row.get(key)
        if value is not None and str(value):
            out[key] = str(value)
    return out


def _row_matches_workflow(row: dict[str, Any], workflow_id: str) -> bool:
    ids = _identifiers(row)
    return any(value == workflow_id for value in ids.values())


def _workflow_detail(workflow_id: str, query: dict[str, Any]) -> tuple[dict[str, Any], str]:
    rows, quality = _load_rows(_canonical_paths(("cio.workflow_lineage",), ("data/cio/cio_workflow_lineage.jsonl", "data/runtime/workflow_traces.json")))
    # The durable lineage writer appends one node/edge per record. Normalize
    # those records into the existing trace contract without mutating source data.
    if rows and all(r.get("record_type") in {"node", "edge"} for r in rows):
        grouped: dict[str, dict[str, Any]] = {}
        for record in rows:
            wf = str(record.get("workflow_id") or "")
            if not wf:
                continue
            trace = grouped.setdefault(wf, {"workflow_id": wf, "identifiers": {}, "nodes": [], "edges": [], "evidence_class": record.get("evidence_class", "OPERATOR_REQUESTED_LIVE"), "source_sha": record.get("source_sha", _sha())})
            if record.get("record_type") == "node":
                trace["nodes"].append(record)
                node_id = record.get("node_id")
                if node_id:
                    trace["identifiers"].setdefault(str(record.get("node_type", "")).lower() + "_id", str(node_id))
            else:
                trace["edges"].append(record)
        rows = list(grouped.values())
    matches = [r for r in rows if _row_matches_workflow(r, workflow_id)]
    if not matches:
        status = "UNAVAILABLE" if quality == "UNAVAILABLE" else "NO_RELEVANT_EVENTS"
        return {"workflow_id": workflow_id, "status": status, "nodes": [], "edges": [], "identifiers": {}}, quality
    row = matches[0]
    identifiers = _identifiers(row)
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
        raw_type = str(n.get("node_type") or n.get("kind") or "")
        nodes.append({
            "node_id": nid,
            "node_type": NODE_TYPES.get(raw_type.lower(), n.get("node_type") or n.get("kind") or "UNKNOWN"),
            "entity_refs": n.get("entity_refs", []),
            "timestamp": n.get("timestamp") or n.get("ts"),
            "status": n.get("status", "UNKNOWN"),
            "evidence_class": n.get("evidence_class", row.get("evidence_class", "HISTORICAL_REPLAY")),
            "source_ref": n.get("source_ref"),
            "source_sha": n.get("source_sha", row.get("source_sha", _sha())),
            "data_quality": n.get("data_quality", "AVAILABLE"),
            "summary": n.get("summary"),
            "lineage_status": n.get("lineage_status") or n.get("status"),
        })
    raw_edges = row.get("edges", [])
    edges = []
    for e in raw_edges if isinstance(raw_edges, list) else []:
        if not isinstance(e, dict):
            continue
        frm, to = str(e.get("from") or e.get("source") or ""), str(e.get("to") or e.get("target") or "")
        if not frm or not to:
            continue
        provided = str(e.get("certainty") or "")
        if provided in PARTIAL_CERTAINTY:
            certainty = provided
        elif provided:
            certainty = provided
        else:
            certainty = "SUPPORTED" if frm in seen and to in seen else "UNRESOLVED_LINK"
        if (frm not in seen or to not in seen) and provided not in PARTIAL_CERTAINTY:
            certainty = "UNRESOLVED_LINK"
        edges.append({
            "from": frm, "to": to,
            "relationship": e.get("relationship", "RELATED"),
            "evidence": e.get("evidence"),
            "certainty": certainty,
            "status": e.get("status", "AVAILABLE"),
        })
    missing = [edge for edge in edges if edge["certainty"] in PARTIAL_CERTAINTY or edge["from"] not in seen or edge["to"] not in seen]
    cutoff = query.get("as_of") or query.get("until")
    if cutoff:
        nodes = [n for n in nodes if not n.get("timestamp") or str(n["timestamp"]) <= str(cutoff)]
        allowed = {n["node_id"] for n in nodes}
        edges = [e for e in edges if e["from"] in allowed and e["to"] in allowed]
        missing = [edge for edge in edges if edge["certainty"] in PARTIAL_CERTAINTY or edge["from"] not in allowed or edge["to"] not in allowed]
    dq = "AVAILABLE" if not missing else "PARTIAL"
    row_quality = str(row.get("data_quality") or quality)
    if row_quality in {"STALE", "DEGRADED", "UNAVAILABLE", "INVALID_SCHEMA", "BROKEN"}:
        dq = row_quality
    canonical_id = str(identifiers.get("workflow_id") or row.get("workflow_id") or workflow_id)
    return {
        "workflow_id": canonical_id,
        "resolved_from": workflow_id if canonical_id != workflow_id else None,
        "status": "AVAILABLE",
        "evidence_class": row.get("evidence_class", "HISTORICAL_REPLAY"),
        "source_sha": row.get("source_sha", _sha()),
        "identifiers": identifiers,
        "nodes": nodes,
        "edges": edges,
        "unresolved_links": missing,
        "pagination": {"nodes": _bounded(query)[0], "edges": _bounded(query)[0]},
    }, dq if quality == "AVAILABLE" else quality


def _system() -> dict[str, Any]:
    hermes: dict[str, Any] = {"mode": "EVENT_DRIVEN_QUEUE", "state": "UNKNOWN"}
    try:
        from scripts.lib.hermes_queue_health import build as build_hermes_health
        health = build_hermes_health()
        hermes.update({"state": "AVAILABLE", "queue": health})
    except Exception as exc:
        hermes.update({"state": "UNAVAILABLE", "reason": type(exc).__name__})
    return {
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
        "runtime": {"source_sha": _sha(), "state": "UNKNOWN", "persistent_state": "UNKNOWN"},
        "services": [], "timers": [], "workers": [{"agent_id": "hermes", "runtime_state": hermes["state"], "mode": hermes["mode"]}], "queues": [hermes],
        "research": {"state": "UNKNOWN"}, "notifications": {"state": "UNKNOWN"},
    }


def _stores() -> tuple[dict[str, Any], str]:
    candidates = _canonical_paths((), ("data/runtime/canonical_store_registry.json", "data/runtime/store_registry.json"))
    data, quality = _rows_from_json(candidates, {})
    if quality == "AVAILABLE":
        return data, quality
    # Registry is code-canonical; expose bounded metadata when a generated
    # registry projection has not yet been emitted, but only for a populated
    # state root. Empty test roots remain explicitly UNAVAILABLE.
    root = _state_root()
    if any((root / p).exists() for p in ("data/cio", "data/portfolios", "data/reconciliation")):
        try:
            from scripts.lib.canonical_store_registry import registry, resolve_store
            rows = []
            for store_id, spec in registry()["stores"].items():
                loc = resolve_store(store_id, root=root)
                rows.append({
                    "store_id": store_id,
                    "path": str(loc.get("path") or loc.get("primary_path")),
                    "exists": bool(loc.get("exists")),
                    "schema": spec.get("schema"),
                    "writer": spec.get("writer"),
                    "ownership_class": spec.get("ownership_class"),
                    "status": "AVAILABLE" if loc.get("exists") else "UNAVAILABLE_PRODUCER_NOT_RUN",
                })
            return _paged(rows, {}), "AVAILABLE"
        except Exception:
            pass
    return data, quality


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
        "/api/v3/control-plane/agents": (_canonical_paths((), ("data/runtime/agent_registry.json",)), "agents"),
        "/api/v3/control-plane/workflows": (_canonical_paths(("cio.workflow_lineage", "cio.operator_product.history", "cio.checkpoints"), ("data/cio/cio_workflow_lineage.jsonl", "data/runtime/workflow_traces.json")), "workflows"),
        "/api/v3/control-plane/research": (_canonical_paths(("research.current", "research.raw"), ("data/runtime/research_attention.json",)), "research"),
        "/api/v3/control-plane/identity": (_canonical_paths((), ("data/runtime/identity_registry.json", "data/identity/identity_registry.json")), "identity"),
        "/api/v3/control-plane/notifications": (_canonical_paths(("notifications.outbox",), ("data/runtime/notification_receipts.json",)), "notifications"),
        "/api/v3/control-plane/learning": (_canonical_paths(("cio.outcomes", "cio.feedback"), ("data/runtime/learning_evidence.json",)), "learning"),
        "/api/v3/control-plane/maturity": (_canonical_paths((), ("data/runtime/maturity.json",)), "maturity"),
        "/api/v3/control-plane/audit": (_canonical_paths((), ("data/runtime/audit_capability_claims.json",)), "audit"),
    }
    if base in mapping:
        paths, _ = mapping[base]
        data, quality = _rows_from_json(paths, query)
        return 200, _envelope(data, quality=quality)
    return 404, _envelope({"error": "unknown control-plane route"}, quality="NO_RELEVANT_EVENTS")


def handle_query_string(path: str, *, method: str = "GET", query_string: str = "") -> tuple[int, dict[str, Any]] | None:
    query = {k: (v[0] if len(v) == 1 else v) for k, v in parse_qs(query_string).items()}
    return handle(path, method=method, query=query)
