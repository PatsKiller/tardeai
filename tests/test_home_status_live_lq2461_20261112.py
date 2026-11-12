"""REVIEW-LQ-20261107-2446 B-1 (+ its snapshot-read minor) — home_status_live.serve(). Synthetic data only.

Pins two things the review measured on 9d2965739:

* a cache-miss storm serialises on ``_LOCK``, so the cache must be re-checked *inside* the lock; otherwise the
  provider set runs once per waiting request (the review's harness saw 6 computes for 6 threads);
* the stored-snapshot SELECT must run through ``readonly_query`` (READ ONLY + ``statement_timeout`` + rollback),
  not through the caller's unguarded query helper.

Fail-before on 9d2965739: the storm test sees 6 computes; the snapshot test's caller helper is invoked (it raises).
Pass-after: 1 compute; the snapshot SQL appears in the read-only statement stream.
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib import home_status_live as hsl  # noqa: E402
from scripts.lib import home_trade_ready as htr  # noqa: E402

NOW = datetime(2026, 11, 14, 17, 0, tzinfo=timezone.utc)


def test_miss_storm_runs_the_provider_set_once(monkeypatch):
    computes = []
    start = threading.Barrier(7)

    def slow_compute(*a, **k):
        computes.append(1)
        time.sleep(0.3)  # long enough for every waiter to clear the pre-lock cache check first
        return {"verdict": "NO", "computed": len(computes)}

    monkeypatch.setattr(hsl, "compute", slow_compute)
    hsl._CACHE.clear()
    outs, errors = [], []

    def request():
        try:
            start.wait(timeout=20)
            outs.append(hsl.serve(lambda: None, now=NOW))
        except BaseException as exc:  # noqa: BLE001 -- surfaced below instead of hanging the test
            errors.append(exc)

    threads = [threading.Thread(target=request) for _ in range(6)]
    for t in threads:
        t.start()
    try:
        start.wait(timeout=20)
    except threading.BrokenBarrierError:
        pytest.fail("a request thread died before the barrier")
    for t in threads:
        t.join(timeout=20)
    hsl._CACHE.clear()

    assert not errors, errors
    assert len(outs) == 6
    assert len(computes) == 1, f"the miss storm ran the provider set {len(computes)} times"
    assert all(o["verdict"] == "NO" for o in outs)


def test_snapshot_select_runs_read_only_and_not_via_the_caller_helper(monkeypatch):
    seen, rollbacks = [], []

    class Cur:
        _sql = ""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            seen.append(sql)
            self._sql = sql

        def fetchall(self):
            if self._sql.startswith("SELECT to_regclass"):
                return [{"present": True}]
            return [{"payload": {"sentinel": 1}}]

    class Conn:
        def cursor(self, **k):
            return Cur()

        def rollback(self):
            rollbacks.append(1)

        def commit(self):
            raise AssertionError("a read-only session never commits")

    captured = {}

    def fake_served_status(*, query, mirror, now=None, writer_last_ok_at=None):
        captured["rows"] = query(htr.SNAPSHOT_SQL)
        return {"state": "UNKNOWN", "verdict": "UNKNOWN"}  # not OK -> serve falls through to compute

    def caller_helper(*a, **k):  # the api_v2._db_query shape: unguarded, must not touch the snapshot SELECT
        raise AssertionError("snapshot read used the caller's unguarded query helper")

    monkeypatch.setattr(htr, "served_status", fake_served_status)
    monkeypatch.setattr(hsl, "compute", lambda *a, **k: {"verdict": "NO", "sentinel": 2})
    hsl._CACHE.clear()
    out = hsl.serve(lambda: Conn(), now=NOW, snapshot_query=caller_helper, use_cache=False)
    hsl._CACHE.clear()

    assert captured["rows"] == [{"payload": {"sentinel": 1}}]
    assert "SET TRANSACTION READ ONLY" in seen
    assert any(s.startswith("SET LOCAL statement_timeout") for s in seen)
    assert htr.SNAPSHOT_SQL in seen
    assert len(rollbacks) == 4  # probe + snapshot SELECT, each wrapped by readonly_query's before/after rollback
    assert out["verdict"] == "NO"


def test_snapshot_read_timeout_is_an_unreadable_store_not_a_500(monkeypatch):
    """readonly_query raises on a bad store; served_status must see None (db_readable: false), not an exception."""

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            if sql.startswith("SELECT payload"):
                raise RuntimeError("synthetic snapshot read failure")
            self._sql = sql

        def fetchall(self):
            return [{"present": True}]

    class Conn:
        def cursor(self, **k):
            return Cur()

        def rollback(self):
            pass

    captured = {}

    def fake_served_status(*, query, mirror, now=None, writer_last_ok_at=None):
        captured["rows"] = query(htr.SNAPSHOT_SQL)
        return {"state": "UNKNOWN", "verdict": "UNKNOWN"}

    monkeypatch.setattr(htr, "served_status", fake_served_status)
    monkeypatch.setattr(hsl, "compute", lambda *a, **k: {"verdict": "UNKNOWN", "sentinel": 3})
    hsl._CACHE.clear()
    out = hsl.serve(lambda: Conn(), now=NOW, snapshot_query=object(), use_cache=False)
    hsl._CACHE.clear()

    assert captured["rows"] is None
    assert out["sentinel"] == 3
