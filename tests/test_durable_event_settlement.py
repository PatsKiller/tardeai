"""Durable event settlement — settlement truth lives on communication_events.

Phase 3 (Grok-closure). The durable UPDATE lives in
``delivery._persist_event_settlement_pg`` (landed on main via 28902a51f); this
module's unique contribution is the provenance columns (source_sha + provenance)
written at INSERT and the additive migration that adds them.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.comms.delivery import _persist_event_settlement_pg  # noqa: E402


class FakeCursor:
    def __init__(self):
        self.statements = []
        self._rowcount = 1

    def execute(self, sql, params=None):
        self.statements.append({"sql": sql, "params": params})

    @property
    def rowcount(self):
        return self._rowcount


class FakeConn:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.committed = 0
        self.rolled_back = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        pass


def test_persist_event_settlement_pg_issues_durable_update(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr("db_adapter._get_conn", lambda: conn)
    _persist_event_settlement_pg(
        "evt-1",
        status="SENT",
        provider_message_id="tg-msg-42",
        settled_at=datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc),
        delivery_owner="gateway",
        gateway_mode="CANARY",
    )
    (stmt,) = conn.cursor_obj.statements
    assert "UPDATE communication_events" in stmt["sql"]
    assert "provider_message_id" in stmt["sql"]
    assert "provider_settlement_state" in stmt["sql"]
    assert "delivery_owner" in stmt["sql"]
    assert "gateway_mode_at_dispatch" in stmt["sql"]
    assert "WHERE event_id" in stmt["sql"]
    assert stmt["params"][0] == "tg-msg-42"
    assert stmt["params"][2] == "SETTLED"
    assert stmt["params"][5] == "evt-1"
    assert conn.committed == 1


def test_persist_event_settlement_pg_missing_id_noop(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr("db_adapter._get_conn", lambda: conn)
    _persist_event_settlement_pg("", status="SENT", provider_message_id="x", settled_at=None)
    assert conn.cursor_obj.statements == []


def test_persist_event_settlement_pg_failed_state(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr("db_adapter._get_conn", lambda: conn)
    _persist_event_settlement_pg("evt-2", status="FAILED", provider_message_id=None, settled_at=None)
    (stmt,) = conn.cursor_obj.statements
    assert stmt["params"][2] == "FAILED"


def test_persist_event_settlement_pg_legacy_state(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr("db_adapter._get_conn", lambda: conn)
    _persist_event_settlement_pg("evt-3", status="LEGACY_DELIVERED", provider_message_id=None, settled_at=None)
    (stmt,) = conn.cursor_obj.statements
    assert stmt["params"][2] == "UNKNOWN_LEGACY"


def test_insert_carries_settlement_and_provenance_columns():
    """The publish INSERT must carry the settlement + provenance columns."""
    text = (ROOT / "scripts" / "lib" / "comms" / "client.py").read_text()
    for col in (
        "provider_message_id",
        "provider_settled_at",
        "provider_settlement_state",
        "delivery_owner",
        "gateway_mode_at_dispatch",
        "curation_kind",
        "curation_provenance",
        "subject_guid",
        "source_sha",
        "provenance",
    ):
        assert col in text, f"INSERT missing durable column: {col}"


def test_provenance_migration_is_additive():
    up = (ROOT / "migrations" / "2026_09_10_communication_event_provenance.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS source_sha" in up
    assert "ADD COLUMN IF NOT EXISTS provenance" in up
    assert "DROP" not in up
