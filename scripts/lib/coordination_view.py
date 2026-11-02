"""Coordinators view (Command Center v3): read-only projections of the coordination store.

Served by scripts/api_v2.py:

  GET /api/v2/coordination/coordinators  → CoordinationCoordinatorsView@v1
      who coordinates what (registry + heartbeat freshness), assignments, pending checks, waiting-on-operator
  GET /api/v2/coordination/board         → CoordinationBoardView@v1
      BOARD.md as last generated + the ledger tail + pending checks/decisions + inbox counts

The ONLY writer of that store is scripts/coordinator.py (flock + atomic replace). GETs here never create a
directory, never lock, never write; a missing store reads as an empty view with ``registry_present: false``.
A torn ledger tail is skipped, never repaired. AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

try:  # scripts/ on sys.path (api_v2)
    from coordinator import (VENDORS, board_path, coordinator_state, coord_root, inbox_counts, notebook,
                             pending_checks, pending_decisions, read_events, read_registry, registry_path, state_root)
except ImportError:  # imported as scripts.lib.coordination_view
    from scripts.coordinator import (VENDORS, board_path, coordinator_state, coord_root, inbox_counts, notebook,
                                     pending_checks, pending_decisions, read_events, read_registry, registry_path,
                                     state_root)

PREFIX = "/api/v2/coordination"
SCHEMA_VIEW = "CoordinationCoordinatorsView@v1"
SCHEMA_BOARD = "CoordinationBoardView@v1"
SCHEMA_JOIN = "CoordinationJoinCommand@v1"
JOIN_TEMPLATE = "join_command.template"
_ID_RE = re.compile(r"^[a-z0-9-]{1,40}$")
_VENDOR_DEFAULT_ID = {"claude": "claude", "codex": "codex", "cursor": "cursor", "grok": "grok", "other": "other"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _q(query: Any, key: str, default: int) -> int:
    raw = (query or {}).get(key)
    raw = (raw or [None])[0] if isinstance(raw, list) else raw
    try:
        return max(1, min(500, int(str(raw))))
    except (TypeError, ValueError):
        return default


def coordinators_view(root) -> dict[str, Any]:
    reg = read_registry(root)
    events = read_events(root)
    stale = float(reg.get("stale_after_minutes") or 30)
    now = datetime.now(timezone.utc)
    rows = []
    for c in reg["coordinators"]:
        row = dict(c)
        row["state"] = coordinator_state(c, stale, now)
        row["stale_after_minutes"] = stale
        rows.append(row)
    return {
        "schema": SCHEMA_VIEW,
        "generated_at": _utc_now(),
        "store": str(coord_root(root)),
        "registry_present": registry_path(root).exists(),
        "stale_after_minutes": stale,
        "lead": next((c.get("id") for c in rows if str(c.get("role")) == "lead"
                      and str(c.get("state")) != "stood_down"), None),
        "coordinators": rows,
        "territories": reg.get("territories") or {},
        "assignments": reg.get("assignments") or {},
        "pending_checks": pending_checks(events),
        "pending_decisions": pending_decisions(events),
        "inbox": inbox_counts(root),
    }


def board_view(root, limit: int = 50) -> dict[str, Any]:
    events = read_events(root)
    md = None
    try:
        md = board_path(root).read_text(encoding="utf-8")
    except OSError:
        md = None
    return {
        "schema": SCHEMA_BOARD,
        "generated_at": _utc_now(),
        "store": str(coord_root(root)),
        "board_present": md is not None,
        "board_md": md,
        "events": events[-limit:],
        "pending_checks": pending_checks(events),
        "pending_decisions": pending_decisions(events),
        "inbox": inbox_counts(root),
    }


def join_command_view(root, ident: str | None, vendor: str | None) -> dict[str, Any]:
    """The join line for a new session, from the ONE server-side template. Editing the template changes this with no
    deploy. Read-only: a missing template is reported, never created (the operator owns that file)."""
    vend = str(vendor or "").strip().lower()
    if vend not in VENDORS:
        return {"schema": SCHEMA_JOIN, "template_present": False, "valid": False, "line": None,
                "error": f"vendor must be one of {', '.join(VENDORS)}"}
    cid = str(ident or "").strip().lower() or _VENDOR_DEFAULT_ID[vend]
    if not _ID_RE.match(cid):
        return {"schema": SCHEMA_JOIN, "vendor": vend, "id": cid, "template_present": False, "valid": False,
                "line": None, "error": "coordinator id must match [a-z0-9-] (1-40 characters)"}
    path = notebook(root) / JOIN_TEMPLATE
    try:
        text = path.read_text(encoding="utf-8")
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(
            microsecond=0).isoformat().replace("+00:00", "Z")
    except OSError:
        return {"schema": SCHEMA_JOIN, "vendor": vend, "id": cid, "template_present": False,
                "template_path": str(path), "template_modified_at": None, "valid": True, "line": None,
                "error": "join_command.template is missing; the operator creates it"}
    line = text.replace("{id}", cid).replace("{vendor}", vend).rstrip("\n")
    return {"schema": SCHEMA_JOIN, "vendor": vend, "id": cid, "template_present": True,
            "template_path": str(path), "template_modified_at": mtime, "valid": True, "line": line}


def handle(base_path: str, query: Any, body: Any) -> dict[str, Any] | None:
    """Dispatch one read. Returns None when the path is not ours (api_v2 falls through)."""
    path = str(base_path or "").rstrip("/")
    root = state_root()

    def qv(key: str) -> Any:
        raw = (query or {}).get(key)
        return (raw or [None])[0] if isinstance(raw, list) else raw

    if path == f"{PREFIX}/coordinators":
        return coordinators_view(root)
    if path == f"{PREFIX}/board":
        return board_view(root, limit=_q(query, "limit", 50))
    if path == f"{PREFIX}/join-command":
        return join_command_view(root, qv("id"), qv("vendor"))
    return None
