#!/usr/bin/env python3
"""CommsHistoryPort backed by real communication_events — what the desk already said.

WakeEngine has always loaded prior comms before deciding (persistent_agent_wake
lines 405-412 populate `prior_comm_event_ids` and `prior_operator_turn_ids`).
Production never gave it anything to load: `run_scheduled_wake` defaults
`comms=None` -> `NullCommsHistory()`, and the runner never passed one. So across
24 organic wakes those fields were non-empty on ZERO, and the agent re-raised
subjects it had messaged about an hour earlier with no idea it had done so.

Nothing was missing but the plug.

HONEST LIMIT, worth stating rather than discovering later: this reads
`communication_events.subject_guid`, which is NULL on all 604 live rows because
outbound messages are produced by `telegram_alert.send_telegram` and never
tagged. Until that path is routed through the CIO write chokepoint (Phase 7),
this port returns empty for most subjects and the wake is no worse off than with
the null port. It is wired now so the moment messages carry identity, memory
starts accumulating without another change.

AUTHORITY: READ_ONLY_ADVISORY. Lane A reads Lane B; it never writes comms tables.
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

#: An operator turn is inbound; anything else the desk said is an outbound event.
_OPERATOR_TYPES = ("operator_turn", "telegram_command", "callback_query")


class DbCommsHistory:
    """Reads prior comms for one subject. Degrades to empty, never raises.

    A wake must not fail because history is unavailable: no history is a
    legitimate state (a subject genuinely new to the desk), and conflating that
    with a broken read would make the wake flaky for no gain.
    """

    def __init__(self, conn_factory: Any = None) -> None:
        self._conn_factory = conn_factory

    def _rows(self, sql: str, params: tuple) -> list[dict]:
        try:
            factory = self._conn_factory
            if factory is None:
                from scripts.lib.comms.agent_contracts import _db_conn as factory
            conn = factory()
            if conn is None:
                return []
            cur = conn.cursor()
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            return []

    def prior_comm_events(self, subject_guid: str, *, limit: int = 20) -> list[dict]:
        """What the desk has already SAID about this subject."""
        return self._rows(
            """SELECT event_id, event_type, direction, sanitized_body, created_at
                 FROM communication_events
                WHERE subject_guid = %s AND direction = 'OUTBOUND'
                ORDER BY created_at DESC LIMIT %s""",
            (str(subject_guid), int(limit)))

    def prior_operator_turns(self, subject_guid: str, *, limit: int = 20) -> list[dict]:
        """What the OPERATOR has said about it."""
        return self._rows(
            """SELECT event_id, event_type, sanitized_body, created_at
                 FROM communication_events
                WHERE subject_guid = %s AND direction = 'INBOUND'
                  AND event_type = ANY(%s)
                ORDER BY created_at DESC LIMIT %s""",
            (str(subject_guid), list(_OPERATOR_TYPES), int(limit)))


__all__ = ["DbCommsHistory", "AUTHORITY", "MBI"]
