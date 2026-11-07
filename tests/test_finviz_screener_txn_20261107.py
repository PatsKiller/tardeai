"""LQ-20261107-129 — a screener's writes must be committed before the next fetch refreshes the handle.

Live evidence, 2026-11-07 (read-only):

  finviz_screeners: 45 active, last_run 2026-08-27 x 38, 2026-08-26 x 3, 2026-11-06 x 4
  screener_symbol_membership: 49 screeners, only 4 with any row newer than 2026-08-27
  run receipt 2026-11-05: {"screeners_run": 45, "total_new_tickers": 2062,
                           "membership_failures": 0, "db_write_failures": 0} — status ok

A run cannot report 2062 new tickers and 45 screeners run while 41 of them keep an August stamp. The
mechanism is in the loop: every screener's writes are made inside a SAVEPOINT, the SAVEPOINT is
RELEASED (which keeps them in the enclosing transaction), and the loop calls

    conn = _refresh_conn(conn)          # scripts/finviz_screener_runner.py, after each HTTP fetch

which is `db_adapter.ensure_conn()`, and that helper probes the live handle and then, on purpose,

    cur.execute("SELECT 1")
    conn.rollback()                     # scripts/db_adapter.py:283-284

so every screener's still-uncommitted work is discarded at the next screener's fetch, and the single
`conn.commit()` after the loop persists only the LAST screener — or nothing at all when the last
screener returned no rows. The run then reports ok, 0 db_write_failures, and a total_new that counts
work the database never received. The same single commit is why the 11-06 run that was killed at
1233 s (`executor_lost`) left nothing behind.

The contract these tests pin:

  1. each screener's writes reach the database before the next screener's fetch can refresh
     (roll back) the connection — the per-screener unit of isolation the savepoints already claim;
  2. the summary counts only what the database actually took: a screener whose commit failed is
     `db_ok: False`, counted in `db_write_failures`, and its tickers are not counted as new;
  3. a failure is not reported as success.

Hermetic: fake connection that models commit/rollback/SAVEPOINT semantics; fake Finviz fetcher.
No DB, no network, no credential read.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import db_adapter  # noqa: E402
import finviz_screener_runner as runner  # noqa: E402

SCREENERS = [
    {"screener_id": "aaa_setups", "display_name": "A", "strategy_type": "core", "finviz_url": "u1"},
    {"screener_id": "bbb_value", "display_name": "B", "strategy_type": "value", "finviz_url": "u2"},
    {"screener_id": "ccc_income", "display_name": "C", "strategy_type": "income", "finviz_url": "u3"},
]
TICKERS = {"u1": ["AAA1", "AAA2"], "u2": ["BBB1"], "u3": ["CCC1", "CCC2"]}


class _Cur:
    """Models the transaction structure the runner uses; nothing else."""

    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        s = " ".join(str(sql).split())
        u = s.upper()
        if u.startswith("SAVEPOINT "):
            self.conn.saves.append((s.split()[1], len(self.conn.pending)))
            return
        if u.startswith("RELEASE SAVEPOINT "):
            name = s.split()[-1]
            for i in range(len(self.conn.saves) - 1, -1, -1):
                if self.conn.saves[i][0] == name:
                    del self.conn.saves[i]
                    break
            return
        if u.startswith("ROLLBACK TO SAVEPOINT "):
            name = s.split()[-1]
            for i in range(len(self.conn.saves) - 1, -1, -1):
                if self.conn.saves[i][0] == name:
                    depth = self.conn.saves[i][1]
                    del self.conn.pending[depth:]
                    del self.conn.saves[i + 1:]
                    break
            return
        if u.startswith("SELECT * FROM FINVIZ_SCREENERS"):
            self._rows = [dict(r) for r in self.conn.screeners]
            return
        if u.startswith("SELECT SYMBOL FROM TICKER_STRATEGY_CLASSIFICATIONS"):
            self._rows = []
            return
        self.conn.pending.append((s, params))     # every other statement is a write

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class _Conn:
    def __init__(self, screeners, fail_commit_on=None):
        self.screeners = screeners
        self.pending, self.committed, self.saves = [], [], []
        self.commits, self.rollbacks = 0, 0
        self.fail_commit_on = fail_commit_on     # 1-based commit call that raises

    def cursor(self, *a, **k):
        return _Cur(self)

    def commit(self):
        self.commits += 1
        if self.fail_commit_on == self.commits:
            self.pending.clear()
            self.saves.clear()
            raise RuntimeError("server closed the connection unexpectedly")
        self.committed.extend(self.pending)
        self.pending.clear()
        self.saves.clear()

    def rollback(self):
        self.rollbacks += 1
        self.pending.clear()
        self.saves.clear()

    def get_transaction_status(self):
        return 2                                  # psycopg2 TRANSACTION_STATUS_READY


def _stamps(conn):
    """The screeners whose last_run UPDATE reached the database."""
    return [p[1] for s, p in conn.committed if s.startswith("UPDATE finviz_screeners SET last_run")]


def _classified(conn):
    """The tickers whose classification INSERT reached the database."""
    return [p[0] for s, p in conn.committed if s.startswith("INSERT INTO ticker_strategy_classifications")]


@pytest.fixture
def env(monkeypatch):
    def use(conn, tickers=None):
        monkeypatch.setattr(runner, "_get_conn", lambda: conn)
        # db_adapter.ensure_conn() on a live handle runs SELECT 1 and then conn.rollback(); this is the
        # behaviour the runner refreshes through, modelled rather than mocked away.
        def _ensure():
            conn.rollback()
            return conn
        monkeypatch.setattr(db_adapter, "ensure_conn", _ensure)
        table = TICKERS if tickers is None else tickers
        monkeypatch.setattr(runner, "_fetch_screener_tickers",
                            lambda url, cookie, token="", *, deadline_monotonic=None: list(table.get(url, [])))
        monkeypatch.setattr(runner, "_update_screener_membership",
                            lambda cur, sid, present, run_id: _membership(cur, sid, present))
        monkeypatch.setattr(runner, "_get_finviz_cookie", lambda: "")
        monkeypatch.setattr(runner, "_get_finviz_token", lambda: "")
        monkeypatch.setattr(runner, "_fence_before_first_write", lambda: None)
        monkeypatch.setattr(runner.time, "sleep", lambda _s: None)
        return conn
    return use


def _membership(cur, sid, present):
    cur.execute("INSERT INTO screener_symbol_membership (symbol, screener_id) VALUES (%s, %s)",
                (sorted(present)[0] if present else None, sid))
    return len(present)


def test_every_screener_is_committed_before_the_next_fetch_refreshes_the_handle(env):
    """Three screeners fetch in a row. Each fetch refreshes through ensure_conn → rollback. All three
    stamps must be in the database, not just the last one."""
    conn = _Conn(SCREENERS)
    env(conn)
    out = runner.run_screener()

    assert out["screeners_run"] == 3
    assert _stamps(conn) == ["aaa_setups", "bbb_value", "ccc_income"], (
        f"only {_stamps(conn)} reached the database: the refresh between screeners rolled the rest back")


def test_the_summary_counts_only_what_the_database_took(env):
    """total_new_tickers is what landed, not what was attempted: 5 inserts, 5 committed."""
    conn = _Conn(SCREENERS)
    env(conn)
    out = runner.run_screener()

    assert out["total_new_tickers"] == 5
    assert len(_classified(conn)) == 5, (
        f"summary says {out['total_new_tickers']} new tickers, database has {len(_classified(conn))}")
    assert out["db_write_failures"] == 0


def test_a_failed_commit_is_reported_on_that_screener_and_its_tickers_are_not_counted(env):
    """The second screener's commit fails: it is db_ok False, counted as a write failure, its tickers
    are not counted as new (they never landed), and the first and third are unaffected."""
    conn = _Conn(SCREENERS, fail_commit_on=2)
    env(conn)
    out = runner.run_screener()

    assert out["db_write_failures"] == 1, out
    by_id = {r["screener_id"]: r for r in out["results"]}
    assert by_id["bbb_value"]["db_ok"] is False
    assert by_id["aaa_setups"]["db_ok"] is True and by_id["ccc_income"]["db_ok"] is True
    assert _stamps(conn) == ["aaa_setups", "ccc_income"], _stamps(conn)
    assert out["total_new_tickers"] == 4, (out["total_new_tickers"], _classified(conn))
    assert "BBB1" not in _classified(conn)


def test_a_screener_that_returns_nothing_does_not_hide_the_previous_ones(env):
    """The last screener of the run returns no rows (the live case: 45 screeners, empty tail). The
    earlier screeners' stamps must still be in the database."""
    tickers = {"u1": ["AAA1"], "u2": ["BBB1"], "u3": []}
    conn = _Conn(SCREENERS)
    env(conn, tickers)
    out = runner.run_screener()

    assert out["screeners_run"] == 3
    assert _stamps(conn) == ["aaa_setups", "bbb_value"], _stamps(conn)
    assert out["total_new_tickers"] == 2
