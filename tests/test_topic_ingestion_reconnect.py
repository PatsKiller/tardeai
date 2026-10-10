#!/usr/bin/env python3
"""topic_ingestion.py survives a lost DB connection and writes a per-run lane receipt.

2026-10-09 20:45 ET: Postgres restarted mid-run; ``is_duplicate`` raised "SSL connection has been closed
unexpectedly", the handler's ``ROLLBACK TO SAVEPOINT`` / ``conn.rollback()`` raised on the dead
connection and the 14-topic run died. The lane's registry signal was null, so nothing noticed.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import psycopg2
import psycopg2.errors
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ti = _load("topic_ingestion_reconnect_under_test", "scripts/topic_ingestion.py")
pgr = _load("pg_reconnect_for_topic_test", "scripts/lib/pg_reconnect.py")

SSL_LOST = "SSL connection has been closed unexpectedly"


class Cur:
    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self._rows = []

    def execute(self, sql, params=None):
        if self.conn.closed:
            raise psycopg2.InterfaceError("cursor already closed")
        key = sql.split()[0]
        if self.conn.fail_on.get(key):
            self.conn.fail_on[key] -= 1
            self.conn.closed = 2
            raise psycopg2.OperationalError(SSL_LOST)
        if key == "ROLLBACK":
            raise psycopg2.errors.InvalidSavepointSpecification("savepoint does not exist")
        self.conn.log.append(key)
        if sql.startswith("SELECT * FROM topic_monitor"):
            self.description = [("topic_id",), ("display_name",)]
            self._rows = [("t1", "Topic One"), ("t2", "Topic Two")]

    def fetchone(self):
        return None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class Conn:
    def __init__(self, fail_on=None):
        self.closed = 0
        self.fail_on = dict(fail_on or {})
        self.log = []
        self.commits = 0

    def cursor(self, *a, **kw):
        if self.closed:
            raise psycopg2.InterfaceError("connection already closed")
        return Cur(self)

    def commit(self):
        if self.closed:
            raise psycopg2.InterfaceError("connection already closed")
        self.commits += 1

    def rollback(self):
        if self.closed:
            raise psycopg2.InterfaceError("connection already closed")

    def close(self):
        self.closed = 1


def proxy(*conns):
    it = iter(conns)
    return pgr.ReconnectingConnection(lambda: next(it), sleep=lambda s: None, log=lambda m: None)


@pytest.fixture
def stub_writer(monkeypatch):
    import lib.writers.news_articles_writer as w

    def is_duplicate(cur, *a):
        cur.execute("SELECT id FROM news_articles")
        return False

    def write_news_articles(cur, rows, **kw):
        cur.execute("INSERT INTO news_articles")
        return SimpleNamespace(rows_written=len(rows))

    monkeypatch.setattr(w, "is_duplicate", is_duplicate)
    monkeypatch.setattr(w, "write_news_articles", write_news_articles)
    monkeypatch.setattr(ti, "score_content", lambda *a, **k: {"relevance_score": 0.5})
    monkeypatch.setattr(ti, "tag_content", lambda *a, **k: {"strategy_tags": [], "agent_tags": []})


TOPIC = {"topic_id": "t1", "strategy_tags": [], "agent_tags": []}
ITEM = {"title": "A title", "url": "https://example.test/a", "source": "google_news_rss", "description": "d"}


def test_lost_dedupe_select_is_retried_and_the_article_saves(stub_writer):
    """Tonight's exact failure point (is_duplicate, first statement of the transaction)."""
    c1, c2 = Conn({"SELECT": 1}), Conn()
    conn = proxy(c1, c2)
    assert ti._save_article(conn, TOPIC, ITEM, {"summary": "s"}) is True
    assert c2.log == ["SELECT", "SAVEPOINT", "INSERT"] and c2.commits == 1
    assert (conn.reconnects, conn.retried_ops) == (1, 1)


def test_loss_mid_transaction_drops_one_article_and_the_run_continues(stub_writer):
    c1, c2 = Conn({"INSERT": 1}), Conn()
    conn = proxy(c1, c2)
    assert ti._save_article(conn, TOPIC, ITEM, {"summary": "s"}) is False  # no exception escapes
    assert conn.dropped_ops == 1
    assert ti._save_article(conn, TOPIC, dict(ITEM, url="https://example.test/b"), {"summary": "s"}) is True
    assert c2.log[-3:] == ["SELECT", "SAVEPOINT", "INSERT"]


def test_gap_fill_log_survives_a_lost_connection():
    c1, c2 = Conn({"INSERT": 1}), Conn()
    conn = proxy(c1, c2)
    ti._log_gap_fill(conn, "t1", "google_news_rss", "q", 3, 1, 0, True, 10)  # retried as first statement
    assert c2.log == ["INSERT"] and c2.commits == 1


