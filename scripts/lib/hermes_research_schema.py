"""Hermes research request/result schema helpers (hermes_request@v1 / hermes_result@v1).

READ_ONLY_ADVISORY — lint rejects execution language.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


SCHEMA_REQUEST = "hermes_request@v1"
SCHEMA_RESULT = "hermes_result@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

LOOP_STATES = frozenset({
    "idle", "queued", "running", "started", "completed", "failed", "reused", "superseded", "cancelled",
})
IN_FLIGHT = frozenset({"queued", "running", "started"})
TERMINAL = frozenset({"completed", "failed", "cancelled", "superseded"})

PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "critical": 3}

# Adjacency was rigid: "place order" matched but "place an order" did not, and
# "execute trade" matched but "execute the buy" did not. An article was enough to
# pass the gate — the same failure shape as the memory jailbreak scan fixed in
# #631, where "ignore all previous instructions" slipped past a one-qualifier
# pattern.
#
# `research_quality.critique` catches "place an order" and this lint catches
# "buy now", so between them each covered the other's blind spot by accident.
# "execute the buy" was covered by neither.
#
# Only the article gap is closed here. Ambiguous advisory verbs ("trim the
# position", "sell half") are deliberately NOT added: they appear in legitimate
# analysis, and rejecting them would silently shrink research coverage. That is
# an operator policy call, recorded in the Wave 2C 251-320 note.
_ART = r"(?:\s+(?:a|an|the|this|that|your|its))?"

EXEC_LINT = re.compile(
    r"\b("
    rf"(?:buy|sell)\s+now|place{_ART}\s+(?:stop|order)|submit{_ART}\s+order|"
    rf"execute{_ART}\s+(?:trade|order|buy|sell)|"
    r"force fill|enter long|enter short|market order|limit order"
    r")\b",
    re.I,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


AS_OF_MAX_AGE_HOURS = 14 * 24
AS_OF_MAX_FUTURE_HOURS = 24


def parse_as_of(value: Any) -> Optional[datetime]:
    """Parse model/catalyst as_of. Date-only is treated as UTC midnight."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.fromisoformat(s[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def coerce_as_of(value: Any, *, now: Optional[datetime] = None) -> str:
    """Keep as_of only if it is a real, near-now timestamp.

    Model bodies have returned '2025-07-11' (year-old hallucination). That must
    not become completed_ts. Worker-now is the honest production time when the
    supplied stamp is unusable.
    """
    now = now or datetime.now(timezone.utc)
    dt = parse_as_of(value)
    if dt is None:
        return now.isoformat()
    delta_s = (dt - now).total_seconds()
    if delta_s > AS_OF_MAX_FUTURE_HOURS * 3600:
        return now.isoformat()
    if delta_s < -AS_OF_MAX_AGE_HOURS * 3600:
        return now.isoformat()
    return dt.isoformat()


def compact_catalyst(request: dict[str, Any]) -> dict[str, Any]:
    """Small catalyst payload for the model + source grounding. No invention."""
    cat = request.get("catalyst") or request.get("catalyst_pack") or {}
    if not isinstance(cat, dict):
        cat = {}
    events: list[dict[str, Any]] = []
    raw_events = cat.get("events") or []
    if isinstance(raw_events, list):
        for ev in raw_events[:8]:
            if not isinstance(ev, dict):
                continue
            events.append({
                "event_id": ev.get("event_id"),
                "title": str(ev.get("title") or "")[:160],
                "kind": ev.get("kind"),
                "severity": ev.get("severity"),
                "session_date": ev.get("session_date") or ev.get("event_ts"),
                "source": ev.get("source"),
                "confirmed": ev.get("confirmed"),
                "symbol": ev.get("symbol"),
            })
    ids = [
        str(x) for x in (
            request.get("known_catalyst_event_ids")
            or cat.get("known_catalyst_event_ids")
            or []
        )
        if x
    ][:12]
    return {
        "as_of": cat.get("as_of"),
        "symbol": cat.get("symbol") or request.get("symbol"),
        "open_count": cat.get("open_count"),
        "quality_state": cat.get("quality_state") or cat.get("quality"),
        "events": events,
        "event_ids": ids,
    }


def _add_source(out: list[str], seen: set[str], value: Any) -> None:
    if isinstance(value, dict):
        value = (
            value.get("url")
            or value.get("event_id")
            or value.get("id")
            or value.get("title")
            or value.get("source")
        )
    s = str(value or "").strip()
    if not s or s in seen:
        return
    seen.add(s)
    out.append(s[:240])


