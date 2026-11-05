"""FQ-143 / D32 §6: a receipt per channel, in the durable outbox, not in a log line.

The spec asks for "delivery receipts for every channel ... if SMS fails, email and Telegram still go, and the failure is
flagged on Home". `critical_channels.deliver` produces those receipts in memory; this module is where they land, so the
operator-facing page can read them back after the process that sent them has gone.

It writes into the existing outbox table rather than a second one: `alert_notification_deliveries` is already one row per
attempt, and migration 2026_11_05 added the two columns it was missing (`channel`, `provider_receipt`).

Two rules, the same two the ack writer keeps:

  * **map the outcome to a status the table allows.** The column only accepts queued / claimed / sent / failed / suppressed /
    abandoned, so "skipped" — a channel that had nothing to send to — is recorded as `suppressed` with the reason in
    `delivery_reason`. Writing a status the CHECK rejects would lose the row, and a lost receipt is worse than a rough one.
  * **no durable store, no claim.** Without the outbox migration there is nothing to write to; that is reported, never
    swallowed, because a receipt nobody can read is indistinguishable from an alert nobody sent.
"""
from __future__ import annotations

from typing import Any, Optional

#: The table's own vocabulary (alert_notification_deliveries.delivery_status CHECK constraint).
ALLOWED_STATUSES = frozenset({"queued", "claimed", "sent", "failed", "suppressed", "abandoned"})

#: How this module's outcomes map onto that vocabulary.
STATUS_MAP = {"sent": "sent", "failed": "failed", "skipped": "suppressed"}

NO_STORE = "durable_store_unavailable"


class ReceiptError(ValueError):
    """A fixed reason. Never carries an address, a token or a message body."""


def _conn(conn: Any = None, connect: Optional[Any] = None) -> Any:
    if conn is not None:
        return conn
    try:
        if connect is not None:
            return connect()
        from alert_outbox import _db as _outbox_db  # the outbox owns the connection policy
        return _outbox_db()
    except Exception:
        return None


def record(alert_id: str, receipts: list[dict[str, Any]], *, conn: Any = None, connect: Optional[Any] = None,
           incident_id: str | None = None, attempt_seq: int = 1) -> dict[str, Any]:
    """Write one row per channel. Returns what was written, or why nothing could be.

    Each receipt is the shape ``critical_channels.Receipt.as_dict()`` returns:
    ``{"channel", "status", "reason", "provider_receipt"}``.
    """
    ident = str(alert_id or "").strip()
    if not ident:
        raise ReceiptError("alert_id_required")
    if not receipts:
        return {"ok": True, "written": 0, "outcome": "nothing_to_record"}
    for r in receipts:
        if STATUS_MAP.get(str(r.get("status"))) is None:
            raise ReceiptError("unknown_receipt_status")

    connection = _conn(conn, connect)
    if connection is None:
        return {"ok": False, "written": 0, "outcome": NO_STORE}

    cur = connection.cursor()
    written = 0
    try:
        for r in receipts:
            cur.execute(
                "INSERT INTO alert_notification_deliveries "
                "(alert_id, incident_id, attempt_seq, channel, delivery_status, delivery_reason, provider_receipt, "
                " rendered_message) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (ident, incident_id, attempt_seq, str(r.get("channel") or ""), STATUS_MAP[str(r["status"])],
                 r.get("reason"), r.get("provider_receipt"), None),
            )
            written += 1
        connection.commit()
        return {"ok": True, "written": written, "outcome": "recorded"}
    except Exception:
        try:
            connection.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cur.close()
        except Exception:
            pass


def for_alert(alert_id: str, *, conn: Any = None, connect: Optional[Any] = None) -> list[dict[str, Any]]:
    """Every receipt recorded for one event, newest attempt first. Empty list when the store is unavailable."""
    ident = str(alert_id or "").strip()
    if not ident:
        raise ReceiptError("alert_id_required")
    connection = _conn(conn, connect)
    if connection is None:
        raise ReceiptError(NO_STORE)
    cur = connection.cursor()
    try:
        cur.execute(
            "SELECT channel, delivery_status, delivery_reason, provider_receipt, created_at "
            "FROM alert_notification_deliveries WHERE alert_id = %s ORDER BY created_at DESC, id DESC",
            (ident,),
        )
        rows = cur.fetchall() or []
    finally:
        try:
            cur.close()
        except Exception:
            pass
    return [{"channel": r[0], "status": r[1], "reason": r[2], "provider_receipt": r[3], "created_at": r[4]} for r in rows]


def confirmed(receipts: list[dict[str, Any]]) -> bool:
    """DELIVERED, as the spec defines it: at least one channel confirmed. A stored `sent` is the confirmation."""
    return any(str(r.get("status")) == "sent" for r in receipts)
