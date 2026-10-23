"""Watchdog owns bounded enrichment children; enrichment writers are single-flight."""

from __future__ import annotations

import signal
import os
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REAL_POPEN = subprocess.Popen


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg2", types.ModuleType("psycopg2"))
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    for name in ("pipeline_watchdog", "symbol_enrichment"):
        sys.modules.pop(name, None)
    import pipeline_watchdog
    import symbol_enrichment

    yield pipeline_watchdog, symbol_enrichment
    sys.modules.pop("pipeline_watchdog", None)
    sys.modules.pop("symbol_enrichment", None)


def _child(tmp_path: Path, body: str) -> subprocess.Popen:
    script = tmp_path / "child.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, str(script)], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def test_watchdog_waits_for_owned_children_before_return(tmp_path, modules):
    watchdog, _ = modules
    child = _child(tmp_path, "import time\ntime.sleep(.15)\n")
    children = [("ABC", child)]
    with watchdog._supervise_enrichment_batch(children, timeout_s=2):
        pass
    assert child.poll() == 0


def test_watchdog_timeout_terminates_and_reaps_child_process_group(tmp_path, modules):
    watchdog, _ = modules
    child = _child(tmp_path, "import time\ntime.sleep(30)\n")
    with watchdog._supervise_enrichment_batch([("ABC", child)], timeout_s=0.1):
        pass
    assert child.poll() is not None
    assert child.returncode in (-signal.SIGTERM, -signal.SIGKILL)


def test_watchdog_signal_terminates_owned_children_before_unwinding(tmp_path, modules):
    watchdog, _ = modules
    child = _child(tmp_path, "import time\ntime.sleep(30)\n")
    with pytest.raises(watchdog._EnrichmentInterrupted):
        with watchdog._supervise_enrichment_batch([("ABC", child)], timeout_s=30):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
    assert child.poll() is not None


def test_watchdog_keeps_supervising_descendants_after_child_exits(tmp_path, modules):
    watchdog, _ = modules
    marker = tmp_path / "grandchild.pid"
    child = _child(
        tmp_path,
        f"""
        import subprocess, sys
        grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        open({str(marker)!r}, 'w').write(str(grandchild.pid))
    """,
    )
    with watchdog._supervise_enrichment_batch([("ABC", child)], timeout_s=0.2):
        pass
    assert child.poll() == 0
    assert marker.exists()
    grandchild_pid = int(marker.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild_pid, 0)


def test_watchdog_claims_entity_before_spawning_only_one_enrichment(modules, monkeypatch):
    watchdog, _ = modules

    class Cursor:
        result = None

        def execute(self, sql, params=()):
            if "SELECT e.entity_id" in sql:
                self.rows = [("ABC", "market", 42, "STALE", None)]
            elif "UPDATE intelligence_entities SET last_enriched=NOW()" in sql:
                if conn.claimed:
                    self.result = None
                else:
                    conn.claimed = True
                    self.result = ("2026-10-22T00:00:00Z",)

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return self.result

    class Connection:
        claimed = False

        def __init__(self):
            self.cur = Cursor()

        def cursor(self):
            return self.cur

        def commit(self):
            pass

        def rollback(self):
            pass

    conn = Connection()
    spawned = []

    def spawn(*args, **kwargs):
        spawned.append(kwargs)
        return REAL_POPEN([sys.executable, "-c", "pass"], start_new_session=True)

    monkeypatch.setattr(watchdog.subprocess, "Popen", spawn)
    monkeypatch.setattr(watchdog, "was_alerted_recently", lambda *a, **k: False)
    monkeypatch.setattr(watchdog, "log_action", lambda *a, **k: None)
    assert watchdog.run_ier_engine(conn) == 1
    assert watchdog.run_ier_engine(conn) == 0
    assert len(spawned) == 1
    assert spawned[0]["start_new_session"] is True


