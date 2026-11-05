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


def _by_column(sql: str, params) -> dict:
    """Map column name -> bound value, so a test never depends on the position of a column in the insert."""
    import re

    columns = [c.strip() for c in re.search(r"\((.*?)\)\s*VALUES", sql, re.S).group(1).split(",") if c.strip()]
    return dict(zip(columns, params))


def test_every_channel_gets_a_row():
    conn = FakeConn()
    out = CR.record("evt-1", RECEIPTS, conn=conn)
    assert out["ok"] is True and out["written"] == 3
    channels = [_by_column(sql, params)['channel'] for sql, params in conn.executed]
    assert channels == ["telegram_critical", "email", "text_gateway"]
    assert conn.committed == 1


def test_a_skipped_channel_is_stored_as_suppressed_because_the_table_says_so():
    """The CHECK constraint has no 'skipped'; writing it would lose the row, and a lost receipt is worse than a rough one."""
    conn = FakeConn()
    CR.record("evt-1", RECEIPTS, conn=conn)
    sql, params = conn.executed[2]
    skipped = _by_column(sql, params)
    assert skipped["delivery_status"] == "suppressed" and skipped["delivery_reason"] == "class_not_enabled_for_text"
    assert skipped["delivery_status"] in CR.ALLOWED_STATUSES


def test_every_written_status_is_one_the_column_accepts():
    conn = FakeConn()
    CR.record("evt-1", RECEIPTS, conn=conn)
    for sql, params in conn.executed:
        assert _by_column(sql, params)["delivery_status"] in CR.ALLOWED_STATUSES, params


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


def test_the_occurrence_is_passed_through_when_a_caller_knows_it():
    conn = FakeConn()
    CR.record("evt-1", RECEIPTS[:1], conn=conn, occurrence_id=77)
    assert _by_column(*conn.executed[0])["occurrence_id"] == 77


def test_a_multi_channel_set_writes_no_occurrence_because_the_table_allows_only_one_sent_row():
    """Review finding F2 on PR 2680, answered with the DDL rather than a shrug.

    `alert_deliveries_one_sent_per_occurrence_uq` is UNIQUE (occurrence_id) WHERE delivery_status='sent', and the table
    carries UNIQUE (occurrence_id, attempt_seq). A CRITICAL event sends three channels, so binding an occurrence here
    would raise on the second channel and again on the third. The column stays NULL and the channel identity lives in
    `channel`; the invariant that would help — one SENT per (occurrence, channel) — is an outbox schema change for the
    operator, not something this writer may do.
    """
    ddl = (ROOT / "migrations/2026_07_28_alert_notification_outbox.sql").read_text(encoding="utf-8")
    index = ddl.split("alert_deliveries_one_sent_per_occurrence_uq", 1)[1].split(";", 1)[0]
    assert "ON alert_notification_deliveries (occurrence_id)" in index and "delivery_status = 'sent'" in index, index
    assert "UNIQUE (occurrence_id, attempt_seq)" in ddl

    conn = FakeConn()
    CR.record("evt-1", RECEIPTS, conn=conn)
    for sql, params in conn.executed:
        assert _by_column(sql, params)["occurrence_id"] is None


def test_every_not_null_column_without_a_default_is_bound_by_the_insert():
    """The fake connection cannot see the schema — that is how `route_mode` was missed.

    Real defect, caught by review on a throwaway Postgres: `alert_notification_deliveries.route_mode` is NOT NULL with no
    default, and the insert did not name it, so every write would have raised. This reads the migration itself and requires
    the insert to bind every column the table refuses to default.
    """
    import re

    ddl = (ROOT / "migrations/2026_07_28_alert_notification_outbox.sql").read_text(encoding="utf-8")
    block = re.search(r"CREATE TABLE IF NOT EXISTS alert_notification_deliveries \((.*?)\n\);", ddl, re.S)
    assert block, "the delivery table DDL was not found"
    required = []
    for line in block.group(1).splitlines():
        text = line.strip().rstrip(",")
        if not text or text.startswith("--") or text.upper().startswith(("UNIQUE", "PRIMARY", "FOREIGN")):
            continue
        if "NOT NULL" in text.upper() and "DEFAULT" not in text.upper():
            required.append(text.split()[0])
    assert "route_mode" in required, required  # the column that was missed must be in the check's own scope

    conn = FakeConn()
    CR.record("evt-1", RECEIPTS, conn=conn)
    sql, params = conn.executed[0]
    columns = re.search(r"\((.*?)\)\s*VALUES", sql, re.S).group(1)
    named = {c.strip() for c in columns.split(",")}
    missing = [c for c in required if c not in named]
    assert not missing, f"insert does not bind NOT NULL columns without defaults: {missing}"
    assert len(params) == len([c for c in columns.split(",") if c.strip()])
