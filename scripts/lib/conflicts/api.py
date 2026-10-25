"""Conflict read projection and server-identity-bound operator decision endpoint."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import quote, unquote

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
    if not key or len(key) > 600 or any(ord(char) < 32 for char in key):
        return 400, {"error": "INVALID_KEY"}
    record = ledger.records().get(key)
    if not record:
        return 404, {"error": "NOT_FOUND"}
    if method == "GET" and not deciding:
        return 200, record
    if method != "POST" or not deciding:
        return 405, {"error": "METHOD_NOT_ALLOWED"}
    body = body if isinstance(body, dict) else {}
    if set(body) - {"expected_revision", "chosen_side", "reason", "evidence_refs", "expires_at"}:
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
                "evidence_refs": refs, "at": at.isoformat(), "expected_revision": record["revision"],
                "expires_at": body.get("expires_at"), "clears_when": record.get("clears_when"),
                "key": key, "subject": record["subject"]}
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
        root = root or _root()
        if not (Path(root) / "data/conflicts/conflict_events.jsonl").exists():
            return {"rows": [], "total": None, "gap": {"reason": "conflict ledger not yet produced"}}
        collection = list_records(root, kind="NEEDS_OPERATOR", active_only=True, limit=min(max(limit, 1), 200))
        rows = []
        for record in collection["records"]:
            text = json.dumps({k: record[k] for k in ("key", "subject", "kind", "rule", "summary", "clears_when",
                                                    "sides", "state", "revision")}, ensure_ascii=False, sort_keys=True)
            version = hashlib.sha256(text.encode()).hexdigest()
            rows.append({"id": record["key"], "title": record["summary"], "proposed_by": "conflict engine",
                         "created_at": record["opened_at"], "document": {"text": text, "version": version,
                         "source_sha": version}, "governed_href": "/watch?conflict=" + quote(record["key"], safe="")})
        gap = {"reason": "more operator conflicts available", "total": collection["total"]} if collection["total"] > len(rows) else None
        return {"rows": rows, "total": collection["total"], "gap": gap}
    except (OSError, ValueError):
        return {"rows": [], "total": None, "gap": {"reason": "conflict ledger unavailable or invalid"}}


def records_section(root=None, *, subject_kind=None, subject_id=None, kind=None):
    """Canonical section for Watch/Home/Ops; includes authoritative lifecycle detail."""
    from .adapters import findings_section
    root = root or _root()
    if not (Path(root) / "data/conflicts/conflict_events.jsonl").exists():
        return findings_section([], gap={"reason": "conflict ledger not yet produced"})
    try:
        collection = list_records(root, subject_kind=subject_kind, subject_id=subject_id, kind=kind, limit=200, active_only=True)
        records = collection["records"]
        findings = [{**r, "schema": "ConflictFinding@v1", "history": r.get("history"),
                     "history_gap": "fetch conflict detail for lifecycle history"} for r in records]
        section = findings_section(findings, gap={"reason": "more conflict records available", "total": collection["total"]}
                                   if collection["total"] > 200 else None)
        return {**section, "source": "conflict_events.jsonl", "as_of": max((r["updated_at"] for r in records), default=None),
                "stale": None}
    except (OSError, ValueError, KeyError):
        return findings_section([], gap={"reason": "conflict ledger unavailable or invalid"})


def data_error_section(root=None):
    return records_section(root, kind="DATA_ERROR")


def sections_for_guids(root, security_guids):
    """One ledger read for Watch rows. No per-row HTTP, source reads or classifier."""
    from .adapters import findings_section
    guids = list(dict.fromkeys(str(g) for g in security_guids if g))
    if len(guids) > 500:
        raise ValueError("conflict GUID batch exceeds 500")
    root = root or _root()
    if not (Path(root) / "data/conflicts/conflict_events.jsonl").exists():
        return {g: findings_section([], gap={"reason": "conflict ledger not yet produced"}) for g in guids}
    try:
        records = ConflictLedger(root).records().values()
        grouped = {g: [] for g in guids}
        for record in records:
            subject = record["subject"]
            if subject["kind"] == "security" and subject["id"] in grouped and record["state"] in ACTIVE:
                grouped[subject["id"]].append({**record["finding"], "state": record["state"],
                    "decision": record["decision"], "revision": record["revision"], "updated_at": record["updated_at"]})
        return {g: {**findings_section(rows), "source": "conflict_events.jsonl",
                    "as_of": max((r["updated_at"] for r in rows), default=None), "stale": None} for g, rows in grouped.items()}
    except (OSError, ValueError, KeyError):
        return {g: findings_section([], gap={"reason": "conflict ledger unavailable or invalid"}) for g in guids}
