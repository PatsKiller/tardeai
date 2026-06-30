"""Shared quote / advisor timestamp normalization for the protective-stop path.

The holdings/quote sources emit several timestamp shapes:
  - ISO 8601 with offset     2026-06-30T15:30:03-04:00
  - ISO 8601 'Z'             2026-06-30T19:30:03Z
  - space-separated local    2026-06-30 15:30:03            (interpreted as America/New_York)
  - explicit ET suffix       2026-06-30 16:15:02 ET         (America/New_York; EDT/EST resolved)

`datetime.fromisoformat()` raises on the ' ET' / space-separated shapes, which previously surfaced a raw
"Invalid isoformat string" to the operator. This module returns ONE tz-aware datetime (or None) so callers
can BLOCK with a human-readable message instead, plus an ET-based US-equity session classification.

Never silently uses a naive datetime: a naive/space-separated quote is interpreted as America/New_York
(the timezone the quote feeds report in), and an unparseable value returns None.
"""
from __future__ import annotations

import datetime as _dt
import re as _re

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - zoneinfo always present on 3.9+, tzdata installed
    _ET = None

_ET_SUFFIX = _re.compile(r"\s+E[DS]?T$", _re.IGNORECASE)


def _et_fallback_offset(naive: _dt.datetime) -> _dt.timezone:
    """Approximate US Eastern DST if zoneinfo is unavailable: Mar–Nov ≈ EDT(-4), else EST(-5)."""
    return _dt.timezone(_dt.timedelta(hours=-4 if 3 <= naive.month <= 11 else -5))


def _attach_et(naive: _dt.datetime) -> _dt.datetime:
    return naive.replace(tzinfo=_ET) if _ET else naive.replace(tzinfo=_et_fallback_offset(naive))


def parse_quote_ts(raw):
    """Return a tz-aware datetime for `raw`, or None if it cannot be parsed (caller must block, not throw)."""
    if raw is None:
        return None
    if isinstance(raw, _dt.datetime):
        return raw if raw.tzinfo else _attach_et(raw)
    s = str(raw).strip()
    if not s:
        return None
    # explicit ET suffix -> America/New_York (zoneinfo resolves EDT vs EST for the date)
    m = _ET_SUFFIX.search(s)
    if m:
        base = s[: m.start()].strip().replace("T", " ")
        for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                naive = _dt.datetime.fromisoformat(base) if fmt is None else _dt.datetime.strptime(base, fmt)
                return naive if naive.tzinfo else _attach_et(naive)
            except ValueError:
                continue
        return None
    # ISO with offset / 'Z' / naive space-separated
    try:
        dt = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else _attach_et(dt)  # naive space-separated quote -> ET, never silent UTC


def to_iso(raw):
    """Normalized tz-aware RFC3339/ISO string, or None."""
    dt = parse_quote_ts(raw)
    return dt.isoformat() if dt else None


def quote_age_seconds(raw, now=None):
    """Age of the quote in seconds, or None if unparseable."""
    dt = parse_quote_ts(raw)
    if dt is None:
        return None
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return (now.astimezone(_dt.timezone.utc) - dt.astimezone(_dt.timezone.utc)).total_seconds()


def classify_session(raw, now=None):
    """US-equity session for the QUOTE time (America/New_York):
      'regular'     Mon–Fri 09:30–16:00 ET
      'pre_market'  Mon–Fri 04:00–09:30 ET
      'after_hours' Mon–Fri 16:00–20:00 ET
      'closed'      otherwise (overnight / weekend)
      'unknown'     timestamp could not be parsed
    """
    dt = parse_quote_ts(raw)
    if dt is None:
        return "unknown"
    et = dt.astimezone(_ET) if _ET else dt
    if et.weekday() >= 5:
        return "closed"
    minutes = et.hour * 60 + et.minute
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return "regular"
    if 4 * 60 <= minutes < 9 * 60 + 30:
        return "pre_market"
    if 16 * 60 <= minutes < 20 * 60:
        return "after_hours"
    return "closed"


# Freshness window (seconds) for a live-stop request quote.
FRESH_MAX_AGE_SEC = 15 * 60