def collect_sources(
    body: dict[str, Any],
    request: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Ground sources from model citations + request catalyst events. No fake URLs."""
    out: list[str] = []
    seen: set[str] = set()
    for key in ("sources", "source_urls", "evidence_links"):
        raw = body.get(key) or []
        if isinstance(raw, str):
            raw = [raw]
        if isinstance(raw, list):
            for item in raw:
                _add_source(out, seen, item)
    for a in body.get("answers") or []:
        if not isinstance(a, dict):
            continue
        for c in a.get("citations") or []:
            _add_source(out, seen, c)
    cat = compact_catalyst(request or {})
    for ev in cat.get("events") or []:
        _add_source(out, seen, ev.get("event_id") or ev.get("title"))
    for eid in cat.get("event_ids") or []:
        _add_source(out, seen, eid)
    return out[:20]


def synthesize_summary(
    body: dict[str, Any],
    request: Optional[dict[str, Any]] = None,
) -> str:
    """Top-level summary from existing answer/finding text. Does not invent claims."""
    existing = body.get("summary")
    if isinstance(existing, str) and existing.strip() and existing.strip().lower() not in {"n/a", "todo"}:
        return existing.strip()[:800]
    parts: list[str] = []
    symbol = ""
    if request:
        symbol = str(
            request.get("symbol")
            or (request.get("subject") or {}).get("symbol")
            or ""
        ).upper()
    if not symbol:
        symbol = str(body.get("symbol") or "").upper()
    for a in body.get("answers") or []:
        if not isinstance(a, dict):
            continue
        text = str(a.get("summary") or a.get("detail") or "").strip()
        if text:
            parts.append(text)
    for f in body.get("findings") or []:
        if isinstance(f, dict):
            text = str(f.get("text") or f.get("summary") or "").strip()
        else:
            text = str(f).strip()
        if text:
            parts.append(text)
    notes = ""
    desk = body.get("desk_implications")
    if isinstance(desk, dict):
        notes = str(desk.get("notes") or "").strip()
    if notes:
        parts.append(notes)
    if not parts:
        return ""
    text = " ".join(parts)
    if symbol and symbol.lower() not in text.lower():
        text = f"{symbol}: {text}"
    return text[:800]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def lint_execution_language(blob: Any) -> Optional[str]:
    """Return match text if forbidden execution language present, else None.

    Delegates to `execution_language.find_imperative` — the single definition
    shared with `research_quality.critique`. Two gates with separate word lists
    is exactly how `execute the buy` passed both; EXEC_LINT is retained below
    only as a fallback if that module cannot be imported.

    This is the INGEST gate: it governs new research artifacts, where the
    tighter rule applies immediately.
    """
    try:
        from scripts.lib.execution_language import find_imperative
    except Exception:  # pragma: no cover - fallback only
        try:
            import json
            text = blob if isinstance(blob, str) else json.dumps(blob, default=str)
        except Exception:
            text = str(blob)
        m = EXEC_LINT.search(text)
        return m.group(0) if m else None
    return find_imperative(blob)


def validate_request(req: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(req, dict):
        return False, "not_a_dict"
    if not str(req.get("plan_id") or "").strip():
        return False, "plan_id_required"
    if not str(req.get("research_id") or "").strip():
        return False, "research_id_required"
    qs = req.get("questions") or []
    if not qs:
        return False, "questions_required"
    auth = str(req.get("authority") or AUTHORITY)
    if auth != AUTHORITY:
        return False, "authority_must_be_read_only_advisory"
    hit = lint_execution_language(req.get("questions"))
    if hit:
        return False, f"execution_language:{hit}"
    return True, "ok"


def validate_result(result: dict[str, Any], request: Optional[dict[str, Any]] = None) -> tuple[bool, str]:
    if not isinstance(result, dict):
        return False, "not_a_dict"
    if not result.get("result_id"):
        return False, "result_id_required"
    if not result.get("research_id"):
        return False, "research_id_required"
    if not (result.get("as_of") or result.get("completed_ts")):
        return False, "as_of_required"
    hit = lint_execution_language(result)
    if hit:
        return False, f"execution_language:{hit}"
    answers = result.get("answers") or []
    findings = result.get("findings") or []
    if not answers and not findings and not result.get("summary"):
        return False, "empty_result"
    # confidence range
    for a in answers:
        if not isinstance(a, dict):
            continue
        c = a.get("confidence")
        if c is not None:
            try:
                cf = float(c)
                if cf < 0 or cf > 1:
                    return False, "confidence_out_of_range"
            except (TypeError, ValueError):
                return False, "confidence_invalid"
    if request:
        req_ids = {
            str(q.get("question_id") or q.get("id"))
            for q in (request.get("questions") or [])
            if isinstance(q, dict)
        }
        req_ids.discard("None")
        if req_ids:
            for a in answers:
                if not isinstance(a, dict):
                    continue
                qid = str(a.get("question_id") or a.get("id") or "")
                if qid and qid not in req_ids:
                    # soft: allow extra, do not fail
                    pass
    return True, "ok"


def stamp_result(
    request: dict[str, Any],
    body: dict[str, Any],
    *,
    worker_id: str,
    t0_ms: Optional[int] = None,
    result_id: Optional[str] = None,
) -> dict[str, Any]:
    """Stamp identity/status onto backend body → hermes_result@v1."""
    completed_ts = _now()
    raw_as_of = body.get("as_of") or body.get("completed_ts")
    as_of = coerce_as_of(raw_as_of)
    sources = collect_sources(body, request)
    summary = synthesize_summary(body, request)
    evidence_links = list(body.get("evidence_links") or sources)[:20]
    model_as_of = str(raw_as_of or "").strip()
    parsed_model_as_of = parse_as_of(raw_as_of)
    as_of_coerced = parsed_model_as_of is None or as_of != parsed_model_as_of.isoformat()
    result = {
        "schema_version": SCHEMA_RESULT,
        "result_id": result_id or new_id("rr"),
        "research_id": request.get("research_id"),
        "plan_id": request.get("plan_id"),
        "completed_ts": completed_ts,
        "as_of": as_of,
        "status": "completed",
        "thesis_version_at_request": request.get("thesis_version"),
        "symbol": request.get("symbol") or (request.get("subject") or {}).get("symbol"),
        "fingerprint": request.get("fingerprint"),
        "answers": list(body.get("answers") or [])[:12],
        "findings": list(body.get("findings") or [])[:12],
        "desk_implications": body.get("desk_implications") or {},
        "summary": summary,
        "sources": sources,
        "source_urls": list(body.get("source_urls") or sources)[:20],
        "evidence_links": evidence_links,
        "limitations": list(body.get("limitations") or [])[:8],
        "authority": AUTHORITY,
        "provenance": {
            **(body.get("provenance") or {}),
            "agent": "hermes",
            "worker_id": worker_id,
            "latency_ms": t0_ms,
            "error": None,
            "model_as_of": model_as_of or None,
            "as_of_coerced": as_of_coerced,
        },
        "catalyst_event_ids": list(
            request.get("known_catalyst_event_ids")
            or compact_catalyst(request).get("event_ids")
            or []
        )[:40],
    }
    # Preserve the governed ResearchThesisDelta inputs produced by the backend.
    # Identity/status/provenance remain worker-stamped; raw chain-of-thought is
    # neither requested nor copied.
    for key in (
        "recommendation", "dissent", "confidence", "classification",
        "evidence_as_of", "evidence", "contradictory_evidence",
        "reason_summary", "what_changed", "what_did_not_change",
        "research_gaps_remaining", "invalidation_triggered", "source_quality",
        "freshness", "source_refs", "thesis_stance", "provider", "model",
    ):
        if body.get(key) is not None:
            result[key] = body.get(key)
    return result


def evidence_domain_from_result(
    result: dict[str, Any],
    *,
    open_research_ids: Optional[list[str]] = None,
    reused: bool = False,
) -> dict[str, Any]:
    """Build hermes_research evidence domain for plan attach."""
    findings = result.get("findings") or []
    # normalize findings to list of strings for summary
    findings_summary: list[str] = []
    for f in findings[:8]:
        if isinstance(f, str):
            findings_summary.append(f[:240])
        elif isinstance(f, dict):
            findings_summary.append(str(f.get("text") or f.get("summary") or f)[:240])
    confs = []
    for a in result.get("answers") or []:
        if isinstance(a, dict) and a.get("confidence") is not None:
            try:
                confs.append(float(a["confidence"]))
            except (TypeError, ValueError):
                pass
    desk = result.get("desk_implications") or {}
    return {
        "domain": "hermes_research",
        "as_of": result.get("as_of") or result.get("completed_ts"),
        "research_id": result.get("research_id"),
        "result_id": result.get("result_id"),
        "status": result.get("status") or "completed",
        "findings_summary": findings_summary,
        "findings": findings[:12],
        "summary": result.get("summary"),
        "answers": result.get("answers") or [],
        "desk_implications": desk,
        "desk_bias": desk.get("suggestion_bias") or desk.get("desk_bias"),
        "confidence_mean": (sum(confs) / len(confs)) if confs else None,
        "open_gaps": list(desk.get("open_gaps") or result.get("limitations") or [])[:6],
        "watch_triggers": list(desk.get("watch_triggers") or [])[:6],
        "reused": bool(reused),
        "quality_state": "OK",
        "fields_used": ["findings_summary", "summary", "answers", "desk_implications"],
        "open_research_ids": list(open_research_ids or []),
        "authority": AUTHORITY,
    }


def evidence_stub_in_flight(
    research_id: str,
    *,
    plan_id: str = "",
    status: str = "queued",
) -> dict[str, Any]:
    return {
        "domain": "hermes_research",
        "as_of": _now()[:19],
        "research_id": research_id,
        "plan_id": plan_id,
        "status": status,
        "quality_state": "PARTIAL",
        "findings_summary": [],
        "open_research_ids": [research_id],
        "gap_reason": f"research_{status}",
        "fields_used": [],
        "authority": AUTHORITY,
    }
