"""LQ-20261107-140 — the outcome linker drained one page a day and could never catch up.

ANCHOR: AGENT_OUTCOME_LINKER_BACKLOG_20261107

Live evidence (read-only, 2026-11-07): 1,086,356 unlinked (recommendation, proposal) pairs over 56,107
recommendations — 663,920 of them from July 2026 alone — while every weekday run stopped at the 1000+500
page cap (11-02..11-06: exactly 1500 links every day, `proposal_cap_hit`/`trade_cap_hit` both true). The
receipt said ok; nothing in it said the queue was a thousand days long.

These tests pin the new contract: an --apply run pages until both SELECTs come back short (drained) or its
budget is spent, the receipt says which, the backlog is counted per recommendation (cheap, index-backed),
and an unreadable backlog count is None — never a confident 0.

Hermetic: fake connections, no database, no network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_outcome_linker as aol  # noqa: E402


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 1
        self._rows, self._one = [], None

    def execute(self, sql, params=None):
        self.conn.sql.append(" ".join(sql.split()))
        if self.conn.raise_on and self.conn.raise_on in sql:
            raise RuntimeError("db failure")
        self._rows, self._one = self.conn.responder(" ".join(sql.split()), params)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._one

    def close(self):
        pass


class FakeConn:
    """Pages are served from a script: each entry is (proposal_rows, trade_rows); the last entry repeats."""

    def __init__(self, pages, backlog=(101, 7), raise_on=None):
        self.pages = list(pages)
        self.calls = 0
        self.sql = []
        self.backlog = backlog
        self.raise_on = raise_on
        self.rollbacks = 0

    def cursor(self, *a, **k):
        return FakeCursor(self)

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        pass

    def close(self):
        pass

    def proposal_rows(self, n):
        return [(f"R{self.calls}_{i}", "AAA", None, "maria", i, "swing", None) for i in range(n)]

    def trade_rows(self, n):
        return [(f"T{self.calls}_{i}", "BBB", None, "steph", i, "swing", None, "closed", 1, 0.5) for i in range(n)]

    def responder(self, sql, params):
        if "JOIN paper_trade_proposals" in sql:
            n_prop = self.pages[min(self.calls, len(self.pages) - 1)][0]
            self.calls += 1
            return self.proposal_rows(n_prop), None
        if "JOIN paper_trades" in sql:
            n_trade = self.pages[min(max(self.calls - 1, 0), len(self.pages) - 1)][1]
            return self.trade_rows(n_trade), None
        if "count(*)" in sql:
            key = "proposals" if "paper_trade_proposals p" in sql else "trades"
            value = self.backlog[0] if key == "proposals" else self.backlog[1]
            return [], (value,)
        return [], None


@pytest.fixture
def saved(monkeypatch):
    """save_links must never reach a real INSERT here: count the rows it was handed."""
    calls = []

    def _save(conn, links, dry_run=True):
        calls.append(len(links))
        return len(links)

    monkeypatch.setattr(aol, "save_links", _save)
    return calls


# --- the loop ----------------------------------------------------------------------------------------

def test_a_full_page_is_followed_by_another_page_until_the_queue_runs_short(saved):
    conn = FakeConn(pages=[(aol.PROPOSAL_LINK_LIMIT, 0), (40, 0)])
    out = aol._run_pages(conn, {"max_links": 50000, "max_seconds": 60.0})
    assert out["pages"] == 2
    assert out["total_links"] == aol.PROPOSAL_LINK_LIMIT + 40
    assert out["drained"] is True and out["budget_exhausted"] is False
    assert out["proposal_cap_hit"] is False and out["trade_cap_hit"] is False
    assert saved == [aol.PROPOSAL_LINK_LIMIT, 40]


def test_the_link_budget_stops_a_queue_that_never_runs_short(saved):
    conn = FakeConn(pages=[(aol.PROPOSAL_LINK_LIMIT, aol.TRADE_LINK_LIMIT)])
    out = aol._run_pages(conn, {"max_links": 2500, "max_seconds": 3600.0})
    # a page is proposals + trades (1500 here); the budget is checked after a page commits, so the run may end
    # one page past it — never a whole run past it
    assert out["pages"] == 2
    assert out["total_links"] == 2 * (aol.PROPOSAL_LINK_LIMIT + aol.TRADE_LINK_LIMIT)
    assert out["drained"] is False and out["budget_exhausted"] is True
    assert out["proposal_cap_hit"] is True and out["trade_cap_hit"] is True


def test_the_time_budget_stops_the_run_and_says_so(saved):
    ticks = iter([0.0, 0.0, 40.0, 80.0, 120.0, 160.0, 200.0, 240.0])
    conn = FakeConn(pages=[(aol.PROPOSAL_LINK_LIMIT, 0)])
    out = aol._run_pages(conn, {"max_links": 10**9, "max_seconds": 100.0}, clock=lambda: next(ticks))
    assert out["drained"] is False and out["budget_exhausted"] is True
    # the clock is read once at start and once per page: 0, 0, 40, 80 pass; 120 crosses the 100 s budget
    assert out["pages"] == 4


def test_an_empty_first_page_is_drained_and_touches_nothing(saved):
    conn = FakeConn(pages=[(0, 0)])
    out = aol._run_pages(conn, {"max_links": 100, "max_seconds": 10.0})
    assert out["pages"] == 1 and out["total_links"] == 0 and out["drained"] is True
    assert saved == []


# --- the backlog count -------------------------------------------------------------------------------

def test_backlog_counts_reads_both_tables():
    conn = FakeConn(pages=[(0, 0)], backlog=(50673, 12))
    assert aol.backlog_counts(conn) == {"proposals": 50673, "trades": 12}


def test_an_unreadable_backlog_is_unknown_not_zero():
    conn = FakeConn(pages=[(0, 0)], raise_on="agent_recommendation_registry")
    out = aol.backlog_counts(conn)
    assert out == {"proposals": None, "trades": None}
    assert conn.rollbacks == 2  # a failed statement aborts the transaction; each one is cleared


def test_a_missing_count_row_is_unknown_not_zero():
    conn = FakeConn(pages=[(0, 0)], backlog=(None, None))
    assert aol.backlog_counts(conn) == {"proposals": None, "trades": None}


# --- main() ------------------------------------------------------------------------------------------

class Receipt:
    def __init__(self):
        self.written = []

    def enforce_readonly(self, conn):
        pass

    def dry_run_report(self, lane_id, summary, would_write=None):
        return {"lane_id": lane_id, "summary": summary, "would_write": would_write}

    def write_lane_receipt(self, lane_id, **kw):
        self.written.append((lane_id, kw))


@pytest.fixture
def wired(monkeypatch):
    rec = Receipt()
    monkeypatch.setattr(aol, "_receipt_lib", lambda: rec)
    return rec


def test_a_dry_run_reads_one_page_and_never_writes(monkeypatch, wired, saved, capsys):
    conn = FakeConn(pages=[(aol.PROPOSAL_LINK_LIMIT, aol.TRADE_LINK_LIMIT)], backlog=(999, 3))
    monkeypatch.setattr(aol, "_get_conn", lambda: conn)
    monkeypatch.setattr(sys, "argv", ["x", "--apply", "--dry-run", "--json"])
    assert aol.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pages"] == 1 and out["inserted"] == 0
    assert out["would_insert"] == aol.PROPOSAL_LINK_LIMIT + aol.TRADE_LINK_LIMIT
    assert saved == []  # save_links is unreachable from a dry run
    assert out["backlog_recommendations"] == {"proposals": 999, "trades": 3}


def test_an_apply_run_records_the_budget_and_the_backlog_in_its_receipt(monkeypatch, wired, saved):
    conn = FakeConn(pages=[(10, 2)], backlog=(500, 4))
    monkeypatch.setattr(aol, "_get_conn", lambda: conn)
    monkeypatch.setattr(sys, "argv", ["x", "--apply", "--max-links", "777", "--max-seconds", "42", "--json"])
    assert aol.main() == 0
    summary = wired.written[-1][1]["summary"]
    assert summary["drained"] is True and summary["inserted"] == 12
    assert summary["budget"] == {"max_links": 777, "max_seconds": 42.0}
    assert summary["backlog_recommendations"] == {"proposals": 500, "trades": 4}


def test_a_budget_that_is_nonsense_cannot_become_an_unbounded_run(monkeypatch, wired, saved, capsys):
    conn = FakeConn(pages=[(10, 0)])
    monkeypatch.setattr(aol, "_get_conn", lambda: conn)
    monkeypatch.setattr(sys, "argv", ["x", "--apply", "--max-links", "0", "--max-seconds", "-5", "--json"])
    assert aol.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["budget"] == {"max_links": 1, "max_seconds": 1.0}
