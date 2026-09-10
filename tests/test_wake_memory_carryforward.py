"""Phase 5: the wake must load what it already knows before it decides.

Across 24 organic wakes on 2026-09-10, memory_fact_ids, prior_comm_event_ids,
prior_operator_turn_ids and parent_id were non-empty on ZERO. Not because the
engine lacked the code -- persistent_agent_wake has always populated those
fields -- but because production plugged nothing into the ports:

    run_scheduled_wake(memory_backend=None, comms=None)
      -> MemoryLoader(None)      loads nothing
      -> NullCommsHistory()      returns nothing

So the agent re-raised subjects it had messaged about an hour earlier with no
idea it had done so. Nothing was missing but the plug.
"""
from __future__ import annotations

from scripts.lib.wake_comms_history import DbCommsHistory


class _Conn:
    def __init__(self, rows):
        self._rows = rows
        self.sql = []

    def cursor(self):
        return self

    @property
    def description(self):
        return [("event_id",), ("event_type",), ("direction",),
                ("sanitized_body",), ("created_at",)]

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchall(self):
        return self._rows


def test_prior_comm_events_returns_what_the_desk_already_said():
    conn = _Conn([("e1", "operator_message", "OUTBOUND", "AES catalyst", "t0")])
    got = DbCommsHistory(conn_factory=lambda: conn).prior_comm_events("guid-1")
    assert got and got[0]["event_id"] == "e1"
    assert "OUTBOUND" in conn.sql[0][0]


def test_operator_turns_are_inbound_only():
    conn = _Conn([])
    DbCommsHistory(conn_factory=lambda: conn).prior_operator_turns("guid-1")
    sql = conn.sql[0][0]
    assert "INBOUND" in sql and "event_type = ANY" in sql


def test_history_filters_by_subject_guid_not_by_symbol():
    """Symbol-keyed history was the original defect in durable memory: '441 live
    records carried symbols, none carried a subject_guid'. Do not repeat it."""
    conn = _Conn([])
    DbCommsHistory(conn_factory=lambda: conn).prior_comm_events("guid-xyz")
    assert conn.sql[0][1][0] == "guid-xyz"
    assert "subject_guid = %s" in conn.sql[0][0]


# --- degradation --------------------------------------------------------------

def test_an_unavailable_db_is_EMPTY_not_an_exception():
    """No history is a legitimate state -- a subject genuinely new to the desk.
    Conflating that with a broken read would make every wake flaky."""
    def boom():
        raise RuntimeError("db down")

    port = DbCommsHistory(conn_factory=boom)
    assert port.prior_comm_events("g") == []
    assert port.prior_operator_turns("g") == []


def test_a_none_connection_is_empty_not_a_crash():
    port = DbCommsHistory(conn_factory=lambda: None)
    assert port.prior_comm_events("g") == []


# --- the runner actually plugs them in ----------------------------------------

def test_the_runner_passes_a_comms_port():
    import inspect

    import scripts.run_persistent_wake as rpw

    src = inspect.getsource(rpw)
    assert "comms=comms_history()" in src, (
        "the runner stopped passing a comms port; the engine falls back to "
        "NullCommsHistory and prior_comm_event_ids goes empty again"
    )


def test_the_runner_defaults_memory_to_the_durable_store():
    import inspect

    import scripts.run_persistent_wake as rpw

    src = inspect.getsource(rpw)
    assert "agent_durable_memory" in src and "default_store_path" in src, (
        "memory_backend fell back to None; MemoryLoader(None) loads nothing and "
        "memory_fact_ids goes empty again"
    )
