#!/usr/bin/env python3
"""CommsHistoryPort backed by real communication_events — what the desk already said.

WakeEngine has always loaded prior comms before deciding (persistent_agent_wake
lines 405-412 populate `prior_comm_event_ids` and `prior_operator_turn_ids`).
Production never gave it anything to load: `run_scheduled_wake` defaults
`comms=None` -> `NullCommsHistory()`, and the runner never passed one. So across
24 organic wakes those fields were non-empty on ZERO, and the agent re-raised
subjects it had messaged about an hour earlier with no idea it had done so.

Nothing was missing but the plug.

HONEST LIMIT, worth stating rather than discovering later: `prior_comm_events`
reads `communication_events.subject_guid`, which is NULL on all 604 live rows
because outbound messages are produced by `telegram_alert.send_telegram` and
never tagged. Until that path is routed through the CIO write chokepoint
(Phase 7), that method returns empty for most subjects and the wake is no worse
off than with the null port.

`prior_operator_turns` HAD the same limit and it was worse there, because for
INBOUND rows the column is not merely sparse but never populated at all — 146
rows, zero subjects, all time. It now reads `operator_conversation_turns`, where
the binding actually lands. See that method for why.

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
        """What the OPERATOR has said about it.

        READS operator_conversation_turns, NOT communication_events.

        The original query filtered `communication_events.subject_guid` on
        INBOUND rows. That column is stamped only by `tag_outbound_event`, whose
        sole caller sits on the OUTBOUND path, so it is NULL on every inbound row
        that has ever existed — measured 2026-09-11: OUTBOUND 792 rows / 172 with
        a subject, INBOUND 146 rows / ZERO. The predicate was not merely
        unproductive, it was unsatisfiable, and had been since it was written.

        It showed: at 19:00Z the operator asked "ADBE — what did Q3 actually show
        on user growth?", the turn was bound to that exact subject with
        identity_status CONFIRMED, and the wake for that subject in that hour
        loaded nothing.

        `operator_conversation_turns` is where the binding actually lands, is the
        declared successor to `inbound_operator_questions`, and is keyed one row
        per message — so it is also the reverse map a reply needs.

        TWO THINGS THIS QUERY MUST NOT GET WRONG
        ----------------------------------------
        `role = 'operator'`: the table holds BOTH halves of the conversation, and
        the notifier now writes `role='agent'` rows for every alert. Without this
        filter the agent reads its own alerts back as operator input and treats
        what it said as what it was told.

        `id AS id`: the caller derives the source id as
        `str(turn.get("turn_id") or turn.get("id"))`. Return neither and it
        becomes the string "None" — and because receipt ids are a deterministic
        uuid5 over (agent_id, source_kind, source_id, purpose), every turn mints
        the SAME receipt id and the store dedupes them. N turns would collapse
        into one receipt naming a source that does not exist, silently.
        """
        return self._rows(
            """SELECT id, role, text AS sanitized_body, symbol, subject_guid,
                      occurred_at AS created_at
                 FROM operator_conversation_turns
                WHERE subject_guid = %s AND role = 'operator'
                ORDER BY occurred_at DESC LIMIT %s""",
            (str(subject_guid), int(limit)))


__all__ = ["DbCommsHistory", "AUTHORITY", "MBI"]
