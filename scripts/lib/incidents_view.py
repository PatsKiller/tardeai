"""Ops → Incidents API (Command Center v3), served by scripts/api_v2.py.

  GET  /api/v2/ops/incidents                 → IncidentIndex@v1 projection (+ watcher/supervisor receipts' as_of)
  GET  /api/v2/ops/incidents/<id>            → one IncidentRecord@v1 + its raw events
  POST /api/v2/ops/incidents/<id>/ack        → operator acknowledge        {request_id, comment?}
  POST /api/v2/ops/incidents/<id>/close      → operator close as won't-fix {request_id, comment}

The two POSTs are the page's only writes. Each is an operator decision first (scripts/lib/operator_approvals.py
``DecisionLedger.incident_decision``: tailnet operator on serve_proxy, same-origin CSRF, the store-approval gate) and
only then an incident ledger row citing the decision's hash. An agent or service caller is refused
(AGENT_CALLER_REFUSED). GETs never create the directory and never write. AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from urllib.parse import unquote

try:
    from scripts.lib import incidents as L
except ImportError:  # api_v2 puts scripts/ on sys.path
    from lib import incidents as L  # type: ignore[no-redef]

PREFIX = "/api/v2/ops/incidents"
SCHEMA = "OpsIncidentsView@v1"


def _receipt_as_of(d: Path, name: str) -> Optional[str]:
    try:
        return json.loads((d / name).read_text(encoding="utf-8")).get("as_of")
    except (OSError, ValueError, AttributeError):
        return None


def payload(d: Path, *, now=None) -> dict:
    exists = (d / "events.jsonl").exists()
    idx = L.load_index(d) if exists else L.build_index([], now)
    return {"schema": SCHEMA, "ledger_present": exists, "generated_at": idx.get("generated_at"),
            "summary": idx.get("summary"), "incidents": idx.get("incidents") or [],
            "watchers_as_of": _receipt_as_of(d, "watchers_last.json"),
            "supervisor_as_of": _receipt_as_of(d, "supervisor_last.json")}


def detail(d: Path, iid: str) -> Optional[dict]:
    events = [e for e in L.read_events(d) if e.get("incident_id") == iid]
    rec = L.fold(events).get(iid)
    if not rec:
        return None
    return {"incident": rec, "events": events}


def _default_operator_ctx():
    """(operator_actor_or_None, csrf_fn, ledger) from the live server's auth context."""
    try:
        from scripts.lib import operator_approvals_api as api
    except ImportError:
        from lib import operator_approvals_api as api  # type: ignore[no-redef]
    ctx = api.default_ctx()
    return api._operator(ctx), ctx.csrf, ctx.ledger


def handle(path: str, method: str, query: Mapping[str, Any] | None = None, body: Any = None, *,
           d: Optional[Path] = None,
           operator_ctx: Callable[[], tuple] = _default_operator_ctx) -> Optional[tuple[int, dict]]:
    base = path.split("?", 1)[0].rstrip("/")
    if not (base == PREFIX or base.startswith(PREFIX + "/")):
        return None
    d = d or L.incidents_dir()
    sub = base[len(PREFIX):].strip("/")
    parts = [unquote(p) for p in sub.split("/")] if sub else []
    if method == "GET":
        if not parts:
            return 200, {"ok": True, "data": payload(d)}
        if len(parts) == 1:
            if not L.valid_id(parts[0]):
                return 400, {"ok": False, "error": "INVALID_INCIDENT_ID"}
            got = detail(d, parts[0])
            return (200, {"ok": True, "data": got}) if got else (404, {"ok": False, "error": "NOT_FOUND"})
        return 404, {"ok": False, "error": "NOT_FOUND"}
    if method != "POST":
        return 405, {"ok": False, "error": "METHOD_NOT_ALLOWED"}
    if len(parts) != 2 or parts[1] not in ("ack", "close") or not L.valid_id(parts[0]):
        return 404, {"ok": False, "error": "NOT_FOUND"}
    iid, verb = parts
    try:
        actor, csrf, ledger = operator_ctx()
    except Exception as exc:  # noqa: BLE001
        return 503, {"ok": False, "error": "SOURCE_UNAVAILABLE", "detail": type(exc).__name__}
    if not actor:
        return 403, {"ok": False, "error": "AGENT_CALLER_REFUSED"}
    ok, _why = csrf("POST", base)
    if not ok:
        return 403, {"ok": False, "error": "CSRF_REFUSED"}
    if not isinstance(body, dict):
        return 400, {"ok": False, "error": "OBJECT_BODY_REQUIRED"}
    rec = L.load_records(d).get(iid)
    if not rec:
        return 404, {"ok": False, "error": "NOT_FOUND"}
    if verb == "close" and rec["status"] in L.TERMINAL:
        return 409, {"ok": False, "error": "ALREADY_CLOSED"}
    comment = str(body.get("comment") or "")
    try:
        row = ledger.incident_decision(actor, {"decision": "ACKNOWLEDGE" if verb == "ack" else "CLOSE_WONT_FIX",
                                               "incident_id": iid, "request_id": body.get("request_id"),
                                               "comment": comment})
    except Exception as exc:  # noqa: BLE001 — Refused carries code/status
        return int(getattr(exc, "status", 503) or 503), {"ok": False, "error": getattr(exc, "code", type(exc).__name__)}
    ref = f"operator_decisions:{row.get('hash_self')}"
    try:
        if verb == "ack":
            out = L.operator_ack(iid, decision_ref=ref, comment=comment, actor=actor, d=d)
        else:
            out = L.operator_close(iid, decision_ref=ref, comment=comment, actor=actor, d=d)
    except L.LedgerError as exc:
        return 409, {"ok": False, "error": "LEDGER_REFUSED", "detail": str(exc)[:200]}
    return 200, {"ok": True, "data": {"incident": out, "decision": {"at": row.get("at"), "ref": ref}}}
