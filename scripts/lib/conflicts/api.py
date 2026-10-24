"""Conflict read projection and server-identity-bound operator decision endpoint."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote

from .ledger import ACTIVE, ConflictLedger, DECISION_SCHEMA, list_records

PREFIX = "/api/v3/conflicts"


def _root():
    from scripts.lib.persistent_state_root import resolve_durable_dir
    return Path(resolve_durable_dir("data/conflicts")).parent.parent


def _first(value, default=None):
    return value[0] if isinstance(value, list) and value else default if value is None else value


def handle(path, method, body=None, query=None, *, ctx=None, root=None, ledger=None,
           write_enabled=False, now=None):
    base = path.split("?", 1)[0].rstrip("/")
    if base != PREFIX and not base.startswith(PREFIX + "/"):
        return None
    method = method.upper()
    if method == "POST":
        from scripts.lib.cio_ask_api import _default_ctx, _operator
        try:
            ctx = ctx or _default_ctx()
            actor = _operator(ctx)
        except Exception:
            return 503, {"error": "AUTH_CONFIG_UNAVAILABLE"}
        if not actor:
            return 403, {"error": "AGENT_CALLER_REFUSED"}
        ok, why = ctx.csrf(method, base)
        if not ok:
            return 403, {"error": "CSRF_REFUSED", "reason": why}
        if not write_enabled:
            return 503, {"error": "CONFLICT_WRITER_NOT_ACTIVATED"}
    elif method != "GET":
        return 405, {"error": "METHOD_NOT_ALLOWED"}
    ledger = ledger or ConflictLedger(root or _root())
    q = {k: _first(v) for k, v in (query or {}).items()}
    if base == PREFIX:
        if method != "GET":
            return 405, {"error": "METHOD_NOT_ALLOWED"}
        try:
            limit = min(max(int(q.get("limit", 100)), 1), 200)
            offset = max(int(q.get("offset", 0)), 0)
        except (ValueError, TypeError):
            return 400, {"error": "INVALID_PAGING"}
        return 200, list_records(ledger.root, subject_kind=q.get("subject_kind"), subject_id=q.get("subject_id"),
                                 state=q.get("state"), kind=q.get("kind"), limit=limit, offset=offset)
    tail = base[len(PREFIX) + 1:]
    deciding = tail.endswith("/decision")
    key = unquote(tail[:-9] if deciding else tail)
    if not key or len(key) > 600 or "/" in key:
        return 400, {"error": "INVALID_KEY"}
    record = ledger.records().get(key)
    if not record:
        return 404, {"error": "NOT_FOUND"}
    if method == "GET" and not deciding:
        return 200, record
    if method != "POST" or not deciding:
        return 405, {"error": "METHOD_NOT_ALLOWED"}
    body = body if isinstance(body, dict) else {}
    if set(body) - {"expected_revision", "chosen_side", "reason", "evidence_refs"}:
        return 400, {"error": "UNKNOWN_OR_ACTOR_FIELD"}
    if type(body.get("expected_revision")) is not int:
        return 400, {"error": "EXPECTED_REVISION_REQUIRED"}
    if body["expected_revision"] != record["revision"]:
        return 409, {"error": "CONFLICT_CHANGED", "revision": record["revision"]}
    if not isinstance(body.get("reason"), str) or not body["reason"].strip() or len(body["reason"]) > 4000:
        return 400, {"error": "REASON_REQUIRED"}
    refs = body.get("evidence_refs")
    if not isinstance(refs, list) or not refs or len(refs) > 30 or any(not isinstance(x, str) or not x.strip() for x in refs):
        return 400, {"error": "EVIDENCE_REQUIRED"}
    if not isinstance(body.get("chosen_side"), str) or not body["chosen_side"].strip():
        return 400, {"error": "CHOSEN_SIDE_REQUIRED"}
    at = now or datetime.now(timezone.utc)
    decision = {"schema": DECISION_SCHEMA, "actor_kind": "operator", "actor": actor,
                "chosen_side": body["chosen_side"], "reason": body["reason"].strip(),
                "evidence_refs": refs, "at": at.isoformat(), "expected_revision": record["revision"]}
    try:
        event = ledger.transition(key, "decided", at=at, expected_revision=record["revision"], decision=decision, apply=True)
    except ValueError as exc:
        return 409, {"error": "DECISION_REFUSED", "reason": str(exc)}
    except RuntimeError:
        return 503, {"error": "DECISION_DURABLE_SINK_PENDING", "key": key}
    return 200, {"ok": True, "event": event, "cleared": False}


def approval_rows(root=None, *, limit=100):
    """W11 bounded read model. Dispositions never resolve or apply a conflict."""
    try:
        collection = list_records(root or _root(), kind="NEEDS_OPERATOR", limit=min(max(limit, 1), 200))
        rows = []
        for record in collection["records"]:
            if record["state"] not in ACTIVE:
                continue
            text = json.dumps({k: record[k] for k in ("key", "subject", "kind", "rule", "summary", "clears_when",
                                                    "sides", "state", "revision")}, ensure_ascii=False, sort_keys=True)
            version = hashlib.sha256(text.encode()).hexdigest()
            rows.append({"id": record["key"], "title": record["summary"], "proposed_by": "conflict engine",
                         "created_at": record["opened_at"], "document": {"text": text, "version": version,
                         "source_sha": version}, "governed_href": "/v3/watch?conflict=" + record["key"]})
        return {"rows": rows, "total": collection["total"], "gap": None}
    except (OSError, ValueError):
        return {"rows": [], "total": None, "gap": {"reason": "conflict ledger unavailable or invalid"}}
