"""research_request/v1 — the research intake contract (Phase 2 PR-D, 2026-10-08).

A research request is a COORDINATION event on lane ``research-intake``: Trade AI's consumer reads it
from the gateway ledger and enqueues the work through the platform's own research queue under the
platform's own caps. n8n never calls Hermes, never calls an LLM and never sends.

The gateway accepts exactly the event-reference/v0 fields, so the typed request lives in two places:
  * ``subject_key``  — ``type=<request_type>;subject=<topic_id|symbol>;by=<requester>;prio=<P1|P2|P3>``
  * ``artifact_ref`` — ``data/runtime:n8n_research_intake/requests/<idempotency_key>.json`` (the sidecar
    with the free-text reason; a REFERENCE, never bytes, per the gateway contract)

Idempotency: ``rq-`` + sha256(subject|type|UTC day)[:24] — one request per subject and type per day.

Enqueue paths (what the consumer can actually do today):
  * ``topic``  → scripts/research_intelligence_queue.enqueue(topic_id) — the after-close research drain
                 (ri_research_queue; deduped on queued/running; drained under its own cap and LLM wrapper)
  * the six hermes_subject_enhance types (scalp, proposal, position, sector, closed_trade, report) are
    batch gatherers over DB subjects with NO per-request enqueue API; a request naming one is recorded
    as a typed refusal ``no_enqueue_path`` so the gap is visible on the ledger instead of invented.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Mapping

LANE = "research-intake"
SCHEMA = "research_request/v1"
REQUEST_SIDECAR_REL = "n8n_research_intake/requests"          # under <state root>/data/runtime
HERMES_SUBJECT_TYPES = frozenset({"scalp", "proposal", "position", "sector", "closed_trade", "report"})
ENQUEUE_PATHS: dict[str, str] = {"topic": "ri_research_queue"}
REQUEST_TYPES = frozenset(ENQUEUE_PATHS) | HERMES_SUBJECT_TYPES
REQUESTERS = frozenset({"cio-wake", "operator", "maria"})
PRIORITIES = ("P1", "P2", "P3")
MAX_SUBJECT = 80
_SUBJECT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


class RequestError(ValueError):
    """A typed refusal reason (``typed_refusal:<code>``) for a request that must not be enqueued."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    @property
    def reason(self) -> str:
        return f"typed_refusal:{self.code}"


def utc_day(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%d")


def idempotency_key(subject: str, request_type: str, *, now: datetime | None = None) -> str:
    return "rq-" + hashlib.sha256(f"{subject}|{request_type}|{utc_day(now)}".encode("utf-8")).hexdigest()[:24]


def validate(subject: str, request_type: str, requested_by: str, priority: str = "P2") -> None:
    if not isinstance(subject, str) or not _SUBJECT_RE.fullmatch(subject):
        raise RequestError("bad_subject")
    if request_type not in REQUEST_TYPES:
        raise RequestError("unknown_request_type")
    if requested_by not in REQUESTERS:
        raise RequestError("unknown_requester")
    if priority not in PRIORITIES:
        raise RequestError("bad_priority")


def subject_key(subject: str, request_type: str, requested_by: str, priority: str = "P2") -> str:
    validate(subject, request_type, requested_by, priority)
    return f"type={request_type};subject={subject};by={requested_by};prio={priority}"


def parse_subject_key(value: Any) -> dict[str, str]:
    """Inverse of subject_key; raises RequestError on anything that is not a research request."""
    if not isinstance(value, str):
        raise RequestError("malformed_subject_key")
    fields: dict[str, str] = {}
    for part in value.split(";"):
        k, sep, v = part.partition("=")
        if not sep:
            raise RequestError("malformed_subject_key")
        fields[k.strip()] = v.strip()
    try:
        validate(fields["subject"], fields["type"], fields["by"], fields.get("prio", "P2"))
    except KeyError as exc:
        raise RequestError("malformed_subject_key") from exc
    return {"subject": fields["subject"], "request_type": fields["type"], "requested_by": fields["by"],
            "priority": fields.get("prio", "P2")}


def sidecar_rel(key: str) -> str:
    return f"{REQUEST_SIDECAR_REL}/{key}.json"


def build_request(*, subject: str, request_type: str, requested_by: str, reason: str, priority: str = "P2",
                  origin_sha: str, now: datetime | None = None, deadline_hours: float = 24.0) -> tuple[dict[str, Any], dict[str, Any]]:
    """(gateway event, sidecar document). Validates first; the sidecar carries the free text."""
    validate(subject, request_type, requested_by, priority)
    now = now or datetime.now(timezone.utc)
    key = idempotency_key(subject, request_type, now=now)
    from datetime import timedelta
    event = {"event_id": f"evt-{LANE}-{key}", "source_project": "trade-ai", "lane_id": LANE,
             "schema_version": "event-reference/v0", "origin_sha": origin_sha,
             "subject_key": subject_key(subject, request_type, requested_by, priority),
             "source_timestamp": now.isoformat(), "deadline": (now + timedelta(hours=deadline_hours)).isoformat(),
             "artifact_ref": f"data/runtime:{sidecar_rel(key)}", "authority_class": "coordination_read",
             "correlation_id": f"corr-{key}", "idempotency_key": key}
    sidecar = {"schema": SCHEMA, "idempotency_key": key, "subject": subject, "request_type": request_type,
               "requested_by": requested_by, "priority": priority, "reason": str(reason or "")[:500],
               "requested_at": now.isoformat(), "origin_sha": origin_sha,
               "enqueue_path": ENQUEUE_PATHS.get(request_type, "none")}
    return event, sidecar


def enqueue_path(request_type: str) -> str | None:
    """The platform writer a request type maps to, or None when no per-request path exists."""
    return ENQUEUE_PATHS.get(request_type)
