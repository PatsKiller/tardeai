"""Bounded review progress over the shared CIO record and existing priority queue.

Read-only: a publication in the acquisition ledger is historical evidence, not
proof that the canonical CIO record accepted that particular request.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import logging
import re

LOG = logging.getLogger(__name__)
MAX_SYMBOLS = 30


def _time(value):
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return at.astimezone(timezone.utc) if at.tzinfo else None
    except (ValueError, TypeError):
        return None


def presentation_state(state, truth, *, now=None):
    """Preserve the queue's state; distinguish a historical answer from readback."""
    out = deepcopy(state)
    now = now or datetime.now(timezone.utc)
    last = out.get("last_attempt") or {}
    publication = out.get("last_publication") or (last if last.get("status") == "PUBLISHED" else {})
    proof = publication.get("publication") or {}
    at = _time(proof.get("published_at") or publication.get("at"))
    out["updated_at"] = last.get("at") or out.get("queued_at")
    if out.get("status") != "answered":
        if out.get("status") == "queued" and out.get("identity_status") and out["identity_status"] != "CONFIRMED":
            out.update(status="blocked", label="Identity confirmation needed — no model call will run")
        return out
    review = truth.get("review") or {}
    linked = bool(
        not truth.get("gap")
        and out.get("request_id")
        and review.get("request_id") == out["request_id"]
        and review.get("research_id")
        and proof.get("thesis_version") == review.get("research_id")
        and publication.get("request_id") == out["request_id"]
        and publication.get("security_guid") == truth.get("security_guid")
        and at is not None
        and _time(review.get("answered_at")) == at
        and review.get("resolution_proven") is True
        and (review.get("answered_at") or review.get("completed_at") or review.get("conflict_resolved_at"))
    )
    out["publication_verified"] = linked
    out["answered_at"] = proof.get("published_at") or publication.get("at")
    out["answer_age_hours"] = max(0, (now - at).total_seconds() / 3600) if at else None
    age = out["answer_age_hours"]
    label = (
        f"{int(age // 24)} d ago"
        if age is not None and age >= 24
        else f"{int(age)} h ago"
        if age is not None
        else "time unknown"
    )
    if linked:
        out["label"] = f"Answered — linked CIO record · published {label}"
        out["answer_summary"] = review.get("reason")
        out["research_id"] = review.get("research_id")
    else:
        day = at.date().isoformat() if at else "date unknown"
        out["label"] = f"Previous research published {day} · {label} — current CIO linkage unavailable; refresh"
        memory = publication.get("cio_link") or {}
        if (
            memory.get("ok") is True
            and memory.get("state") == "ANSWERED_PENDING_CIO"
            and publication.get("request_id") == out.get("request_id")
            and publication.get("security_guid") == truth.get("security_guid")
        ):
            out["label"] = f"Research published {day} · {label} — CIO decision pending"
            out["research_link_verified"] = True
            out["answer_summary"] = memory.get("answer_summary")
    return out


def review_status(query=None, *, priority_reader=None, stance_reader=None, now=None):
    """GET watch-curation?review_status=1&symbols=ZZAA,ZZBB; no provider/write."""
    now = now or datetime.now(timezone.utc)
    raw = (query or {}).get("symbols") or ""
    if isinstance(raw, list):
        raw = raw[0] if len(raw) == 1 else ",".join(raw)
    names = sorted(set(str(raw).upper().split(",")))
    if not names or len(names) > MAX_SYMBOLS or any(not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,9}", s) for s in names):
        return {"ok": False, "error": "invalid_review_symbols", "max_symbols": MAX_SYMBOLS}
    try:
        if priority_reader is None:
            from scripts.lib.symbol_thesis_priority import review_states

            priority_reader = review_states
        if stance_reader is None:
            from scripts.lib.cio_truth import stances_for_symbols
            from scripts.lib.data_broker.cio_prospect import get_prospects
            from scripts.lib.data_broker.watch_prospects import _db_query

            projection = get_prospects(db_query=_db_query(), now=now)
            stance_reader = lambda symbols: stances_for_symbols(symbols, projection=projection, now=now)
        states = priority_reader(names)
        truths = stance_reader(names)
    except Exception as exc:  # no credentials or raw exception text in a surface
        LOG.warning(
            "watch_review_status_unavailable",
            extra={"error_class": type(exc).__name__, "projection": "watch_review_status"},
        )
        return {
            "ok": False,
            "schema": "WatchReviewStatus@v1",
            "error": "review_status_unavailable",
            "reason": type(exc).__name__,
            "rows": {},
            "provider_calls": 0,
            "read_only": True,
        }
    return {
        "ok": True,
        "schema": "WatchReviewStatus@v1",
        "as_of": now.isoformat(),
        "rows": {
            s: presentation_state(
                states.get(s) or {"status": "unavailable", "label": "Review status unavailable", "open": False},
                truths.get(s) or {},
                now=now,
            )
            for s in names
        },
        "read_only": True,
        "provider_calls": 0,
    }
