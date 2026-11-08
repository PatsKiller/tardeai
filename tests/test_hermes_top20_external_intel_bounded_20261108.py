"""LQ-20261107-1136: hermes_top20_external_intel honours ``--top`` and survives the socket the LLM waits kill.

ANCHOR: TOP20_BOUNDED_SCAN_20261108

Measured on the 2026-11-08 14:05 ET cron run (logs/hermes_top20.log, receipt
``data/runtime/hermes_top20_external_intel_last.json`` 19:05:01Z → 19:12:25Z, ``OperationalError``):

* ``--top 20`` scanned **2,312** distinct symbols. ``_top`` OR'd ``in_directive_watch = true`` into the ranked
  arm and that flag is inflated: 3,676 rows carry it on 2026-11-08 while ``directive_promotion.FLAG_KEEP_SQL``
  keeps 404 — the flag's baseline reconcile (``reconcile_directive_watch_flag.py --apply``) has never been run
  (no marker, no backup dir). The arm was never a research opportunity either: the guard's
  ``external_cloud_tiers`` is T0/T1 and ``active_directive`` maps to T2, so a directive name can only ever be
  DEFERred here.
* the ranked arm was ``hermes_rank <= 20``, which is every row in the top-20 band (29-52 symbols, rank is not
  unique), not the top 20.
* one connection was held for the whole run, idle across up to ``timeout=180`` researcher subprocess calls; the
  read after those waits raised ``OperationalError: SSL connection has been closed unexpectedly`` and ended the
  run with an empty receipt summary.

These tests pin the repair, one property each. Synthetic scripted connections only: no DB, no network, no
researcher, no removal.
"""
from __future__ import annotations

import sys
import types

import pytest
from psycopg2 import OperationalError

sys.path.insert(0, "scripts")

import hermes_top20_external_intel as top20  # noqa: E402

COLS = ("symbol", "hermes_rank", "hermes_composite_score", "hermes_score_components", "rsi", "trend")


def row(symbol, rank=None, score=50.0):
    return {"symbol": symbol, "hermes_rank": rank, "hermes_composite_score": score,
            "hermes_score_components": {}, "rsi": 50, "trend": "up"}


class _Cur:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        # The two arms are told apart by the predicate each one is pinned to below.
        self._rows = self._conn.directive if "in_directive_watch" in sql else self._conn.ranked
        self._conn.executed.append((sql, params))
        self.description = [(c,) for c in COLS]

    def fetchall(self):
        return [tuple(r[c] for c in COLS) for r in self._rows]


class _Conn:
    """A scripted connection: the ranked arm and the directive arm answer from their own lists."""

    def __init__(self, ranked=(), directive=()):
        self.ranked, self.directive = list(ranked), list(directive)
        self.executed = []

    def cursor(self):
        return _Cur(self)


# ── the scan is bounded by --top ────────────────────────────────────────────────────────────────────────────────

def test_each_arm_is_a_true_limit_not_a_rank_band_filter():
    """``hermes_rank <= 20`` returned every row in the band; each arm must carry its own ``LIMIT``."""
    conn = _Conn(ranked=[row("AAA", 1)], directive=[row("ZZZ", None)])
    top20._top(conn, 20)
    ranked_sql, ranked_params = conn.executed[0]
    directive_sql, directive_params = conn.executed[1]
    assert "LIMIT %s" in ranked_sql and ranked_params == (20,)
    assert "LIMIT %s" in directive_sql and directive_params == (20,)
    assert "hermes_rank <= %s" not in ranked_sql, "a rank band is not the top N"


def test_the_directive_arm_is_bounded_by_the_same_n_as_the_rank_arm():
    """3,676 flagged rows must not enter a ``--top 20`` scan: the arm shares the ``n`` by default."""
    conn = _Conn(ranked=[row("AAA", 1)], directive=[row("ZZZ", None)])
    top20._top(conn, 5)
    assert conn.executed[1][1] == (5,)
    top20._top(conn, 5, directive_limit=2)
    assert conn.executed[3][1] == (2,)


def test_the_arms_merge_without_duplicates_and_rank_first():
    conn = _Conn(ranked=[row("AAA", 1), row("BBB", 2)],
                 directive=[row("BBB", 2), row("CCC", 7), row("ZZZ", None)])
    rows = top20._top(conn, 2)
    assert [r["symbol"] for r in rows] == ["AAA", "BBB", "CCC", "ZZZ"]
    assert len({r["symbol"] for r in rows}) == len(rows)


