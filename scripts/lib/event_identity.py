"""Event-specific GUIDs. Earnings is not a timeless catalyst."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "SecurityEvent@v1"
STATUSES = ("SCHEDULED", "OCCURRED", "POST_EVENT", "SUPERSEDED", "CANCELLED", "UNKNOWN")

# Event types whose natural lifecycle unit is a fiscal quarter. Everything else
# is dated to the day: two analyst downgrades in one quarter are two events,
# while two Q3 earnings reports for one issuer are a data error, not two events.
QUARTERLY_TYPES = frozenset({
    "earnings_beat", "earnings_miss", "earnings", "earnings_preview", "guidance",
})


def period_for(catalyst_type: str, when: Any) -> str | None:
    """Lifecycle bucket for an event. None when the timestamp is unusable.

    A missing period yields no event_guid at all rather than a shared placeholder,
    which would merge unrelated events onto one node.
    """
    dt = _as_dt(when)
    if dt is None:
        return None
    if str(catalyst_type or "").strip().lower() in QUARTERLY_TYPES:
        return f"{dt.year}Q{(dt.month - 1) // 3 + 1}"
    return f"{dt:%Y%m%d}"


def _as_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def event_guid(*, issuer_guid: str | None, event_type: str, period: str) -> str | None:
    issuer = str(issuer_guid or "").strip()
    et = str(event_type or "").strip().upper()
    per = str(period or "").strip().upper()
    if not issuer or not et or not per:
        return None
    payload = f"tradeai:event:{issuer}|{et}|{per}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, payload))


def build_event(
    *,
    issuer_guid: str | None,
    security_guid: str | None,
    event_type: str,
    period: str,
    status: str = "UNKNOWN",
    as_of: str | None = None,
) -> dict[str, Any]:
    st = status if status in STATUSES else "UNKNOWN"
    guid = event_guid(issuer_guid=issuer_guid, event_type=event_type, period=period)
    return {
        "schema": SCHEMA,
        "event_guid": guid,
        "issuer_guid": issuer_guid,
        "security_guid": security_guid,
        "event_type": str(event_type or "").upper(),
        "period": str(period or "").upper(),
        "status": st,
        "as_of": as_of,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def supersede_scheduled(scheduled: dict[str, Any], *, occurred_as_of: str) -> dict[str, Any]:
    """Scheduled-event evidence becomes historical once the event occurs."""
    row = dict(scheduled or {})
    if row.get("status") == "SCHEDULED":
        row["status"] = "SUPERSEDED"
        row["superseded_at"] = occurred_as_of
        row["supersession_reason"] = "event_occurred"
    return row
