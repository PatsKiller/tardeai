"""LQ-20261107-2592 -- route() held a FOR UPDATE transaction across a <=300 s researcher subprocess.

The trade_ai role terminates a session idle in a transaction after 120 s; the next statement then raised
``psycopg2.InterfaceError: cursor already closed`` and the 17:00 and 17:20 ET 2026-11-12 runs were
RUN_FAILED. Synthetic fake connection/cursor: no database, no network, no model call.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

ddq = pytest.importorskip("due_diligence_questions")
researcher = pytest.importorskip("hermes_external_researcher")


class Conn:
    def __init__(self, log, rows=None, researched=True):
        self.log, self.rows, self.researched = log, rows or [], researched
        self.open_txn = False
        self.dead = False

    def cursor(self):
        return Cur(self)

    def commit(self):
        self.open_txn = False
        self.log.append("commit")

    def rollback(self):
        self.open_txn = False

    def close(self):
        pass


class Cur:
    def __init__(self, conn):
        self.connection = self._c = conn
        self._next = None

    def execute(self, sql, params=None):
        c = self._c
        if c.dead:
            raise RuntimeError("cursor already closed")
        c.open_txn = True
        c.log.append(("sql", " ".join(sql.split())[:60], params))
        self._next = None
        if "FOR UPDATE" in sql:
            self._next = list(c.rows)
        elif "SELECT id FROM hermes_external_research" in sql:
            self._next = [(1,)] if c.researched else []

    def fetchall(self):
        return self._next

    def fetchone(self):
        return (self._next or [None])[0]


class Proc:
    def __init__(self, rc=0):
        self.returncode, self.stderr = rc, ""


@pytest.fixture
def env(monkeypatch):
    log = []
    conn = Conn(log, rows=[("g1", "AAA", "q one"), ("g2", "BBB", "q two")])
    monkeypatch.setattr(ddq, "rank_research_lanes", lambda cur: [("grok", 0.9, 0.9)])
    monkeypatch.setattr(ddq, "via_bridge", lambda: False)
    state = {"open_at_spawn": [], "kill": False, "fresh": []}

    def run(cmd, **kw):
        state["open_at_spawn"].append(conn.open_txn)
        if state["kill"]:
            conn.dead = True  # the server terminated the idle session
        return Proc(0)

    monkeypatch.setattr(ddq.subprocess, "run", run)

    def fresh():
        n = Conn(log, rows=[], researched=True)
        state["fresh"].append(n)
        return n

    monkeypatch.setattr(ddq, "_db", fresh)
    return conn, log, state


def test_no_transaction_is_open_while_the_researcher_runs(env):
    conn, log, state = env
    out = ddq.route(conn.cursor(), 2)
    assert state["open_at_spawn"] == [False, False]
    assert out["routed"] == 2


def test_selected_questions_are_claimed_and_committed_before_the_first_call(env):
    conn, log, state = env
    ddq.route(conn.cursor(), 2)
    first_spawn_idx = next(i for i, e in enumerate(log) if e == "commit")
    claim = [e for e in log[:first_spawn_idx] if isinstance(e, tuple) and "SET routed_at = now()" in e[1]]
    assert claim and claim[0][2] == (["g1", "g2"],)


def test_select_admits_an_expired_claim_lease(env):
    conn, log, state = env
    ddq.route(conn.cursor(), 2)
    sql_params = [e for e in log if isinstance(e, tuple)][0]
    assert sql_params[2] == (ddq.ROUTE_LEASE_S, 2)


def test_a_session_killed_during_the_call_is_replaced_not_fatal(env):
    conn, log, state = env
    state["kill"] = True
    out = ddq.route(conn.cursor(), 2)
    assert out["routed"] == 2 and out["failed"] == 0
    new_conn, new_cur = out["_db"]
    assert new_conn in state["fresh"] and new_conn is not conn


def test_a_failed_question_releases_its_claim(env):
    conn, log, state = env
    conn.researched = False  # exit 0, no stored row -> the chain stops, question stays ASKED
    out = ddq.route(conn.cursor(), 2)
    assert out["failed"] == 2
    rel = [e for e in log if isinstance(e, tuple) and "routed_at = NULL" in e[1]]
    assert [r[2] for r in rel] == [("g1",), ("g2",)]
    assert not conn.open_txn


def test_no_ranked_lane_releases_every_claim(env, monkeypatch):
    conn, log, state = env
    monkeypatch.setattr(ddq, "rank_research_lanes", lambda cur: [])
    out = ddq.route(conn.cursor(), 2)
    assert out["routed"] == 0 and state["open_at_spawn"] == []
    rel = [e for e in log if isinstance(e, tuple) and "routed_at = NULL" in e[1]]
    assert rel and rel[0][2] == (["g1", "g2"],) and not conn.open_txn


def test_a_cursor_without_a_connection_keeps_the_old_contract(monkeypatch):
    log = []
    conn = Conn(log, rows=[("g1", "AAA", "q")])
    cur = conn.cursor()
    cur.connection = None
    monkeypatch.setattr(ddq, "rank_research_lanes", lambda c: [("grok", 1, 1)])
    monkeypatch.setattr(ddq, "via_bridge", lambda: False)
    monkeypatch.setattr(ddq.subprocess, "run", lambda *a, **k: Proc(0))
    out = ddq.route(cur, 1)
    assert out["routed"] == 1 and "_db" not in out


# ---- the researcher's "johnclaw" database FATAL ------------------------------------------------------------
def test_researcher_connects_to_the_app_db_even_with_empty_db_env(monkeypatch):
    seen = {}
    import psycopg2

    monkeypatch.setattr(psycopg2, "connect", lambda **k: seen.update(k) or object())
    monkeypatch.setattr(researcher, "_load_env", lambda: None)
    for k in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DB_NAME", "")  # setdefault would never override this
    researcher._pg_connect()
    assert seen["dbname"] == "trade_ai" and seen["user"] == "trade_ai" and seen["host"] == "localhost"


def test_researcher_has_no_bare_getenv_connect_left():
    src = (ROOT / "scripts" / "hermes_external_researcher.py").read_text(encoding="utf-8")
    assert 'dbname=os.getenv("DB_NAME")' not in src