def test_the_directive_arm_reads_the_flag_and_never_its_own_operator_join():
    """The flag has one writer (directive_promotion); a consumer re-deriving it is the 2026-10-22 regression."""
    conn = _Conn(ranked=[row("AAA", 1)], directive=[])
    top20._top(conn, 20)
    directive_sql = conn.executed[1][0]
    assert "in_directive_watch=true AND status<>'removed'" in directive_sql
    assert "created_by" not in directive_sql


# ── the connection outlives the LLM wait ───────────────────────────────────────────────────────────────────────

class _Socket:
    """A connection that can be declared dead: any cursor read raises, exactly like the reaped SSL socket."""

    def __init__(self, dead=False):
        self.dead, self.closed = dead, False

    def cursor(self):
        if self.dead:
            raise OperationalError("SSL connection has been closed unexpectedly")
        return types.SimpleNamespace(execute=lambda *a, **k: None, fetchall=lambda: [],
                                     description=[("x",)])

    def close(self):
        self.closed = True


def test_a_query_reopens_the_socket_once_on_a_connection_error():
    made = []

    def factory():
        made.append(_Socket(dead=not made))   # the first socket is dead, the second is healthy
        return made[-1]

    session = top20._Session(factory=factory)
    session.query(lambda conn: conn.cursor())                # the dead socket raises here
    assert len(made) == 2 and made[0].closed is True


def test_a_query_does_not_swallow_a_statement_error():
    def factory():
        return _Socket()

    session = top20._Session(factory=factory)

    def bad(conn):
        raise ValueError("column does not exist")

    with pytest.raises(ValueError):
        session.query(bad)


def test_after_llm_drops_the_socket_before_the_next_read():
    made = []

    def factory():
        made.append(_Socket())
        return made[-1]

    session = top20._Session(factory=factory)
    session.query(lambda conn: conn.cursor())
    session.after_llm()
    assert len(made) == 2 and made[0].closed is True
    session.query(lambda conn: conn.cursor())               # works on the fresh socket


# ── the run finishes even when the socket dies mid-run ────────────────────────────────────────────────────────

def _run_setup(monkeypatch, rows, *, raise_on_read=None):
    """A run whose socket is reopened after every LLM wait; ``raise_on_read`` kills one read instead."""
    made, reads = [], {"n": 0}

    def factory():
        made.append(_Socket())
        return made[-1]

    monkeypatch.setattr(top20, "_conn", factory)
    monkeypatch.setattr(top20, "_top", lambda conn, n, directive_limit=None: list(rows))
    monkeypatch.setattr(top20, "_trigger_context",
                        lambda conn: {"holdings": set(), "proposals": set(), "directive": set()})

    def recent(conn, symbol, lane):
        reads["n"] += 1
        if raise_on_read is not None and reads["n"] == raise_on_read:
            raise OperationalError("SSL connection has been closed unexpectedly")
        return False

    monkeypatch.setattr(top20, "_recent", recent)
    monkeypatch.setattr(top20, "append_call_event", lambda *a, **k: None)
    guard = types.ModuleType("hermes_research_budget_guard")
    guard._load_policy = lambda: {"trigger_source_tier": {"holdings": "T0"}}
    guard.decide = lambda **kw: {"decision": "ALLOW"}
    monkeypatch.setitem(sys.modules, "hermes_research_budget_guard", guard)
    calls = []
    monkeypatch.setattr(top20.subprocess, "run",
                        lambda cmd, **kw: (calls.append(cmd), types.SimpleNamespace(returncode=0))[1])
    return made, reads, calls


def test_a_socket_killed_by_an_llm_wait_is_reopened_and_every_symbol_is_still_attempted(monkeypatch):
    rows = [row("AAA", 1), row("BBB", 2)]
    made, _reads, calls = _run_setup(monkeypatch, rows)
    rep = top20.run(top=20, lanes=("grok", "chatgpt"), apply=True)
    assert rep["called"] == 4 and rep["call_errors"] == 0
    assert len(calls) == 4
    # One socket per researcher call: the socket never idles across an LLM wait.
    assert len(made) == 5  # initial + one reconnect after each of the four calls
    assert all(c.closed for c in made[:-1])


def test_a_connection_error_costs_one_retry_not_the_run(monkeypatch):
    rows = [row("AAA", 1), row("BBB", 2)]
    made, reads, _calls = _run_setup(monkeypatch, rows, raise_on_read=2)
    rep = top20.run(top=20, lanes=("grok",), apply=True)
    assert rep["called"] == 2 and rep["call_errors"] == 0
    assert reads["n"] == 3        # two reads plus the one retry the closed socket cost
    assert len(made) >= 3
