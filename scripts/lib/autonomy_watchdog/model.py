"""Component state model + New York calendar day."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")

HEALTHY = "HEALTHY"
EXPECTED_IDLE = "EXPECTED_IDLE"
DEGRADED = "DEGRADED"
STALE = "STALE"
FAILED = "FAILED"
NOT_CONFIGURED = "NOT_CONFIGURED"

STATES = (HEALTHY, EXPECTED_IDLE, DEGRADED, STALE, FAILED, NOT_CONFIGURED)

# Worst-first for rollup. EXPECTED_IDLE and NOT_CONFIGURED never escalate
# into FAILED/HEALTHY by this map — callers must not remap them.
_RANK = {
    FAILED: 50,
    DEGRADED: 40,
    STALE: 30,
    HEALTHY: 20,
    EXPECTED_IDLE: 10,
    NOT_CONFIGURED: 0,
}

SCHEMA = "DailyIntelligenceHeartbeat@v1"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ny_now(now: Optional[datetime] = None) -> datetime:
    dt = now or now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)


def ny_date(now: Optional[datetime] = None) -> str:
    return ny_now(now).date().isoformat()


def ny_day_bounds(day: Optional[str] = None, now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    if day:
        d = datetime.fromisoformat(day).date()
    else:
        d = ny_now(now).date()
    start = datetime(d.year, d.month, d.day, tzinfo=TZ)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def parse_ts(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if not s or s in {"n/a", "unknown", "-"}:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def in_day(ts: Any, start: datetime, end: datetime) -> bool:
    dt = parse_ts(ts)
    return bool(dt and start <= dt < end)


def age_seconds(ts: Any, now: Optional[datetime] = None) -> Optional[float]:
    dt = parse_ts(ts)
    if dt is None:
        return None
    return max(0.0, ((now or now_utc()) - dt).total_seconds())


def component(
    name: str,
    status: str,
    *,
    observed_at: Optional[str] = None,
    last_success: Any = None,
    last_failure: Any = None,
    reason: str = "",
    source: str = "",
    consecutive_failures: int = 0,
    extras: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    if status not in STATES:
        status = DEGRADED
        reason = (reason + " unknown_status").strip()
    rec: dict[str, Any] = {
        "component": name,
        "status": status,
        "observed_at": observed_at or (now or now_utc()).isoformat(),
        "last_success": last_success,
        "last_failure": last_failure,
        "age_seconds": age_seconds(last_success, now),
        "reason": reason,
        "source": source,
        "consecutive_failures": int(consecutive_failures or 0),
    }
    if extras:
        rec.update(extras)
    return rec


def rollup(statuses: list[str]) -> str:
    """Overall status. EXPECTED_IDLE/NOT_CONFIGURED never become FAILED/HEALTHY."""
    if not statuses:
        return NOT_CONFIGURED
    worst = NOT_CONFIGURED
    for s in statuses:
        if _RANK.get(s, 0) > _RANK.get(worst, 0):
            worst = s
    return worst
