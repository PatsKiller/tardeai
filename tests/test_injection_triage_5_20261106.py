"""Injection triage batch 5: hostile values reach the driver as parameters or quoted identifiers, never SQL text.

ANCHOR: INJECTION_TRIAGE_5_20261106

Rule tq-py-sql-fstring. Hermetic: a recording fake cursor stands in for psycopg2; no database is touched.
- cleanup_stale_proposals.sweep_stale_enrichment_in_progress: the stale-minutes window is a driver parameter.
- build_phase2e_qwen3_global_shadow_index.main / build_phase2b_parallel_embedding_index.main: a CLI table name
  is carried only inside psycopg2.sql.Identifier, never inside an SQL text fragment.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
# CI's plain shards do not install psycopg2; this line routes the file to the Postgres shard (scripts/lib/ci_shards.py).
pytest.importorskip("psycopg2")
from psycopg2 import sql  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_phase2b_parallel_embedding_index as p2b  # noqa: E402
import build_phase2e_qwen3_global_shadow_index as p2e  # noqa: E402
import cleanup_stale_proposals as csp  # noqa: E402

HOSTILE = "x'; DROP TABLE t;--"


class _Cur:
    """Records (sql, params); answers every fetch with a configurable row set."""

    def __init__(self, one=(0,), rows=(), description=None):
        self.calls: list[tuple[object, object]] = []
        self.rowcount = 0
        self._one, self._rows = one, list(rows)
        self.description = description or []

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, cur):
        self.cur, self.commits = cur, 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


def _text_parts(q) -> tuple[list[str], list[str]]:
    """(SQL text fragments, identifier strings) of a query that is a str or a psycopg2.sql composable."""
    if isinstance(q, str):
        return [q], []
    if isinstance(q, sql.Composed):
        texts, idents = [], []
        for part in q.seq:
            t, i = _text_parts(part)
            texts += t
            idents += i
        return texts, idents
    if isinstance(q, sql.Identifier):
        return [], list(q.strings)
    if isinstance(q, sql.SQL):
        return [q.string], []
    raise AssertionError(f"unexpected query object {type(q)!r}")


# ── cleanup_stale_proposals ─────────────────────────────────────────────────

def test_stale_minutes_window_is_a_parameter():
    cur = _Cur(one=(3,))
    cur.rowcount = 3
    csp.sweep_stale_enrichment_in_progress(cur, _Conn(cur), apply=True, stale_minutes=45)
    windowed = [(q, p) for q, p in cur.calls if "enrichment_last_attempt_at" in q]
    assert len(windowed) == 2                                        # the count and the reset
    for q, p in windowed:
        assert p == (45,)
        assert "%s * INTERVAL '1 minute'" in q and "45" not in q
    assert all(not isinstance(q, str) or "{" not in q for q, _ in cur.calls)


def test_stale_minutes_hostile_value_never_reaches_the_database():
    cur = _Cur()
    with pytest.raises(ValueError):
        csp.sweep_stale_enrichment_in_progress(cur, _Conn(cur), apply=True, stale_minutes=HOSTILE)
    assert cur.calls == []


def test_stale_minutes_floor_is_kept():
    cur = _Cur(one=(0,))
    csp.sweep_stale_enrichment_in_progress(cur, _Conn(cur), apply=False, stale_minutes=1)
    assert [p for q, p in cur.calls if "enrichment_last_attempt_at" in q] == [(5,)]


# ── phase 2E / 2B: CLI table names ──────────────────────────────────────────

def _assert_identifier_only(calls, name):
    seen = 0
    for q, _ in calls:
        texts, idents = _text_parts(q)
        assert all(name not in t for t in texts), q
        seen += idents.count(name)
    return seen


def test_phase2e_table_names_are_identifiers(monkeypatch):
    cur = _Cur(one=(0,), rows=[])
    monkeypatch.setattr(p2e, "get_conn", lambda: _Conn(cur))
    monkeypatch.setattr(sys, "argv", ["x", "--dry-run", "--resume", "--source-table", HOSTILE,
                                      "--target-table", HOSTILE + "2", "--source-types", "news,youtube"])
    p2e.main()
    assert _assert_identifier_only(cur.calls, HOSTILE) >= 3          # count + priority loop + distinct
    assert _assert_identifier_only(cur.calls, HOSTILE + "2") == 2    # count + resume keys
    resume = [p for q, p in cur.calls if p == ("qwen3-embedding:8b",)]
    assert resume, "the model filter stays a parameter"
    prio = [p for q, p in cur.calls if isinstance(p, list) and len(p) == 3]
    assert prio and prio[0][1:] == ["news", "youtube"]


def test_phase2e_schema_qualified_name_keeps_both_parts():
    assert p2e.table_ident("public.content_embeddings").strings == ("public", "content_embeddings")
    assert p2b.table_ident("content_embeddings_qwen3_test").strings == ("content_embeddings_qwen3_test",)


def test_phase2b_table_name_is_an_identifier(monkeypatch):
    class _Cur2b(_Cur):
        def fetchone(self):
            return (True,)                                           # the test table exists

    cur = _Cur2b(rows=[(1, "news", "n1", "title", None)],
                 description=[("id",), ("source_type",), ("source_id",), ("title",), ("created_at",)])
    monkeypatch.setattr(p2b, "get_db_connection", lambda: _Conn(cur))
    monkeypatch.setattr(sys, "argv", ["x", "--dry-run", "--limit-docs", "10", "--table", HOSTILE])
    p2b.main()
    # the existence probe passes the name as a value; the existing-keys read carries it as an identifier
    assert any(p == (HOSTILE,) for _, p in cur.calls)
    assert _assert_identifier_only(cur.calls, HOSTILE) == 1
