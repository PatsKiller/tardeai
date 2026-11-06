"""Injection triage batch 12: identifiers only after a plain-name check, values only as driver parameters.

ANCHOR: INJECTION_TRIAGE_12_20261106

Hermetic. No database: a fake cursor records every (sql, params) pair and the real functions are driven
through it. A hostile value must arrive in params (or be refused before any SQL runs), never in SQL text.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib import retention_archive as ra  # noqa: E402
from lib import two_way_curation as tc  # noqa: E402
from lib.writers import news_articles_writer as naw  # noqa: E402

import watchlist_priority as wp  # noqa: E402

HOSTILE = "x'; DROP TABLE t;--"


class RecordingCursor:
    """Records (sql, params); answers fetchone/fetchall with fixed shapes. ``fail_on`` raises like an abort."""

    def __init__(self, fetchone=(0,), fetchall_batches=None):
        self.calls: list[tuple[str, object]] = []
        self._fetchone = fetchone
        self._batches = list(fetchall_batches or [])
        self.rowcount = 0
        self.connection = self

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return self._batches.pop(0) if self._batches else []

    def rollback(self):
        pass

    def close(self):
        pass


class RecordingConn:
    def __init__(self, cur):
        self._cur = cur
        self.autocommit = False

    def cursor(self, *a, **k):
        return self._cur

    def commit(self):
        pass

    def rollback(self):
        pass


def _sql_text(cur) -> str:
    return "\n".join(sql for sql, _ in cur.calls)


# --- retention_archive (table/key are checked identifiers; predicate values are params) --------------------

def test_managed_purge_values_travel_as_params():
    cur = RecordingCursor(fetchone=(3,))
    out = ra.managed_purge(RecordingConn(cur), table="news_articles", where_sql="t.title = %s", params=(HOSTILE,),
                           label="t12", writer="test", apply=False)
    assert out["eligible"] == 3 and out["mode"] == "dry_run"
    assert cur.calls == [("SELECT count(*) FROM news_articles t WHERE t.title = %s", (HOSTILE,))]
    assert "DROP TABLE" not in _sql_text(cur)


@pytest.mark.parametrize("fn", ["managed_purge", "estimate", "archive_then_delete_batches"])
def test_hostile_table_is_refused_before_any_sql(fn, tmp_path):
    cur = RecordingCursor(fetchone=(1, 1))
    kwargs = {"table": HOSTILE, "where_sql": "TRUE"}
    if fn == "managed_purge":
        kwargs.update(label="t12", writer="test", apply=False)
    if fn == "archive_then_delete_batches":
        kwargs.update(label="t12", archive_dir=tmp_path, batch_rows=10, max_rows=10)
    with pytest.raises(ValueError):
        getattr(ra, fn)(RecordingConn(cur), **kwargs)
    assert cur.calls == []


def test_hostile_key_is_refused_and_plain_names_pass():
    cur = RecordingCursor(fetchone=(0, 0))
    with pytest.raises(ValueError):
        ra.estimate(RecordingConn(cur), table="content_embeddings", where_sql="TRUE", key="id; DROP TABLE t")
    assert cur.calls == []
    # Every name a real caller passes stays allowed (plain names, optionally schema-qualified).
    for name in ("content_embeddings", "hermes_directive_hits_staging", "memory_r10_m2.memory_fact_version"):
        assert ra._plain_ident(name, table=True) == name
    assert ra._plain_ident("id") == "id"


# --- two_way_curation (savepoint names checked; the staging table comes from STAGING_TABLE) ----------------

def test_savepoint_helpers_refuse_a_hostile_name():
    cur = RecordingCursor()
    tc._rollback_savepoint(cur, f"sp_cio_{HOSTILE}")
    assert cur.calls == []
    tc._rollback_savepoint(cur, "sp_cio_7")
    assert [sql for sql, _ in cur.calls] == ["ROLLBACK TO SAVEPOINT sp_cio_7", "RELEASE SAVEPOINT sp_cio_7"]


def _drain(row_id):
    row = {"id": row_id, "directive_id": 42, "symbol": "NVDA", "thesis": "t",
           "source_detail": {"directive_kind": "ticker", "spec": {}, "directive_label": "L"}}
    cur = RecordingCursor(fetchall_batches=[[row]])
    report: dict = {}
    tc.drain_curation_sources(cur, False, report,
                              evaluate=lambda *a, **k: {"status": "MONITORED_NO_QUALIFY"},
                              resolve_fn=lambda d: ["NVDA"])
    return cur, report


def test_drain_hostile_staging_id_never_reaches_sql_text():
    cur, report = _drain(HOSTILE)
    assert "DROP TABLE" not in _sql_text(cur)
    # the refused savepoint makes the promote an ERROR: the row stays undrained for retry
    assert report["curation_errors"] == 1 and report["curation_drained"] == 0


def test_drain_legit_staging_id_unchanged():
    cur, report = _drain(7)
    sqls = [sql for sql, _ in cur.calls]
    assert "SAVEPOINT sp_cio_7" in sqls and "RELEASE SAVEPOINT sp_cio_7" in sqls
    upd = [(s, p) for s, p in cur.calls if s.startswith("UPDATE cio_directive_hits_staging")]
    assert upd == [("UPDATE cio_directive_hits_staging SET drained=true, drained_at=now() WHERE id=%s", (7,))]
    assert report["curation_drained"] == 1


# --- watchlist_priority / news_articles_writer (literal fragments; values in params) -----------------------

def test_daily_priority_holdings_are_params(monkeypatch):
    monkeypatch.setattr(wp, "holdings_list", lambda project_root=None: [HOSTILE])
    cur = RecordingCursor(fetchall_batches=[[("NVDA",)]])
    assert wp.load_daily_priority_symbols(cur) == {"NVDA"}
    (sql, params), = cur.calls
    assert "DROP TABLE" not in sql and params[0] == [HOSTILE]
    assert sql.count("%s") == len(params)


def test_news_is_duplicate_title_is_a_param():
    cur = RecordingCursor(fetchone=None)
    assert naw.is_duplicate(cur, HOSTILE, title=HOSTILE) is False
    (sql, params), = cur.calls
    assert sql == "SELECT id FROM news_articles WHERE symbol = %s AND (title = %s) LIMIT 1"
    assert params == [HOSTILE, HOSTILE]
