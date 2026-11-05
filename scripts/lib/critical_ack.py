"""FQ-143 / D32 §6: one acknowledgement stops the repeats, on every channel.

The operator's words: "acknowledge once ... and the repeats stop on all channels." The mechanism half-exists already —
`alert_incidents.acknowledged_at` and `acknowledged_by` are in the schema, and `alert_dedupe` refuses to escalate while
`acknowledged_at` is set (`scripts/alert_dedupe.py:138-140`) — but **nothing in the tree ever writes them**. This module is
that writer, and nothing else: it does not decide what is critical, does not send, and does not touch a delivery row.

Two rules it keeps:

  * **Ack is idempotent.** The first acknowledgement wins and records who; a second returns `already` and changes nothing, so
    a double tap, a retried request or two channels acking at once cannot rewrite the history of who saw it first.
  * **No durable store, no claim of success.** `alert_outbox._db()` degrades to an in-memory store when the migration is
    absent. An acknowledgement that says "done" while writing to a fallback nobody reads would leave the repeats running and
    the operator believing they had stopped, so a missing store is reported as `durable_store_unavailable`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

#: Fixed outcomes. A caller switches on these; none of them is a sentence about the world.
ACKED = "acked"
ALREADY = "already_acknowledged"
NOT_FOUND = "incident_not_found"
NO_STORE = "durable_store_unavailable"


class AckError(ValueError):
    """A fixed reason. Never carries an incident's payload, a symbol or an operator's name."""


def _utc_now(now: Optional[datetime]) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def acknowledge(incident_id: str, by: str, *, conn: Any = None, connect: Optional[Callable[[], Any]] = None,
                now: Optional[datetime] = None) -> dict[str, Any]:
    """Acknowledge one incident. Returns a fixed outcome, never raises for a predictable condition.

    ``conn`` is injected so the behaviour is testable without a database; ``connect`` defaults to the outbox's own
    accessor, which already refuses to hand back a connection to an unmigrated database.
    """
    incident = str(incident_id or "").strip()
    who = str(by or "").strip()
    if not incident:
        raise AckError("incident_id_required")
    if not who:
        # An ack with no author is not an ack: the whole point is knowing who saw it.
        raise AckError("acknowledger_required")

    if conn is None:
        try:
            if connect is not None:
                conn = connect()
            else:
                from alert_outbox import _db as _outbox_db  # the outbox owns the connection policy
                conn = _outbox_db()
        except Exception:
            conn = None
    if conn is None:
        return {"ok": False, "outcome": NO_STORE, "incident_id": incident}

    stamp = _utc_now(now)
    cur = conn.cursor()
    try:
        # The WHERE clause is what makes this idempotent: only an unacknowledged row can be claimed, so two racing acks
        # produce exactly one winner and the loser learns it lost rather than overwriting the first.
        cur.execute(
            "UPDATE alert_incidents SET acknowledged_at = %s, acknowledged_by = %s "
            "WHERE incident_id = %s AND acknowledged_at IS NULL",
            (stamp, who, incident),
        )
        updated = cur.rowcount
        if not updated:
            cur.execute("SELECT acknowledged_at, acknowledged_by FROM alert_incidents WHERE incident_id = %s", (incident,))
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                return {"ok": False, "outcome": NOT_FOUND, "incident_id": incident}
            conn.rollback()
            return {"ok": True, "outcome": ALREADY, "incident_id": incident,
                    "acknowledged_by": row[1], "acknowledged_at": row[0]}
        conn.commit()
        return {"ok": True, "outcome": ACKED, "incident_id": incident, "acknowledged_by": who,
                "acknowledged_at": stamp}
    except Exception:
        try:
            conn.rollback()
        except Exception:  # noqa: S110 - cleanup path: the exception is re-raised or the resource is closing; nothing to log
            pass
        raise
    finally:
        try:
            cur.close()
        except Exception:  # noqa: S110 - cleanup path: the exception is re-raised or the resource is closing; nothing to log
            pass


def stops_repeats(incident: dict[str, Any]) -> bool:
    """Whether the dedupe/escalation path will now stay quiet for this incident.

    Kept next to the writer so the two cannot drift: the rule the reader applies (`alert_dedupe.py:138-140`) is exactly
    "acknowledged_at is set".
    """
    return incident.get("acknowledged_at") is not None
