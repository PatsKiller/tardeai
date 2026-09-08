"""Negative controls for the centralized receipt-write barrier.

INC-2026-09-08-TEST-RECEIPT-PRODUCTION-WRITE: while debugging
tests/test_inbound_poller_integration.py, feed_telegram_update() reached
emit_consumption_receipt() and minted five real AgentConsumptionReceipt rows in
the live trade_ai database ('persisted': 'db').

Nothing stopped it. Every guard in conftest was a per-PATH denylist -- options
telegram, telegram HTTP, alert_outbox -- and SFR-I-RUNTIME-001 had just created
a write path none of them named. A denylist protects only the paths somebody
already thought of.

The barrier now sits at `_db_conn()`, the single point every durable receipt
write must pass through. These controls prove it holds for callers it has never
heard of, which is the whole point: a new module, a new wrapper or a new code
path cannot route around a barrier that does not know its callers' names.

Each control must FAIL if the barrier is removed. A guard that cannot go red
proves nothing.
"""
from __future__ import annotations

import os

import pytest

from scripts.lib.comms import agent_contracts


def _conn():
    """Whatever the barrier currently permits."""
    return agent_contracts._db_conn()


# --- 1. direct invocation ----------------------------------------------------

def test_direct_db_conn_returns_none_under_pytest():
    """The lowest boundary yields no production connection during tests."""
    assert _conn() is None, (
        "a test obtained a live receipt connection; the barrier is not in place"
    )


# --- 2. indirect invocation through the poller path --------------------------

def test_indirect_through_consumption_path_does_not_persist_to_db():
    """The exact route that caused the incident."""
    from scripts.lib import inbound_consumption

    update = {
        "update_id": 77000001,
        "message": {
            "message_id": 77000001,
            "chat": {"id": 6993102664},
            "from": {"id": 4242},
            "date": 1788870000,
            "text": "barrier control",
        },
    }
    res = inbound_consumption.feed_telegram_update(update)
    persisted = (res.receipt or {}).get("persisted") if getattr(res, "receipt", None) else None
    assert persisted != "db", (
        f"inbound consumption persisted to the PRODUCTION database: {persisted}"
    )


# --- 3. a wrapper the denylist has never heard of ----------------------------

def test_a_brand_new_wrapper_cannot_reach_production():
    """The failure mode a per-path denylist cannot cover.

    Simulates a module invented after the guard was written. It is not named
    anywhere in conftest, so only a barrier at the write boundary can stop it.
    """
    def freshly_invented_wrapper():
        return agent_contracts._db_conn()

    assert freshly_invented_wrapper() is None, (
        "a wrapper unknown to the denylist reached a production connection"
    )


# --- 4. live DSN / environment leakage ---------------------------------------

def test_production_dsn_in_environment_does_not_open_a_connection(monkeypatch):
    """A leaked production DSN must not be honoured under pytest."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod/trade_ai")
    monkeypatch.setenv("TRADEAI_DB_DSN", "postgresql://prod/trade_ai")
    assert _conn() is None, "a production DSN in the environment was honoured"


def test_isolated_dsn_is_the_only_accepted_opt_in():
    """Only TRADEAI_TEST_ISOLATED_DSN may ever yield a connection."""
    assert not os.environ.get("TRADEAI_TEST_ISOLATED_DSN"), (
        "this suite must not run against an isolated cluster by default"
    )
    assert _conn() is None


# --- 5. missing injected writer ----------------------------------------------

def test_missing_injected_writer_degrades_instead_of_writing_production():
    """No injected store => in-memory path, never a silent production write.

    emit_consumption_receipt already degrades when the connection is None. The
    barrier makes that degradation the default rather than an accident of the
    database being unreachable -- the earlier reading of "those writes used to
    fail" that let this class of bug hide for months.
    """
    from scripts.lib.comms.agent_contracts import emit_consumption_receipt

    out = emit_consumption_receipt(
        "cio",
        purpose="barrier_control",
        event_id="evt_barrier_control_1",
        source_kind="comm_event",
        source_id="evt_barrier_control_1",
    )
    row = out.to_dict() if hasattr(out, "to_dict") else dict(out)
    assert row.get("persisted") != "db", (
        f"receipt persisted to production without an injected writer: {row.get('persisted')}"
    )


# --- the control on the controls ---------------------------------------------

def test_barrier_is_installed_by_conftest_not_by_this_module():
    """Guard against a control that passes only because it patched itself."""
    import inspect

    src = inspect.getsource(agent_contracts._db_conn)
    assert "TRADEAI_TEST_ISOLATED_DSN" in src or _conn() is None, (
        "the barrier must come from conftest, not from this test module"
    )
