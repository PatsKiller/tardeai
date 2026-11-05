"""FQ-143: receipts land in the durable outbox, with a status the table actually accepts.

No database: the connection is a fake that records each statement, so the test proves the SQL that would run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import critical_receipts as CR  # noqa: E402


class FakeCursor:
    def __init__(self, owner):
        self.owner = owner
        self._rows = []

    def execute(self, sql, params=()):
        self.owner.executed.append((sql, params))
        if sql.startswith("SELECT"):
            self._rows = self.owner.rows

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class FakeConn:
    def __init__(self, rows=None):
        self.executed = []
        self.rows = rows or []
        self.committed = 0
        self.rolled = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled += 1


RECEIPTS = [
    {"channel": "telegram_critical", "status": "sent", "reason": None, "provider_receipt": "tg-42"},
    {"channel": "email", "status": "failed", "reason": "RuntimeError", "provider_receipt": None},
    {"channel": "text_gateway", "status": "skipped", "reason": "class_not_enabled_for_text", "provider_receipt": None},
]


def test_every_channel_gets_a_row():
    conn = FakeConn()
    out = CR.record("evt-1", RECEIPTS, conn=conn)
    assert out["ok"] is True and out["written"] == 3
    channels = [params[3] for _sql, params in conn.executed]
    assert channels == ["telegram_critical", "email", "text_gateway"]
    assert conn.committed == 1


def test_a_skipped_channel_is_stored_as_suppressed_because_the_table_says_so():
    """The CHECK constraint has no 'skipped'; writing it would lose the row, and a lost receipt is worse than a rough one."""
    conn = FakeConn()
    CR.record("evt-1", RECEIPTS, conn=conn)
    skipped = conn.executed[2][1]
    assert skipped[4] == "suppressed" and skipped[5] == "class_not_enabled_for_text"
    assert skipped[4] in CR.ALLOWED_STATUSES


def test_every_written_status_is_one_the_column_accepts():
    conn = FakeConn()
    CR.record("evt-1", RECEIPTS, conn=conn)
    for _sql, params in conn.executed:
        assert params[4] in CR.ALLOWED_STATUSES, params


def test_no_durable_store_is_reported_rather_than_silently_dropped():
    out = CR.record("evt-1", RECEIPTS, connect=lambda: None)
    assert out["ok"] is False and out["outcome"] == CR.NO_STORE and out["written"] == 0


def test_an_unknown_receipt_status_is_refused_before_any_write():
    conn = FakeConn()
    with pytest.raises(CR.ReceiptError) as exc:
        CR.record("evt-1", [{"channel": "email", "status": "probably"}], conn=conn)
    assert str(exc.value) == "unknown_receipt_status"
    assert conn.executed == [], "nothing may be written when one receipt is unrecognised"


def test_receipts_read_back_per_channel():
    conn = FakeConn(rows=[("telegram_critical", "sent", None, "tg-42", "2026-11-05T03:00:00Z"),
                          ("email", "failed", "RuntimeError", None, "2026-11-05T03:00:01Z")])
    rows = CR.for_alert("evt-1", conn=conn)
    assert [r["channel"] for r in rows] == ["telegram_critical", "email"]
    assert CR.confirmed(rows) is True


def test_delivered_means_at_least_one_confirmed_and_a_skip_is_not_one():
    assert CR.confirmed([{"channel": "email", "status": "suppressed"}]) is False
    assert CR.confirmed([{"channel": "email", "status": "failed"},
                         {"channel": "text_gateway", "status": "sent"}]) is True


def test_an_empty_receipt_list_writes_nothing_and_is_not_an_error():
    out = CR.record("evt-1", [], conn=FakeConn())
    assert out["ok"] is True and out["written"] == 0
