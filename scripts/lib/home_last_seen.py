"""Home "Since last visit" anchor: the ``home.last_seen`` key of ``/api/v2/ui/prefs`` (LQ-20261107-2142).

The Home page stamps the moment the operator last looked; the next visit reads it to say what changed
since. Only the page writes it and only this shape is accepted, so the anchor cannot be filled with
arbitrary JSON or rewound by a stale tab. A read never invents a visit: no record is ``NOT_RECORDED`` and
the page falls back to "last 24 h" saying so; an unreadable record is ``UNKNOWN`` with the reason, never a
guessed time. Pure functions; the endpoint owns the database.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

KEY = "home.last_seen"
SCHEMA = "HomeLastSeen@v1"
FALLBACK_WINDOW_HOURS = 24
#: A clock that runs ahead of the server by more than this is rejected, not stored.
MAX_FUTURE = timedelta(minutes=5)
_EARLIEST = datetime(2020, 1, 1, tzinfo=timezone.utc)
CLIENTS = ("web", "phone")


def parse_ts(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:  # a naive time is ambiguous; refuse rather than assume a zone
        return None
    return dt.astimezone(timezone.utc)


def validate(value: Any, *, now: datetime) -> tuple[Optional[dict], Optional[str]]:
    """``(normalised, None)`` or ``(None, reason)``. Accepts only ``{"seen_at": ISO8601 with zone, "client"?}``."""
    if not isinstance(value, dict):
        return None, "value must be an object {seen_at, client?}"
    extra = set(value) - {"seen_at", "client"}
    if extra:
        return None, f"unexpected field(s): {', '.join(sorted(extra))}"
    seen = parse_ts(value.get("seen_at"))
    if seen is None:
        return None, "seen_at must be an ISO-8601 time with a zone"
    if seen < _EARLIEST:
        return None, "seen_at is implausibly old"
    if seen > now + MAX_FUTURE:
        return None, "seen_at is in the future"
    client = value.get("client")
    if client is not None and client not in CLIENTS:
        return None, f"client must be one of {list(CLIENTS)}"
    out = {"seen_at": seen.isoformat()}
    if client is not None:
        out["client"] = client
    return out, None


def is_rewind(new: dict, stored_value: Any) -> bool:
    """True when ``new`` is older than what is stored: a stale tab must not move the anchor back."""
    old = parse_ts(stored_value.get("seen_at")) if isinstance(stored_value, dict) else None
    return old is not None and parse_ts(new["seen_at"]) < old


def read(value: Any, updated_at: Any, *, now: datetime, exists: bool) -> dict:
    """The page-facing reading. ``exists`` is whether a row was found at all."""
    fallback = {"window_hours": FALLBACK_WINDOW_HOURS,
                "text": f"last {FALLBACK_WINDOW_HOURS} h (your last visit is not recorded)"}
    if not exists:
        return {"schema": SCHEMA, "status": "NOT_RECORDED", "seen_at": None, "age_sec": None, "fallback": fallback}
    norm, why = validate(value, now=now) if isinstance(value, dict) else (None, "value is not an object")
    if norm is None:
        return {"schema": SCHEMA, "status": "UNKNOWN", "seen_at": None, "age_sec": None,
                "reason": f"stored last-seen is unreadable: {why}", "fallback": fallback}
    seen = parse_ts(norm["seen_at"])
    return {"schema": SCHEMA, "status": "RECORDED", "seen_at": norm["seen_at"],
            "age_sec": max(0, int((now - seen).total_seconds())), "client": norm.get("client")}