class _LockCursor:
    def __init__(self, acquired):
        self.acquired = acquired
        self.statements = []
        self.closed = False

    def execute(self, sql, params):
        self.statements.append((sql, params))

    def fetchone(self):
        return (self.acquired,)

    def close(self):
        self.closed = True


class _LockConn:
    def __init__(self, acquired):
        self.cursors = []
        self.acquired = acquired
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        c = _LockCursor(self.acquired)
        self.cursors.append(c)
        return c

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_enrichment_takes_and_releases_per_symbol_session_lock(modules, monkeypatch):
    _, enrichment = modules
    conn = _LockConn(True)
    called = []
    monkeypatch.setattr(
        enrichment,
        "_enrich_symbol_impl",
        lambda symbol, score, db, force_full=False: (
            called.append((symbol, score, db, force_full, db.commits)) or {"ok": True}
        ),
    )
    assert enrichment.enrich_symbol("abc", 55, conn, force_full=True) == {"ok": True}
    assert called == [("ABC", 55, conn, True, 1)]  # lock probe committed before source writers
    assert "pg_try_advisory_lock" in conn.cursors[0].statements[0][0]
    assert "pg_advisory_unlock" in conn.cursors[1].statements[0][0]
    assert all(cursor.closed for cursor in conn.cursors)
    assert conn.commits == 2  # acquire-boundary commit and post-unlock commit


def test_enrichment_rolls_back_before_unlock_and_preserves_writer_error(modules, monkeypatch):
    _, enrichment = modules

    class AbortedTransactionConn(_LockConn):
        def __init__(self):
            super().__init__(True)
            self.aborted = False

        def cursor(self):
            conn = self

            class Cursor(_LockCursor):
                def execute(self, sql, params):
                    if "pg_advisory_unlock" in sql and conn.aborted:
                        raise RuntimeError("current transaction is aborted")
                    super().execute(sql, params)

            cur = Cursor(self.acquired)
            self.cursors.append(cur)
            return cur

        def rollback(self):
            self.aborted = False
            super().rollback()

    conn = AbortedTransactionConn()
    writer_error = ValueError("source write failed")

    def fail_writer(*args, **kwargs):
        conn.aborted = True
        raise writer_error

    monkeypatch.setattr(enrichment, "_enrich_symbol_impl", fail_writer)
    with pytest.raises(ValueError, match="source write failed") as caught:
        enrichment.enrich_symbol("abc", 55, conn)

    assert caught.value is writer_error
    assert conn.rollbacks == 1
    assert conn.commits == 2
    assert len(conn.cursors) == 2
    assert "pg_advisory_unlock" in conn.cursors[1].statements[0][0]
    assert all(cursor.closed for cursor in conn.cursors)


def test_enrichment_lock_contention_skips_without_running_writer(modules, monkeypatch):
    _, enrichment = modules
    conn = _LockConn(False)
    called = []
    monkeypatch.setattr(enrichment, "_enrich_symbol_impl", lambda *a, **k: called.append(a))
    result = enrichment.enrich_symbol("abc", 55, conn)
    assert result["skipped"] == "already_running"
    assert called == []
    assert len(conn.cursors) == 1 and conn.cursors[0].closed
    assert conn.commits == 1  # close the lock-probe transaction even on contention


def test_enrichment_lock_query_failure_fails_closed(modules, monkeypatch):
    _, enrichment = modules

    class BrokenCursor(_LockCursor):
        def execute(self, sql, params):
            raise RuntimeError("database unavailable")

    class BrokenConn(_LockConn):
        def cursor(self):
            c = BrokenCursor(False)
            self.cursors.append(c)
            return c

    called = []
    monkeypatch.setattr(enrichment, "_enrich_symbol_impl", lambda *a, **k: called.append(a))
    with pytest.raises(RuntimeError, match="database unavailable"):
        conn = BrokenConn(False)
        enrichment.enrich_symbol("ABC", 55, conn)
    assert called == []
    assert conn.cursors[0].closed