def _run_main(monkeypatch, tmp_path, argv, *, conn_factory, process=None, previous=None):
    receipt = tmp_path / "topic_ingestion_run_latest.json"
    if previous is not None:
        receipt.write_text(json.dumps(previous), encoding="utf-8")
    monkeypatch.setattr(ti, "RUN_RECEIPT", receipt)
    monkeypatch.setattr(ti, "_interval_gate_ok", lambda: True)
    monkeypatch.setattr(ti, "_get_run_conn", conn_factory)
    monkeypatch.setattr(ti, "_check_existing_count", lambda *a: 5)
    monkeypatch.setattr(ti, "_write_desk_projection", lambda stats: None)
    monkeypatch.setattr(ti, "process_topic", process or (
        lambda conn, topic, **kw: {"articles": 1, "transcripts": 0, "found": 2, "sources_used": ["x"]}))
    monkeypatch.setattr(sys, "argv", ["topic_ingestion.py", "--no-auto-curate", *argv])
    return receipt


def test_ok_run_writes_receipt_with_ok_at(monkeypatch, tmp_path):
    receipt = _run_main(monkeypatch, tmp_path, ["--max-topics", "14"], conn_factory=lambda: proxy(Conn()))
    ti.main()
    r = json.loads(receipt.read_text())
    assert r["schema"] == "TopicIngestionRun@v1" and r["status"] == "ok"
    assert r["ok_at"] == r["finished_at"] and r["topics_processed"] == 2 and r["articles"] == 2
    assert r["db_reconnects"] == 0


def test_run_survives_restart_between_topics_and_records_the_reconnect(monkeypatch, tmp_path):
    c1, c2 = Conn({"UPDATE": 1}), Conn()  # last_searched UPDATE after topic 1 hits the dead connection
    receipt = _run_main(monkeypatch, tmp_path, [], conn_factory=lambda: proxy(c1, c2))
    ti.main()
    r = json.loads(receipt.read_text())
    assert r["status"] == "ok" and r["topics_processed"] == 2 and r["db_reconnects"] == 1
    assert c2.log.count("UPDATE") == 2  # the lost UPDATE was retried, topic 2's ran on c2


def test_failed_run_keeps_previous_ok_at_and_raises(monkeypatch, tmp_path):
    def boom(conn, topic, **kw):
        raise RuntimeError("search exploded")

    receipt = _run_main(monkeypatch, tmp_path, [], conn_factory=lambda: proxy(Conn()), process=boom,
                        previous={"ok_at": "2026-10-08T00:56:00+00:00"})
    with pytest.raises(RuntimeError):
        ti.main()
    r = json.loads(receipt.read_text())
    assert r["status"] == "failed" and r["ok_at"] == "2026-10-08T00:56:00+00:00"
    assert "search exploded" in r["error"]


def test_unrecoverable_database_fails_the_run(monkeypatch, tmp_path):
    def factory():
        it = iter([Conn({"UPDATE": 1})])

        def make():
            try:
                return next(it)
            except StopIteration:
                raise psycopg2.OperationalError("could not connect") from None

        return pgr.ReconnectingConnection(make, sleep=lambda s: None, log=lambda m: None,
                                          reconnect_delays_s=(1.0,))

    receipt = _run_main(monkeypatch, tmp_path, [], conn_factory=factory, previous={"ok_at": "prev"})
    with pytest.raises(Exception):
        ti.main()
    r = json.loads(receipt.read_text())
    assert r["status"] == "failed" and r["ok_at"] == "prev"


def test_single_topic_drain_and_dry_run_do_not_touch_the_lane_receipt(monkeypatch, tmp_path):
    receipt = _run_main(monkeypatch, tmp_path, ["--topic", "t1"], conn_factory=lambda: proxy(Conn()))
    ti.main()
    assert not receipt.exists()
    receipt = _run_main(monkeypatch, tmp_path, ["--dry-run"], conn_factory=lambda: proxy(Conn()))
    ti.main()
    assert not receipt.exists()


def test_interval_gate_skip_is_recorded_without_advancing_ok_at(monkeypatch, tmp_path):
    receipt = _run_main(monkeypatch, tmp_path, [], conn_factory=lambda: proxy(Conn()), previous={"ok_at": "prev"})
    monkeypatch.setattr(ti, "_interval_gate_ok", lambda: False)
    ti.main()
    r = json.loads(receipt.read_text())
    assert r["status"] == "skipped" and r["ok_at"] == "prev"
