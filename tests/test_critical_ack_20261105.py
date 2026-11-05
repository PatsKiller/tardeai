"""FQ-143: one acknowledgement stops the repeats, and says so honestly when it could not.

No database is touched: the connection is a fake that records the SQL it is given, so the test proves the statement that
would run without ever running it.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import critical_ack as A  # noqa: E402


class FakeCursor:
    def __init__(self, owner):
        self.owner = owner
        self.rowcount = 0
        self._select = None

    def execute(self, sql, params=()):
        self.owner.executed.append((sql, params))
        if sql.startswith("UPDATE"):
            # a row that does not exist cannot be updated, whatever its acknowledgement state
            self.rowcount = 1 if (self.owner.exists and self.owner.unacked) else 0
            if self.rowcount:
                self.owner.unacked = False
                self.owner.who = params[1]
                self.owner.at = params[0]
        else:
            self._select = (self.owner.at, self.owner.who) if self.owner.exists else None

    def fetchone(self):
        return self._select

    def close(self):
        pass


class FakeConn:
    def __init__(self, *, exists=True, unacked=True):
        self.executed = []
        self.committed = 0
        self.rolled = 0
        self.exists = exists
        self.unacked = unacked
        self.who = None
        self.at = None

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled += 1


NOW = datetime(2026, 11, 5, 3, 10, tzinfo=timezone.utc)


def test_the_first_acknowledgement_writes_who_and_when():
    conn = FakeConn()
    out = A.acknowledge("inc-1", "operator", conn=conn, now=NOW)
    assert out["outcome"] == A.ACKED and out["ok"] is True
    assert conn.committed == 1 and conn.who == "operator" and conn.at == NOW


def test_the_second_acknowledgement_does_not_rewrite_the_first():
    conn = FakeConn(unacked=False)
    out = A.acknowledge("inc-1", "someone-else", conn=conn, now=NOW)
    assert out["outcome"] == A.ALREADY
    assert out["acknowledged_by"] == "operator" or out["acknowledged_by"] == conn.who
    assert conn.committed == 0, "a losing ack must never commit"


def test_the_statement_only_claims_an_unacknowledged_row():
    conn = FakeConn()
    A.acknowledge("inc-1", "operator", conn=conn, now=NOW)
    sql = conn.executed[0][0]
    assert "acknowledged_at IS NULL" in sql, "the WHERE clause is what makes two racing acks safe"


def test_an_unknown_incident_is_reported_not_invented():
    conn = FakeConn(exists=False)
    out = A.acknowledge("nope", "operator", conn=conn)
    assert out["ok"] is False and out["outcome"] == A.NOT_FOUND


def test_no_durable_store_is_reported_rather_than_success():
    """A fallback store nobody reads would leave the repeats running while the operator believed they had stopped."""
    out = A.acknowledge("inc-1", "operator", connect=lambda: None)
    assert out["ok"] is False and out["outcome"] == A.NO_STORE


def test_an_ack_without_an_author_is_refused():
    with pytest.raises(A.AckError) as exc:
        A.acknowledge("inc-1", "   ")
    assert str(exc.value) == "acknowledger_required"
    with pytest.raises(A.AckError) as exc:
        A.acknowledge("", "operator")
    assert str(exc.value) == "incident_id_required"


def test_the_reader_rule_matches_the_writer():
    assert A.stops_repeats({"acknowledged_at": NOW}) is True
    assert A.stops_repeats({"acknowledged_at": None}) is False
    assert A.stops_repeats({}) is False
