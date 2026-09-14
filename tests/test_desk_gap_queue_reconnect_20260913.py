"""The operator desk queues its gaps for real, and says only what is true.

Before 2026-09-13 `_register_gaps` imported `advisory_gap_requeue`, a module that
never reached main, so every call registered 0 while the soft-gap note said
"queued for Trade-AI refresh". The data gap queue itself had no new row since
2026-05-24. The operator approved reconnecting the desk. These tests pin:

* only gaps the resolver has an action for are queued; book-level gaps are not
* the write goes through the store's write module, on one connection, committed
* no database, a disabled flag, or a failing write -> registered 0, error named
* the note names the queue rows and the resolver's next run, read from crontab
* a pending with an ETA stays open until the ETA plus grace, not a flat 2 h

Offline: fake connections, fake crontab text, a temp pending ledger.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import lib.cio_operator_desk_loop as desk  # noqa: E402


class FakeCursor:
    def __init__(self, fetchone=None, fail=False):
        self.calls = []
        self._one = list(fetchone or [])
        self.rowcount = 1
        self.fail = fail

    def execute(self, sql, params=None):
        if self.fail:
            raise RuntimeError("insert failed")
        self.calls.append((" ".join(str(sql).split()), params))

    def fetchone(self):
        return self._one.pop(0) if self._one else None


class FakeConn:
    def __init__(self, cur):
        self.cur, self.commits, self.rollbacks, self.closed = cur, 0, 0, False

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


GAPS = [
    {"domain": "reentry_decision_desk", "symbol": "SCHG", "field": "levels", "gap_type": "missing_market_data"},
    {"domain": "symbol_thesis", "symbol": "SPCX", "field": "thesis", "gap_type": "research"},
    {"domain": "cash_buying_power", "symbol": None, "field": "cash", "gap_type": "soft"},
    {"domain": "holdings_detail", "symbol": "ADBE", "field": "position", "gap_type": "soft"},
]

CRONTAB = """
# comment 0 9 * * * scripts/data_gap_resolver.py
0 10-16 * * 1-5 cd /x && .venv/bin/python scripts/data_gap_resolver.py >> logs/a.log 2>&1
0 18 * * 1-5 cd /x && .venv/bin/python scripts/data_gap_resolver.py --pre-overnight >> logs/b.log 2>&1
0 8 * * 0 cd /x && .venv/bin/python scripts/data_gap_resolver.py --weekly-audit >> logs/c.log 2>&1
*/5 * * * * cd /x && something_else.py
"""


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    ledger: list = []
    monkeypatch.setattr(desk, "_append_jsonl", lambda path, row: ledger.append((str(path), row)))
    monkeypatch.setattr(desk, "_gap_resolver_schedule", lambda: desk._resolver_cron_exprs(CRONTAB))
    monkeypatch.delenv("CIO_OPERATOR_GAP_REGISTRY", raising=False)
    return ledger


def test_only_gaps_with_a_resolver_action_are_mapped():
    assert [desk._registry_gap_type(g) for g in GAPS] == ["missing_market_data", "missing_thesis", None, None]
    assert desk._registry_gap_type({"domain": "hermes_research", "symbol": "NOC", "gap_type": "research"}) == "stale_news"
    assert desk._registry_gap_type({"domain": "hermes_research", "symbol": None, "gap_type": "research"}) is None


def test_register_gaps_writes_through_the_module_and_reports_ids(monkeypatch, _offline):
    cur = FakeCursor(fetchone=[None, (81,), (40,)])  # SCHG new -> 81; SPCX already open -> 40
    conn = FakeConn(cur)
    monkeypatch.setattr(desk, "_gap_registry_write_conn", lambda: conn)
    out = desk._register_gaps(GAPS, chat_id="c", pending_id="opr_x")
    assert out["registered"] == 2 and out["gap_ids"] == [81, 40] and out["not_registered"] == 2
    assert "error" not in out and conn.commits == 1 and conn.closed
    inserts = [c for c in cur.calls if c[0].startswith("INSERT INTO data_gap_registry")]
    assert len(inserts) == 1 and inserts[0][1][3] == "cio_operator_desk"
    assert out["receipt"]["table"] == "data_gap_registry"
    assert out["resolver_next_run"]
    ledger_row = _offline[-1][1]
    assert ledger_row["gap_ids"] == [81, 40] and ledger_row["registered"] == 2


def test_no_database_means_nothing_registered_and_the_reason_is_named(monkeypatch):
    monkeypatch.setattr(desk, "_gap_registry_write_conn", lambda: None)
    out = desk._register_gaps(GAPS, chat_id="c", pending_id="p")
    assert out["registered"] == 0 and "credentials" in out["error"] and out["resolver_next_run"] is None


def test_flag_off_writes_nothing(monkeypatch):
    monkeypatch.setenv("CIO_OPERATOR_GAP_REGISTRY", "0")
    monkeypatch.setattr(desk, "_gap_registry_write_conn", lambda: pytest.fail("must not connect"))
    out = desk._register_gaps(GAPS, chat_id="c", pending_id="p")
    assert out["registered"] == 0 and "disabled" in out["error"]


def test_a_failing_write_rolls_back_and_claims_nothing(monkeypatch):
    conn = FakeConn(FakeCursor(fail=True))
    monkeypatch.setattr(desk, "_gap_registry_write_conn", lambda: conn)
    out = desk._register_gaps(GAPS, chat_id="c", pending_id="p")
    assert out["registered"] == 0 and out["error"].startswith("RuntimeError") and conn.rollbacks == 1 and conn.closed


def test_book_level_gaps_never_open_a_connection(monkeypatch):
    monkeypatch.setattr(desk, "_gap_registry_write_conn", lambda: pytest.fail("must not connect"))
    out = desk._register_gaps([GAPS[2]], chat_id="c", pending_id="p")
    assert out["registered"] == 0 and out["not_registered"] == 1 and "error" not in out


def test_resolver_schedule_comes_from_the_crontab_lines_that_resolve():
    assert desk._resolver_cron_exprs(CRONTAB) == ["0 10-16 * * 1-5", "0 18 * * 1-5"]
    sat = datetime(2026, 9, 12, 20, 0).astimezone()
    nxt = desk._next_gap_resolver_run(sat)
    assert nxt is not None and (nxt.weekday(), nxt.hour, nxt.minute) == (0, 10, 0)


def test_queue_note_names_rows_and_run_time_or_promises_nothing():
    run = datetime(2026, 9, 14, 10, 0).astimezone().isoformat()
    note = desk._gap_queue_note({"gap_ids": [81, 40], "resolver_next_run": run})
    assert "#81" in note and "#40" in note and "Mon 10:00" in note
    assert "Ask again after that" in note
    bare = desk._gap_queue_note({"gap_ids": [81], "resolver_next_run": None})
    assert "no follow-up is promised" in bare


def test_pending_expiry_waits_for_the_eta_plus_grace(monkeypatch):
    assert desk._pending_expiry_hours({}) == desk.PENDING_EXPIRY_HOURS
    assert desk._pending_expiry_hours({"eta_seconds": 600}) == desk.PENDING_EXPIRY_HOURS
    assert desk._pending_expiry_hours({"eta_seconds": 6 * 3600}) == pytest.approx(7.0)
    monkeypatch.setenv("CIO_OPERATOR_PENDING_ETA_GRACE_HOURS", "0.5")
    assert desk._pending_expiry_hours({"eta_seconds": 6 * 3600}) == pytest.approx(6.5)


def _pending(tmp_path, *, age_h, eta_seconds=None):
    row = {
        "pending_id": "opr_eta", "status": "open", "chat_id": "c", "message_id": "m",
        "operator_text": "research SCHG", "intent": {"intent": "freeform", "symbols": ["SCHG"]},
        "ts": (datetime.now(timezone.utc) - timedelta(hours=age_h)).replace(microsecond=0).isoformat(),
    }
    if eta_seconds is not None:
        row["eta_seconds"] = eta_seconds
    path = tmp_path / "pending.jsonl"
    path.write_text(json.dumps(row) + "\n")
    return path


@pytest.mark.parametrize("eta_seconds,expect_expired", [(6 * 3600, 0), (None, 1)])
def test_fulfil_loop_keeps_a_pending_open_until_its_eta(monkeypatch, tmp_path, eta_seconds, expect_expired):
    path = _pending(tmp_path, age_h=3, eta_seconds=eta_seconds)
    monkeypatch.setattr(desk, "PENDING_PATH", path)
    monkeypatch.setattr(desk, "_append_jsonl", lambda p, row: open(p, "a").write(json.dumps(row) + "\n"))
    monkeypatch.setattr(desk, "gather_tradeai_evidence", lambda intent: {"complete": False, "sources": []})
    monkeypatch.setattr(desk, "is_answerable", lambda intent: (True, ""))
    sent: list = []
    res = desk.try_fulfill_pending_replies(lambda chat, body, mid: sent.append(body) or {"ok": True})
    assert res["expired"] == expect_expired
    assert len(sent) == expect_expired
