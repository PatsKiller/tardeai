"""Freshness classification for holding-drawer Hermes / CIO intel rows.

Policy (aligned with Hermes FRESH_HOURS=12 for "current"):
  CURRENT  — age_hours <= 12
  STALE    — 12 < age_hours <= 168 (7d)
  EXPIRED  — age_hours > 168
  UNDATED  — missing / unparseable timestamp
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

FRESH_HOURS = 12
STALE_HOURS = 168  # 7 days


def _to_aware(dt: Any) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    if isinstance(dt, str):
        s = dt.strip()
        if not s:
            return None
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            parsed = datetime.fromisoformat(s)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            return None
    return None


def age_hours(at: Any, *, now: datetime | None = None) -> float | None:
    dt = _to_aware(at)
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def classify_freshness(at: Any, *, now: datetime | None = None) -> str:
    h = age_hours(at, now=now)
    if h is None:
        return "UNDATED"
    if h <= FRESH_HOURS:
        return "CURRENT"
    if h <= STALE_HOURS:
        return "STALE"
    return "EXPIRED"


def annotate_external_row(row: dict, *, now: datetime | None = None) -> dict:
    """Return a shallow copy with freshness_class + age_hours."""
    out = dict(row)
    at = out.get("at") or out.get("created_at")
    out["age_hours"] = age_hours(at, now=now)
    out["freshness_class"] = classify_freshness(at, now=now)
    return out


def is_refusal_narrative(text: str | None) -> bool:
    t = (text or "").lstrip("*#_ ").lower()
    if t.startswith("llm error:"):
        return True
    return t.startswith(
        (
            "i cannot fulfill",
            "i can't fulfill",
            "i cannot help",
            "i can't help",
            "i'm unable to",
            "i am unable to",
            "i cannot act as",
            "i can't act as",
            "i cannot provide",
            "i can't provide",
        )
    )


def synthesis_status_from_narrative(narrative: str | None) -> str:
    """ok | refused | error | empty."""
    if narrative is None or not str(narrative).strip():
        return "empty"
    s = str(narrative).strip()
    if is_refusal_narrative(s):
        if "refused" in s.lower():
            return "refused"
        return "error"
    return "ok"
