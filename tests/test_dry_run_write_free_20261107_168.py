"""LQ-20261107-168: the five NEEDS_DRY_MODE lanes accept a write-free --dry-run.

Each lane's --dry-run must exit 0, print a DRY-RUN line, and perform no write: no lane receipt, no
non-SELECT SQL, no HTTP request. The receipt writer, requests and every non-SELECT statement are stubbed to
raise, so any write or network reach fails the test.

The wave-3 contract is kept: an explicit --dry-run does not change to a DB-reading preview.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


class _Boom(AssertionError):
    pass


class RecordingDB:
    """Stands in for db_adapter's connection: records SQL, returns no rows."""

    def __init__(self):
        self.sql: list[str] = []
        self.description = None
        self.readonly = False

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def close(self):
        pass

    def rollback(self):
        pass

    def commit(self):
        raise _Boom("dry run committed a transaction")

    def set_session(self, readonly=False):
        self.readonly = readonly


@pytest.fixture
def no_writes(monkeypatch):
    """Receipt writer, HTTP, and DB writes all raise if a dry run reaches them."""
    import lib.lane_last_receipt as lr
    import requests

    def _refuse(name):
        def f(*a, **k):
            raise _Boom(f"dry run reached a write/network path: {name}")
        return f

    monkeypatch.setattr(lr, "write_lane_receipt", _refuse("write_lane_receipt"))
    monkeypatch.setattr(requests, "get", _refuse("requests.get"))
    monkeypatch.setattr(requests, "post", _refuse("requests.post"))
    rec = RecordingDB()
    import db_adapter

    monkeypatch.setattr(db_adapter, "_get_conn", lambda: rec, raising=False)
    monkeypatch.setattr(db_adapter, "USE_DB", True, raising=False)

    def _execute(sql, params=None, fetch="all"):
        head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        if head not in ("SELECT", "WITH"):
            raise _Boom(f"dry run sent a non-SELECT statement: {sql.strip()[:80]}")
        rec.sql.append(sql)
        return (1,) if fetch == "one" else []

    monkeypatch.setattr(db_adapter, "_execute", _execute, raising=False)
    return rec


@pytest.mark.parametrize(
    "module, entry, marker",
    [
        ("aegis_transcript_discovery", "cli", "DRY-RUN aegis-transcript-discovery"),
        ("drain_discovery_backlog", "main", "DRY-RUN drain-discovery-backlog"),
        ("finviz_proactive_research", "main", "DRY-RUN"),
        ("hermes_social_sentiment", "main", "DRY-RUN"),
        ("sync_social_to_intelligence", "main", "DRY-RUN"),
    ],
)
def test_dry_run_writes_nothing(module, entry, marker, no_writes, capsys):
    fn = getattr(importlib.import_module(module), entry)
    rc = fn(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert marker in out, out
    assert all(s.lstrip().split(None, 1)[0].upper() in ("SELECT", "WITH") for s in no_writes.sql if s.strip())


def test_sync_dry_run_wins_over_apply(no_writes, capsys):
    """--dry-run wins over --apply: the sync lane must not fold or write a receipt."""
    import sync_social_to_intelligence as sts

    rc = sts.main(["--dry-run", "--apply"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "DRY-RUN sync-social-to-intelligence" in out
    assert no_writes.sql == []
