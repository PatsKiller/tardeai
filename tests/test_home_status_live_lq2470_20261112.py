"""LQ-20261107-2470 (REVIEW-2446 B-1): home_status_live.serve is double-checked inside _LOCK, the snapshot read goes
through readonly_query, and both paths share one cache policy. Synthetic data only; no DB, no broker, no network."""

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

NOW = datetime(2026, 11, 14, 17, 0, tzinfo=timezone.utc)
N_THREADS = 8


@pytest.fixture(autouse=True)
def _clean_cache():
    hsl._CACHE.clear()
    yield
    hsl._CACHE.clear()


def _storm(fn, n=N_THREADS):
    barrier = threading.Barrier(n)
    out, errs = [None] * n, []

    def run(i):
        try:
            barrier.wait(5)
            out[i] = fn()
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)

    ts = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join(10) for t in ts]
    assert not errs, errs
    return out


class _FakeConn:
    def rollback(self):
        pass


def _stub_modules(monkeypatch, calls):
    def fake_compute(q, now, **kw):
        calls.append(1)
        time.sleep(0.3)
        return {"verdict": "YES", "computed": True}

    monkeypatch.setattr(hsl, "compute", fake_compute)
    monkeypatch.setattr(hsl, "readonly_query", lambda get_conn, tc: (lambda sql, params=None: []))


def test_poll_storm_computes_once(monkeypatch):
    calls = []
    _stub_modules(monkeypatch, calls)
    out = _storm(lambda: hsl.serve(lambda: _FakeConn(), now=NOW))
    assert len(calls) == 1, f"{len(calls)} computes for {N_THREADS} simultaneous requests"
    assert all(o["verdict"] == "YES" for o in out)


def test_second_wave_after_first_is_all_cache_hits(monkeypatch):
    calls = []
    _stub_modules(monkeypatch, calls)
    hsl.serve(lambda: _FakeConn(), now=NOW)
    _storm(lambda: hsl.serve(lambda: _FakeConn(), now=NOW))
    assert len(calls) == 1


def test_use_cache_false_still_computes_every_time(monkeypatch):
    calls = []
    _stub_modules(monkeypatch, calls)
    hsl.serve(lambda: _FakeConn(), now=NOW, use_cache=False)
    hsl.serve(lambda: _FakeConn(), now=NOW, use_cache=False)
    assert len(calls) == 2


def test_failed_compute_does_not_poison_the_lock_or_cache(monkeypatch):
    calls = []
    _stub_modules(monkeypatch, calls)

    def boom(q, now, **kw):
        calls.append(1)
        raise RuntimeError("provider down")

    monkeypatch.setattr(hsl, "compute", boom)
    out = hsl.serve(lambda: _FakeConn(), now=NOW)
    assert out["verdict"] == "UNKNOWN"
    assert hsl._LOCK.acquire(False), "lock leaked"
    hsl._LOCK.release()


# ---- snapshot path: through readonly_query, cached like the computed path ----------------------------------------

def _snapshot_env(monkeypatch, sqls, *, fail_snapshot=False):
    from scripts.lib import home_trade_ready as htr

    calls = []
    monkeypatch.setattr(hsl, "compute", lambda q, now, **kw: calls.append(1) or {"verdict": "UNKNOWN", "computed": True})

    def fake_ro(get_conn, tc):
        def q(sql, params=None):
            sqls.append(sql)
            if "to_regclass" in sql:
                return [{"present": True}]
            if fail_snapshot:
                raise RuntimeError("snapshot read failed")
            return [{"payload": {}}]
        return q

    monkeypatch.setattr(hsl, "readonly_query", fake_ro)
    served = []

    def fake_served(*, query, mirror, now):
        served.append(1)
        rows = query(htr.SNAPSHOT_SQL)
        return {"state": htr.OK if rows else htr.UNKNOWN, "verdict": "YES"}

    monkeypatch.setattr(htr, "served_status", fake_served)
    monkeypatch.setattr(hsl, "flatten", lambda snap, rf: {"verdict": snap["verdict"], "read_from": rf})
    return calls, served


def _forbidden(*a, **k):
    raise AssertionError("snapshot_query (unbounded _db_query) must not be used")


def test_snapshot_is_read_through_readonly_query_not_snapshot_query(monkeypatch):
    sqls = []
    calls, served = _snapshot_env(monkeypatch, sqls)
    out = hsl.serve(lambda: _FakeConn(), now=NOW, snapshot_query=_forbidden)
    from scripts.lib import home_trade_ready as htr
    assert out["read_from"] == "snapshot" and not calls
    assert htr.SNAPSHOT_SQL in sqls


def test_snapshot_result_is_cached_and_storm_reads_once(monkeypatch):
    sqls = []
    calls, served = _snapshot_env(monkeypatch, sqls)
    _storm(lambda: hsl.serve(lambda: _FakeConn(), now=NOW, snapshot_query=_forbidden))
    assert len(served) == 1, f"{len(served)} snapshot reads for {N_THREADS} requests"


def test_snapshot_not_cached_when_use_cache_false(monkeypatch):
    sqls = []
    calls, served = _snapshot_env(monkeypatch, sqls)
    hsl.serve(lambda: _FakeConn(), now=NOW, snapshot_query=_forbidden, use_cache=False)
    assert "v" not in hsl._CACHE


def test_failed_snapshot_read_falls_through_to_compute(monkeypatch):
    sqls = []
    calls, served = _snapshot_env(monkeypatch, sqls, fail_snapshot=True)
    out = hsl.serve(lambda: _FakeConn(), now=NOW, snapshot_query=_forbidden)
    assert len(calls) == 1 and out["computed"] is True
