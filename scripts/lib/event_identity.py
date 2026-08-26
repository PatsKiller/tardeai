"""Event-specific GUIDs. Earnings is not a timeless catalyst."""
from __future__ import annotations

import uuid
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "SecurityEvent@v1"
STATUSES = ("SCHEDULED", "OCCURRED", "POST_EVENT", "SUPERSEDED", "CANCELLED", "UNKNOWN")


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
