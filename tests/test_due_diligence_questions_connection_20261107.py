"""due-diligence-questions: a server-closed socket must not kill the run (LQ-20261107-305).

2026-11-07 15:20 ET: the run held one connection and an open transaction across the slow model calls.
The server closed the socket during a call; the next DB use raised ``SSL connection has been closed
unexpectedly`` and the lane exited 1 with ``ok=false``.

What is pinned here:

* ``_usable`` returns the same connection when a statement executes, and a fresh one only when it does not;
* the loop ends its read transaction before the model call, so no transaction idles across model time;
* after a socket drop during the model call, the write that follows runs on a reconnected connection.

Hermetic: the module is executed from source; DB, DDL, escalation, curation and receipts are stubs.
No DB, provider, lock or live state.
"""

from __future__ import annotations

import argparse
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


class _OperationalError(Exception):
    pass


class _Conn:
    def __init__(self, name: str):
        self.name = name
        self.dropped = False      # the server has closed this socket
        self.open = False         # a transaction is open on this connection
        self.closed = 0           # conn.closed stays 0 when the server closes the socket
        self.closed_flag = False
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cur(self)

    def commit(self):
        self.open = False
        self.commits += 1

    def rollback(self):
        if self.dropped:
            raise _OperationalError("SSL connection has been closed unexpectedly")
        self.open = False
        self.rollbacks += 1

    def close(self):
        self.closed_flag = True

    def set_session(self, **_kw):
        pass


class _Cur:
    def __init__(self, conn: _Conn):
        self.conn = conn
        self.rowcount = 0

    def execute(self, sql, params=None):
        if self.conn.dropped:
            raise _OperationalError("SSL connection has been closed unexpectedly")
        self.conn.open = True

    def fetchone(self):
        return (True,)

    def fetchall(self):
        return []


def _load(conns: list) -> types.ModuleType:
    path = ROOT / "scripts" / "due_diligence_questions.py"
    mod = types.ModuleType("ddq_connection_under_test")
    mod.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), mod.__file__, "exec"), mod.__dict__)

    def fresh_db():
        conn = _Conn(f"conn{len(conns) + 1}")
        conns.append(conn)
        return conn

    mod._db = fresh_db
    return mod


def test_usable_keeps_a_healthy_connection_and_does_not_reconnect():
    conns: list = []
    mod = _load(conns)
    conn = _Conn("healthy")
    cur = conn.cursor()
    got_conn, got_cur = mod._usable(conn, cur)
    assert got_conn is conn and got_cur is cur
    assert conns == []                # _db never called
    assert conn.rollbacks == 0


def test_usable_reconnects_when_the_server_closed_the_socket():
    conns: list = []
    mod = _load(conns)
    conn = _Conn("dropped")
    conn.dropped = True
    got_conn, got_cur = mod._usable(conn, conn.cursor())
    assert got_conn is not conn
    assert conn.closed_flag is True   # the dead socket is closed, not reused
    assert len(conns) == 1            # exactly one reconnect
    got_cur.execute("SELECT 1")       # the new pair works


def test_the_read_transaction_ends_before_the_model_call_and_the_write_survives_a_drop(monkeypatch):
    conns: list = []
    mod = _load(conns)
    observed = {}
    written_on = []

    def db():
        # first call: the run's own connection; second call: the reconnect after the drop
        conn = _Conn("first" if not conns else "second")
        conns.append(conn)
        return conn

    mod._db = db

    change = {"subject_guid": "S1", "change_guid": "C1", "symbol": "ABC", "kind": "x", "magnitude": 1}
    mod.pending_changes = lambda cur, n: [change]
    mod.evidence_subjects = lambda cur, guids: {"S1"}
    mod.cap_env_warning = lambda: None
    mod.reconcile_answers = lambda cur, apply=False: {}
    mod.dossier = lambda cur, guid: [{"id": 1}]
    mod.ground = lambda parsed, items: ([{"sentence": "s", "cites": []}], [], {})

    def ask_model(ch, items):
        observed["txn_open_during_model_call"] = conns[0].open
        conns[0].dropped = True       # the server closes the socket while the model is thinking
        return {"parsed": {}, "lane": "bridge"}

    mod.ask_model = ask_model

    def persist(cur, ch, narrative, questions, got, n):
        written_on.append(cur.conn)
        cur.execute("INSERT INTO due_diligence_questions VALUES (1)")   # raises on a dead socket
        return None, 1

    mod.persist = persist
    receipts = []
    mod._write_lane_receipt = lambda **kw: receipts.append(kw)

    # the lazy imports inside _apply_run
    ddl = types.ModuleType("scripts.lib.ddl_guard")
    ddl.apply_ddl = lambda cur, sql: None
    esc = types.ModuleType("lib.llm_escalation")

    class EscalationStopped(Exception):
        pass

    esc.EscalationStopped = EscalationStopped
    monkeypatch.setitem(sys.modules, "scripts.lib.ddl_guard", ddl)
    monkeypatch.setitem(sys.modules, "lib.llm_escalation", esc)

    args = argparse.Namespace(apply=True, route=False, limit=5)
    rc = mod._apply_run(args, datetime.now(timezone.utc))

    assert observed["txn_open_during_model_call"] is False, "a transaction idled across the model call"
    assert len(conns) == 2, "expected one reconnect after the drop"
    assert written_on and written_on[0] is conns[1], "the write ran on the dropped socket"
    assert rc == 0
    assert receipts and receipts[-1]["ok"] is True
