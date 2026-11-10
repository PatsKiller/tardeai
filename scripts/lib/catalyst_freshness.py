"""Publish-age gate for catalyst_events writers (LQ-20261107-1817).

A catalyst row means "something just happened". An article published long before ingest is a backfill:
it stays in news_articles but must not become a new catalyst. The threshold lives in
config/catalyst_ingest_freshness.json (``max_publish_age_hours``; 0 disables the gate).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional

_CONFIG = Path(__file__).resolve().parents[2] / "config" / "catalyst_ingest_freshness.json"
DEFAULT_MAX_AGE_HOURS = 72.0


def max_age_hours(config_path: Optional[Path] = None) -> float:
    try:
        return float(json.loads((config_path or _CONFIG).read_text()).get("max_publish_age_hours", DEFAULT_MAX_AGE_HOURS))
    except (OSError, ValueError, TypeError):
        return DEFAULT_MAX_AGE_HOURS


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
    limit = max_age_hours() if max_hours is None else max_hours
    if not limit or limit <= 0:
        return False
    pub = parse_published(published_at)
    if pub is None:
        return False
    now = now or datetime.now(timezone.utc)
    return (now - pub).total_seconds() > limit * 3600
