"""Home "Since last visit" anchor: the ``home.last_seen`` key of ``/api/v2/ui/prefs`` (LQ-20261107-2142).

Shape (HOME-BACKEND-SPEC-20261111 LQ-2142): ``{"seen_at", "previous_seen_at", "device": "phone|desktop"}``.
The operator's visit is the event, so the writer is the page's ``POST /api/v2/ui/prefs``; the *server* owns
the times: ``seen_at`` is server ``now()`` (a client time is ignored), ``previous_seen_at`` is copied from the
stored ``seen_at`` (a client value is ignored), so a second tab cannot erase the window. A read never
invents a visit: no record -> ``window_basis: "fallback_24h"``, ``last_visit_recorded: false``; an
unreadable record is the same fallback with ``status: UNKNOWN`` and the reason. Pure functions.

``portfolio.last_seen`` (LQ-20261107-2467, Portfolio v002 G13) is the same contract under its own key and schema:
the same server stamping, the same operator-session + CSRF write gate, its own window (a Home visit never moves the
Portfolio anchor). ``LAST_SEEN_KEYS`` is the only list of keys that get this treatment.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

KEY = "home.last_seen"
SCHEMA = "HomeLastSeen@v1"
PORTFOLIO_KEY = "portfolio.last_seen"
LAST_SEEN_KEYS = {KEY: SCHEMA, PORTFOLIO_KEY: "PortfolioLastSeen@v1"}
FALLBACK_WINDOW_HOURS = 24
DEVICES = ("phone", "desktop")


def is_last_seen_key(key: Any) -> bool:
    """True for a key whose writes are server-stamped and gated (home.last_seen, portfolio.last_seen)."""
    return isinstance(key, str) and key.strip() in LAST_SEEN_KEYS


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


def stamp(client_value: Any, stored_value: Any, *, now: datetime) -> tuple[Optional[dict], Optional[str]]:
    """The value to store: ``(new, None)`` or ``(None, reason)``.

    Only ``device`` is taken from the client; ``seen_at`` / ``previous_seen_at`` from the client are ignored.
    """
    if not isinstance(client_value, dict):
        return None, "value must be an object {device}"
    device = client_value.get("device")
    if device not in DEVICES:
        return None, f"device must be one of {list(DEVICES)}"
    prev = parse_ts(stored_value.get("seen_at")) if isinstance(stored_value, dict) else None
    return {"seen_at": now.astimezone(timezone.utc).isoformat(),
            "previous_seen_at": prev.isoformat() if prev else None,
            "device": device}, None


def read(value: Any, updated_at: Any, *, now: datetime, exists: bool, key: str = KEY) -> dict:
    """The page-facing reading. ``exists`` is whether a row was found at all. ``key`` picks the schema name."""
    schema = LAST_SEEN_KEYS.get(key.strip() if isinstance(key, str) else key)
    if schema is None:
        raise ValueError(f"not a last-seen key: {key!r}")
    fb = {"window_basis": "fallback_24h", "last_visit_recorded": False, "fallback_window_hours": FALLBACK_WINDOW_HOURS,
          "fallback_text": f"last {FALLBACK_WINDOW_HOURS} h (your last visit is not recorded)",
          "seen_at": None, "previous_seen_at": None, "age_sec": None, "device": None, "schema": schema}
    if not exists:
        return {**fb, "status": "NOT_RECORDED"}
    seen = parse_ts(value.get("seen_at")) if isinstance(value, dict) else None
    if seen is None:
        return {**fb, "status": "UNKNOWN", "reason": "stored last-seen is unreadable: no valid seen_at"}
    prev = parse_ts(value.get("previous_seen_at"))
    return {"schema": schema, "status": "RECORDED", "window_basis": "last_visit", "last_visit_recorded": True,
            "seen_at": seen.isoformat(), "previous_seen_at": prev.isoformat() if prev else None,
            "age_sec": max(0, int((now - seen).total_seconds())),
            "device": value.get("device") if value.get("device") in DEVICES else None}
