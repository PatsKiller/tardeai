"""Read-only Command Center control-plane projections (R21).

This module deliberately contains no business decisions or mutation methods.  It
projects inexpensive metadata from canonical stores and returns an explicit
evidence/data-quality envelope for UI consumers.
"""
from __future__ import annotations

import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_CLASS = "CURRENT_SMOKE"
READ_ONLY_ADVISORY = "READ_ONLY_ADVISORY"

# One registry map for every collection endpoint, including computed system/stores.
# Fallbacks are fixture/legacy filenames that MUST live in this map — no endpoint
# may open a bare path that is not listed here.
CONTROL_PLANE_DOMAINS: dict[str, dict[str, Any]] = {
    "system": {
        "kind": "computed",
        "store_ids": (),
        "fallbacks": (),
        "wrap_dict": False,
    },
    "agents": {
        "kind": "collection",
        "store_ids": ("cio.agent_traces",),
        "fallbacks": ("data/runtime/agent_registry.json",),
        "wrap_dict": False,
        "extract": "agent_traces",
    },
    "workflows": {
        "kind": "collection",
        "store_ids": ("cio.workflow_lineage",),
        "fallbacks": ("data/cio/cio_workflow_lineage.jsonl", "data/runtime/workflow_traces.json"),
        "wrap_dict": False,
    },
    "research": {
        "kind": "collection",
        "store_ids": ("research.hermes_requests", "research.raw", "research.current"),
        "fallbacks": ("data/runtime/research_attention.json",),
        "wrap_dict": False,
    },
    "stores": {
        "kind": "computed",
        "store_ids": (),
        "fallbacks": (
            "data/runtime/canonical_store_registry.json",
            "data/runtime/store_registry.json",
        ),
        "wrap_dict": False,
        "populated_markers": ("data/cio", "data/portfolios", "data/reconciliation"),
    },
    "identity": {
        "kind": "collection",
        "store_ids": ("identity.registry",),
        "fallbacks": ("data/runtime/identity_registry.json", "data/identity/identity_registry.json"),
        "wrap_dict": False,
    },
    "notifications": {
        "kind": "collection",
        "store_ids": ("notifications.audit", "notifications.outbox"),
        "fallbacks": ("data/runtime/notification_receipts.json",),
        "wrap_dict": False,
    },
    "learning": {
        "kind": "collection",
        "store_ids": ("cio.outcomes", "cio.feedback"),
        "fallbacks": ("data/runtime/learning_evidence.json",),
        "wrap_dict": False,
    },
    "maturity": {
        "kind": "collection",
        "store_ids": ("runtime.maturity",),
        "fallbacks": ("data/runtime/maturity.json",),
        "wrap_dict": True,
    },
    "audit": {
        "kind": "collection",
        "store_ids": ("runtime.audit_claims",),
        "fallbacks": ("data/runtime/audit_capability_claims.json",),
        "wrap_dict": True,
    },
}

ROUTES = tuple(f"/api/v3/control-plane/{name}" for name in CONTROL_PLANE_DOMAINS)


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
            primary = loc.get("primary_path")
            if primary:
                paths.append(Path(primary))
            found = loc.get("path")
            if found:
                paths.append(Path(found))
            for alias in spec.get("aliases") or []:
                paths.append(root / alias)
    except Exception:
        pass
    paths.extend(root / p for p in fallbacks)
    # Preserve the historical PROJECT_ROOT fixture behavior when monkeypatched.
    if root != PROJECT_ROOT:
        paths.extend(PROJECT_ROOT / p for p in fallbacks)
    return tuple(dict.fromkeys(paths))


def _domain_paths(domain: str) -> tuple[Path, ...]:
    spec = CONTROL_PLANE_DOMAINS[domain]
    return _canonical_paths(tuple(spec.get("store_ids") or ()), tuple(spec.get("fallbacks") or ()))


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


def _empty_page(query: dict[str, Any]) -> dict[str, Any]:
    limit, offset = _bounded(query)
    return {"items": [], "pagination": {"limit": limit, "offset": offset, "total": 0}}


