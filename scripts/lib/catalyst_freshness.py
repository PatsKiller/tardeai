"""Publish-age gate for catalyst_events writers (LQ-20261107-1817).

A catalyst row means "something just happened". An article published long before ingest is a backfill:
it stays in news_articles but must not become a new catalyst. The threshold lives in
config/catalyst_ingest_freshness.json (``max_publish_age_hours``; 0 disables the gate).
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional, Tuple

_CONFIG = Path(__file__).resolve().parents[2] / "config" / "catalyst_ingest_freshness.json"
# Fail-CLOSED fallback, used only when the config file is missing, empty, malformed, not a JSON object, or holds an
# invalid limit (negative / NaN / inf / non-numeric). It keeps the gate ON; it is never a silent value: every use
# logs a WARNING and callers surface ``config_unreadable``. The normal source of truth is the config file.
DEFAULT_MAX_AGE_HOURS = 72.0
STATUS_OK = "ok"
STATUS_UNREADABLE = "config_unreadable"
_log = logging.getLogger(__name__)


def resolve_limit(config_path: Optional[Path] = None) -> Tuple[float, str]:
    """(max_age_hours, status). status is ``ok`` or ``config_unreadable`` (fallback constant in use, warned)."""
    path = config_path or _CONFIG
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError(f"top-level JSON is {type(data).__name__}, not an object")
        if "max_publish_age_hours" not in data:
            raise ValueError("key max_publish_age_hours missing")
        val = float(data["max_publish_age_hours"])
        if math.isnan(val) or math.isinf(val) or val < 0:
            raise ValueError(f"invalid limit {data['max_publish_age_hours']!r}")
        return val, STATUS_OK
    except (OSError, ValueError, TypeError) as exc:
        _log.warning("catalyst freshness config unreadable (%s: %s); gate stays ON with fallback %sh",
                     path, exc, DEFAULT_MAX_AGE_HOURS)
        return DEFAULT_MAX_AGE_HOURS, STATUS_UNREADABLE


def max_age_hours(config_path: Optional[Path] = None) -> float:
    return resolve_limit(config_path)[0]


def parse_published(value: Any) -> Optional[datetime]:
    """Aware UTC datetime from a datetime, ISO-8601 or RFC-822 string; naive values are taken as UTC."""
    if value is None or value == "":
        return None
    dt = value
    if not isinstance(dt, datetime):
        text = str(value).strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = parsedate_to_datetime(text)
            except (TypeError, ValueError):
                return None
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def is_backfill(published_at: Any, *, now: Optional[datetime] = None, max_hours: Optional[float] = None) -> bool:
    """True when the item is older than the configured cutoff. Unknown/unparseable dates are not backfill."""
    limit = max_age_hours() if max_hours is None else max_hours   # hot loops pass max_hours (resolve once)
    if not limit or limit <= 0:
        return False
    pub = parse_published(published_at)
    if pub is None:
        return False
    now = now or datetime.now(timezone.utc)
    return (now - pub).total_seconds() > limit * 3600
