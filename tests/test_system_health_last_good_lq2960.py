"""LQ-20261107-2960: /api/v2/system-health is served last-good-with-age from a background refresh. Hermetic: no DB."""
import sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pytest
import api_v2 as A


@pytest.fixture(autouse=True)
def _reset():
    def clr():
        with A._SH_LOCK:
            A._SH_STATE.update(value=None, computed_at=None, running=None, error=None)
    clr(); yield; clr()


def _wait_idle():
    t = A._SH_STATE["running"]
    if t is not None:
        t.join(5)


def test_first_call_computes_off_thread_and_is_ok(monkeypatch):
    seen = []
    monkeypatch.setattr(A, "_system_health_compute", lambda: seen.append(threading.current_thread().name) or {"db_tables": {"x": 1}})
    d = A._system_health_dashboard()
    assert d["freshness"] == "OK" and d["db_tables"] == {"x": 1} and d["age_s"] < 5
    assert seen == ["system-health-refresh"]  # never the request thread


def test_slow_first_computation_is_unavailable_not_blocking(monkeypatch):
    monkeypatch.setattr(A, "_SH_WAIT_S", 0.2)
    ev = threading.Event()
    monkeypatch.setattr(A, "_system_health_compute", lambda: (ev.wait(5), {"k": 1})[1])
    t0 = time.time(); d = A._system_health_dashboard()
    assert time.time() - t0 < 1.5
    assert d["freshness"] == "UNAVAILABLE" and d["value"] is None and d["refreshing"] is True
    ev.set(); _wait_idle()
    assert A._system_health_dashboard()["freshness"] == "OK"


def test_stale_value_is_served_instantly_with_true_age_while_refresh_runs(monkeypatch):
    monkeypatch.setattr(A, "_system_health_compute", lambda: {"k": 1})
    A._system_health_dashboard()
    ev = threading.Event()
    monkeypatch.setattr(A, "_system_health_compute", lambda: (ev.wait(5), {"k": 2})[1])
    later = A._SH_STATE["computed_at"] + 300
    t0 = time.time(); d = A._system_health_dashboard(now=later)
    assert time.time() - t0 < 1.0
    assert d["freshness"] == "STALE" and d["age_s"] == 300.0 and d["k"] == 1 and d["refreshing"] is True
    ev.set(); _wait_idle()
    assert A._system_health_dashboard()["k"] == 2


def test_failed_refresh_keeps_last_good_and_names_the_failure(monkeypatch):
    monkeypatch.setattr(A, "_system_health_compute", lambda: {"k": 1})
    A._system_health_dashboard()
    def boom(): raise RuntimeError("db down")
    monkeypatch.setattr(A, "_system_health_compute", boom)
    d = A._system_health_dashboard(now=A._SH_STATE["computed_at"] + 120); _wait_idle()
    d = A._system_health_dashboard(now=A._SH_STATE["computed_at"] + 120)
    assert d["k"] == 1 and d["freshness"] == "STALE" and "db down" in d["refresh_error"]


def test_single_flight_one_thread_for_many_callers(monkeypatch):
    n = []; ev = threading.Event()
    monkeypatch.setattr(A, "_SH_WAIT_S", 0.05)
    monkeypatch.setattr(A, "_system_health_compute", lambda: n.append(1) or (ev.wait(5), {"k": 1})[1])
    for _ in range(8): A._system_health_dashboard()
    ev.set(); _wait_idle()
    assert len(n) == 1


def test_never_computed_failure_is_unavailable_with_reason(monkeypatch):
    def boom(): raise RuntimeError("no db")
    monkeypatch.setattr(A, "_system_health_compute", boom)
    d = A._system_health_dashboard(); _wait_idle()
    d = A._system_health_dashboard()
    assert d["freshness"] == "UNAVAILABLE" and "no db" in d["reason"]


def test_compute_uses_pg_class_estimates_not_count_star(monkeypatch):
    sql = []
    def q(s, params=None, fetch="all"):
        sql.append(s); return {"cnt": -1} if "pg_class" in s else ([] if fetch == "all" else {})
    monkeypatch.setattr(A, "_db_query", q); monkeypatch.setattr(A, "_llm_health", lambda: {})
    out = A._system_health_compute()
    assert not [s for s in sql if "COUNT(*) as cnt FROM" in s and "GROUP BY" not in s and "finviz" not in s], sql
    assert all(v is None for v in out["db_tables"].values()) and "estimate" in out["db_tables_basis"]