def _agents_from_traces(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Unique `agent` field → {agent_id, role, last_wake, runtime_state}."""
    by_agent: dict[str, dict[str, Any]] = {}
    for row in rows:
        agent_id = str(row.get("agent") or row.get("agent_id") or "")
        if not agent_id:
            continue
        last_wake = row.get("ended_at") or row.get("started_at") or row.get("last_wake")
        candidate = {
            "agent_id": agent_id,
            "role": row.get("role"),
            "last_wake": last_wake,
            "runtime_state": row.get("status") or row.get("runtime_state"),
        }
        existing = by_agent.get(agent_id)
        if existing is None or str(last_wake or "") >= str(existing.get("last_wake") or ""):
            by_agent[agent_id] = candidate
    return list(by_agent.values())


def _is_agent_trace_source(path: Path) -> bool:
    return path.name == "agent_run_traces.jsonl" or (
        path.suffix.lower() == ".jsonl" and "agent_run_trace" in path.name
    )


def _project_workflow_collection(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer latest envelope per workflow; ignore raw node/edge rows on the list."""
    if not rows:
        return rows
    types = {str(r.get("record_type") or "") for r in rows}
    if not (types & {"envelope", "node", "edge"}):
        return rows
    envelopes: dict[str, dict[str, Any]] = {}
    leftovers: list[dict[str, Any]] = []
    for row in rows:
        rt = row.get("record_type")
        if rt == "envelope":
            wf = str(row.get("workflow_id") or "")
            if wf:
                envelopes[wf] = row
            continue
        if rt in {"node", "edge"}:
            continue
        leftovers.append(row)
    if envelopes:
        return list(envelopes.values())
    return leftovers


def _extract_rows(value: Any, *, domain: str, path: Path) -> list[dict[str, Any]] | None:
    """Return usable rows, or None to skip this path (do not AVAILABLE-empty-steal)."""
    spec = CONTROL_PLANE_DOMAINS.get(domain) or {}
    wrap_dict = bool(spec.get("wrap_dict"))

    if isinstance(value, list):
        rows = [dict(row) for row in value if isinstance(row, dict)]
        if domain == "agents" and _is_agent_trace_source(path):
            return _agents_from_traces(rows)
        if domain == "workflows":
            return _project_workflow_collection(rows)
        return rows

    if not isinstance(value, dict):
        return None

    for key in ("items", "rows", "data"):
        nested = value.get(key)
        if isinstance(nested, list):
            return [dict(row) for row in nested if isinstance(row, dict)]

    by_research = value.get("by_research_id")
    if isinstance(by_research, dict):
        rows = []
        for key, row in by_research.items():
            if isinstance(row, dict):
                item = dict(row)
                item.setdefault("research_id", key)
                rows.append(item)
            else:
                rows.append({"research_id": str(key), "value": row})
        return rows

    if wrap_dict:
        return [dict(value)]

    # Dict without items/rows/data/by_research_id and not a wrap-dict domain.
    return None


def _select_rows(paths: tuple[Path, ...], *, domain: str) -> tuple[list[dict[str, Any]], str]:
    """First-AVAILABLE over registry-ordered candidates.

    missing → continue
    invalid JSON → try next unless it is the only existing unreadable primary
    usable rows (including empty list) → AVAILABLE
    unusable shape → skip to next path (do not AVAILABLE empty)
    """
    seen_invalid = False
    seen_valid = False
    for path in paths:
        if not path.is_file():
            continue
        if path.suffix.lower() == ".jsonl":
            value, quality = _read_jsonl(path)
        else:
            value, quality = _read_json(path)
        if quality == "INVALID_SCHEMA":
            seen_invalid = True
            continue
        if quality != "AVAILABLE":
            continue
        seen_valid = True
        rows = _extract_rows(value, domain=domain, path=path)
        if rows is None:
            continue
        return rows, "AVAILABLE"
    if seen_invalid and not seen_valid:
        return [], "INVALID_SCHEMA"
    return [], "UNAVAILABLE"


def _rows_from_json(paths: tuple[Path, ...], query: dict[str, Any], *, domain: str) -> tuple[dict[str, Any], str]:
    rows, quality = _select_rows(paths, domain=domain)
    if quality != "AVAILABLE":
        return _empty_page(query), quality
    return _paged(rows, query), quality


def _load_rows(paths: tuple[Path, ...], *, domain: str = "") -> tuple[list[dict[str, Any]], str]:
    """Load bounded projection inputs without replaying or mutating domain state."""
    return _select_rows(paths, domain=domain)


def _collection(domain: str, query: dict[str, Any]) -> tuple[dict[str, Any], str]:
    return _rows_from_json(_domain_paths(domain), query, domain=domain)


def _agent_detail(agent_id: str, query: dict[str, Any]) -> tuple[dict[str, Any], str]:
    rows, quality = _load_rows(_domain_paths("agents"), domain="agents")
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
    "entity_guid", "research_request_id", "research_artifact_id",
    "specialist_artifact_id", "cio_generation_id",
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


def _load_checkpoint_row(checkpoint_id: str) -> dict[str, Any] | None:
    if not checkpoint_id:
        return None
    rows, _quality = _load_rows(
        _canonical_paths(("cio.checkpoints",), ("data/cio/outcome_checkpoints.jsonl",)),
        domain="learning",
    )
    for row in rows:
        if str(row.get("checkpoint_id") or "") == str(checkpoint_id):
            return dict(row)
    return None


def _workflow_detail(workflow_id: str, query: dict[str, Any]) -> tuple[dict[str, Any], str]:
    # domain="" skips list projection so node/edge/envelope records remain.
    rows, quality = _select_rows(_domain_paths("workflows"), domain="")
    grouped: dict[str, dict[str, Any]] = {}
    typed = [r for r in rows if r.get("record_type") in {"node", "edge", "envelope"}]
    if typed:
        for record in rows:
            wf = str(record.get("workflow_id") or "")
            if not wf:
                continue
            trace = grouped.setdefault(
                wf,
                {
                    "workflow_id": wf,
                    "identifiers": {},
                    "nodes": [],
                    "edges": [],
                    "evidence_class": record.get("evidence_class", "OPERATOR_REQUESTED_LIVE"),
                    "source_sha": record.get("source_sha", _sha()),
                },
            )
            rt = record.get("record_type")
            if rt == "envelope":
                for key in (
                    "workflow_id",
                    "research_request_id",
                    "research_artifact_id",
                    "specialist_artifact_id",
                    "cio_generation_id",
                    "notification_id",
                    "checkpoint_id",
                    "event_id",
                    "generation_id",
                ):
                    if record.get(key):
                        trace["identifiers"][key] = str(record[key])
                trace["envelope"] = record
                trace["checkpoint_id"] = record.get("checkpoint_id")
                continue
            if rt == "node":
                trace["nodes"].append(record)
                node_id = record.get("node_id")
                if node_id:
                    trace["identifiers"].setdefault(str(record.get("node_type", "")).lower() + "_id", str(node_id))
            elif rt == "edge":
                trace["edges"].append(record)
        rows = list(grouped.values()) or rows
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
    checkpoint_id = str(identifiers.get("checkpoint_id") or row.get("checkpoint_id") or "")
    checkpoint = _load_checkpoint_row(checkpoint_id) if checkpoint_id else None
    return {
        "workflow_id": canonical_id,
        "resolved_from": workflow_id if canonical_id != workflow_id else None,
        "status": "AVAILABLE",
        "evidence_class": row.get("evidence_class", "HISTORICAL_REPLAY"),
        "source_sha": row.get("source_sha", _sha()),
        "identifiers": identifiers,
        "checkpoint": checkpoint,
        "envelope": row.get("envelope"),
        "nodes": nodes,
        "edges": edges,
        "unresolved_links": missing,
        "pagination": {"nodes": _bounded(query)[0], "edges": _bounded(query)[0]},
    }, dq if quality == "AVAILABLE" else quality


def _invoke_status(fn: Any) -> Any:
    attempts = (
        lambda: fn(),
        lambda: fn(root=_state_root()),
        lambda: fn(_state_root()),
    )
    for attempt in attempts:
        try:
            return attempt()
        except TypeError:
            continue
        except Exception:
            return None
    return None


def _hermes_from_runtime_status() -> dict[str, Any] | None:
    """Lane C classifier when present; None means fail-soft to current health."""
    try:
        hrs = importlib.import_module("scripts.lib.hermes_runtime_status")
    except Exception:
        return None
    snapshot = None
    for name in ("classify", "status", "build", "runtime_status", "snapshot"):
        fn = getattr(hrs, name, None)
        if not callable(fn):
            continue
        snapshot = _invoke_status(fn)
        if snapshot is not None:
            break
    if snapshot is None:
        return None
    if isinstance(snapshot, str):
        return {"mode": "EVENT_DRIVEN_QUEUE", "state": snapshot}
    if isinstance(snapshot, dict):
        hermes = dict(snapshot)
        if "state" not in hermes:
            for key in ("status", "taxonomy", "class", "runtime_state"):
                if hermes.get(key):
                    hermes["state"] = hermes[key]
                    break
        hermes.setdefault("mode", "EVENT_DRIVEN_QUEUE")
        hermes.setdefault("state", "UNKNOWN")
        return hermes
    return None


def _hermes_projection() -> dict[str, Any]:
    pending = 0
    queue: dict[str, Any] = {}
    error = None
    try:
        from scripts.lib.hermes_queue_health import build as build_hermes_health
        queue = build_hermes_health() or {}
        pending = int(queue.get("pending") or 0)
    except Exception as exc:
        error = type(exc).__name__
    try:
        from scripts.lib.hermes_runtime_status import classify
        hermes = classify(
            architecture="oneshot",
            pending=pending,
            worker_running=False,
            error=error,
        )
    except Exception:
        hermes = _hermes_from_runtime_status() or {"mode": "ON_DEMAND", "state": "UNKNOWN"}
    if queue:
        hermes = dict(hermes)
        hermes["queue"] = queue
    return hermes


def _system() -> dict[str, Any]:
    hermes = _hermes_projection()
    return {
        "authority": READ_ONLY_ADVISORY,
        "memory_behavior_influence": 0,
        "runtime": {"source_sha": _sha(), "state": "UNKNOWN", "persistent_state": "UNKNOWN"},
        "services": [], "timers": [], "workers": [{"agent_id": "hermes", "runtime_state": hermes.get("state", "UNKNOWN"), "mode": hermes.get("mode", "EVENT_DRIVEN_QUEUE")}], "queues": [hermes],
        "research": {"state": "UNKNOWN"}, "notifications": {"state": "UNKNOWN"},
    }


def _registered_store_present(root: Path) -> bool:
    """True when a canonical store file exists — not merely a data/cio directory."""
    try:
        from scripts.lib.canonical_store_registry import STORES
    except Exception:
        markers = tuple(CONTROL_PLANE_DOMAINS["stores"].get("populated_markers") or ())
        return any((root / p).exists() for p in markers)
    for store_spec in STORES.values():
        rel = store_spec.get("path")
        if rel and (root / rel).exists():
            return True
        for alias in store_spec.get("aliases") or []:
            if (root / alias).exists():
                return True
    return False


def _stores(query: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    query = query or {}
    spec = CONTROL_PLANE_DOMAINS["stores"]
    candidates = _canonical_paths(tuple(spec.get("store_ids") or ()), tuple(spec.get("fallbacks") or ()))
    data, quality = _rows_from_json(candidates, query, domain="stores")
    if quality == "AVAILABLE":
        return data, quality
    # Registry is code-canonical; expose bounded metadata when a generated
    # registry projection has not yet been emitted, but only for a populated
    # state root. Empty test roots remain explicitly UNAVAILABLE.
    root = _state_root()
    if _registered_store_present(root):
        try:
            from scripts.lib.canonical_store_registry import registry, resolve_store
            rows = []
            for store_id, store_spec in registry()["stores"].items():
                loc = resolve_store(store_id, root=root)
                rows.append({
                    "store_id": store_id,
                    "path": str(loc.get("path") or loc.get("primary_path")),
                    "exists": bool(loc.get("exists")),
                    "schema": store_spec.get("schema"),
                    "writer": store_spec.get("writer"),
                    "ownership_class": store_spec.get("ownership_class"),
                    "status": "AVAILABLE" if loc.get("exists") else "UNAVAILABLE_PRODUCER_NOT_RUN",
                })
            return _paged(rows, query), "AVAILABLE"
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
    prefix = "/api/v3/control-plane/"
    if base == "/api/v3/control-plane" or not base.startswith(prefix):
        return 404, _envelope({"error": "unknown control-plane route"}, quality="NO_RELEVANT_EVENTS")
    rest = base[len(prefix):]
    if not rest:
        return 404, _envelope({"error": "unknown control-plane route"}, quality="NO_RELEVANT_EVENTS")
    parts = rest.split("/")
    domain = parts[0]
    if domain not in CONTROL_PLANE_DOMAINS:
        return 404, _envelope({"error": "unknown control-plane route"}, quality="NO_RELEVANT_EVENTS")
    spec = CONTROL_PLANE_DOMAINS[domain]
    if len(parts) > 2:
        return 404, _envelope({"error": "unknown control-plane route"}, quality="NO_RELEVANT_EVENTS")
    if len(parts) == 2:
        item_id = parts[1]
        if domain == "agents":
            detail, quality = _agent_detail(item_id, query)
            return 200, _envelope(detail, quality=quality)
        if domain == "workflows":
            detail, quality = _workflow_detail(item_id, query)
            return 200, _envelope(detail, quality=quality)
        return 404, _envelope({"error": "unknown control-plane route"}, quality="NO_RELEVANT_EVENTS")
    if spec.get("kind") == "computed" and domain == "system":
        return 200, _envelope(_system())
    if spec.get("kind") == "computed" and domain == "stores":
        data, quality = _stores(query)
        return 200, _envelope(data, quality=quality)
    data, quality = _collection(domain, query)
    return 200, _envelope(data, quality=quality)


def handle_query_string(path: str, *, method: str = "GET", query_string: str = "") -> tuple[int, dict[str, Any]] | None:
    query = {k: (v[0] if len(v) == 1 else v) for k, v in parse_qs(query_string).items()}
    return handle(path, method=method, query=query)
