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

