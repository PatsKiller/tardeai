"""REQUEST_ISOLATION_SWR_20261107 (LQ-20261107-259): stale-while-revalidate for isolated reads."""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import request_isolation as ri  # noqa: E402


def _stub(monkeypatch, calls, delay=0.0):
    def fake(module, fn, kwargs, deadline):
        calls.append(time.monotonic())
        time.sleep(delay)
        return {"n": len(calls)}

    monkeypatch.setattr(ri, "_run_child", fake)
    ri.clear_cache()


def test_stale_result_returns_at_once_and_refreshes_once(monkeypatch):
    calls: list = []
    _stub(monkeypatch, calls, delay=0.3)
    first = ri.run_isolated("m", "f", ttl=0.05, stale_ttl=60)
    assert first == {"n": 1}
    time.sleep(0.1)  # past ttl, inside stale window
    t = time.monotonic()
    a = ri.run_isolated("m", "f", ttl=0.05, stale_ttl=60)
    b = ri.run_isolated("m", "f", ttl=0.05, stale_ttl=60)
    assert time.monotonic() - t < 0.2, "a stale hit must not wait for the child"
    assert a["served_stale"] and a["n"] == 1 and b["served_stale"]
    time.sleep(0.6)
    assert len(calls) == 2, "exactly one background refresh"
    assert ri.run_isolated("m", "f", ttl=60, stale_ttl=60) == {"n": 2}


def test_without_stale_ttl_expiry_is_a_blocking_recompute(monkeypatch):
    calls: list = []
    _stub(monkeypatch, calls)
    ri.run_isolated("m", "f", ttl=0.05)
    time.sleep(0.1)
    assert ri.run_isolated("m", "f", ttl=0.05) == {"n": 2}


def test_older_than_stale_window_recomputes_in_the_foreground(monkeypatch):
    calls: list = []
    _stub(monkeypatch, calls)
    ri.run_isolated("m", "f", ttl=0.05, stale_ttl=0.1)
    time.sleep(0.2)
    assert ri.run_isolated("m", "f", ttl=0.05, stale_ttl=0.1) == {"n": 2}


def test_failed_refresh_keeps_the_stale_answer(monkeypatch):
    ri.clear_cache()
    seq = iter([{"ok": 1}, {"isolation_failure": True, "status": "TIMEOUT"}])
    monkeypatch.setattr(ri, "_run_child", lambda *a, **k: next(seq, {"isolation_failure": True}))
    ri.run_isolated("m", "f", ttl=0.05, stale_ttl=60)
    time.sleep(0.1)
    ri.run_isolated("m", "f", ttl=0.05, stale_ttl=60)
    time.sleep(0.2)
    again = ri.run_isolated("m", "f", ttl=0.05, stale_ttl=60)
    assert again["ok"] == 1 and again["served_stale"]


def test_surface_authority_is_registered_stale_ok():
    assert ri.STALE_OK_SEC["control_plane_surface_authority"] >= 600
    assert threading.active_count() >= 1
