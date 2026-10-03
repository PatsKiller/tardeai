"""Heavy CIO compositions: one shared, serialised, re-entrant build slot.

2026-10-03: one /v3/cio overview load composed `home` three times at once
(/home, /observability, and brain inside observability). Two overlapping loads
pushed portfolio-server past MemoryHigh and systemd restarted it.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

import scripts.api_v3_cio as A  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_cache():
    A._HEAVY_CACHE.clear()
    yield
    A._HEAVY_CACHE.clear()


def test_hit_returns_fresh_top_level_copy_so_serving_stamp_never_sticks():
    first = A.cached_heavy("x", lambda: {"ok": True, "v": 1})
    first["_serving"] = {"pin": "stale"}
    second = A.cached_heavy("x", lambda: {"ok": True, "v": 2})
    assert second["v"] == 1
    assert "_serving" not in second
    assert second["_composition_cache"]["name"] == "x"


def test_concurrent_callers_build_once():
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        time.sleep(0.2)
        return {"ok": True}

    threads = [threading.Thread(target=A.cached_heavy, args=("same", build)) for _ in range(5)]
    [t.start() for t in threads]
    [t.join(5) for t in threads]
    assert calls["n"] == 1


def test_different_compositions_never_build_concurrently():
    live = {"now": 0, "max": 0}
    guard = threading.Lock()

    def build():
        with guard:
            live["now"] += 1
            live["max"] = max(live["max"], live["now"])
        time.sleep(0.1)
        with guard:
            live["now"] -= 1
        return {"ok": True}

    threads = [threading.Thread(target=A.cached_heavy, args=(f"n{i}", build)) for i in range(4)]
    [t.start() for t in threads]
    [t.join(5) for t in threads]
    assert live["max"] == 1


def test_nested_composition_reuses_the_slot_without_deadlock():
    inner_calls = {"n": 0}

    def inner():
        inner_calls["n"] += 1
        return {"ok": True, "inner": True}

    def outer():
        return {"ok": True, "inner": A.cached_heavy("inner", inner)["inner"]}

    done = {}
    t = threading.Thread(target=lambda: done.setdefault("r", A.cached_heavy("outer", outer)))
    t.start()
    t.join(5)
    assert not t.is_alive(), "nested heavy build deadlocked"
    assert done["r"]["inner"] is True
    assert A.cached_heavy("inner", inner)["inner"] is True
    assert inner_calls["n"] == 1


def test_failures_and_non_dicts_are_never_cached():
    seq = iter([{"ok": False, "error": "boom"}, {"ok": True, "v": 1}])
    assert A.cached_heavy("f", lambda: next(seq))["ok"] is False
    assert A.cached_heavy("f", lambda: next(seq))["v"] == 1
    assert A.cached_heavy("g", lambda: None) is None
    assert "g" not in A._HEAVY_CACHE


def test_ttl_expiry_rebuilds():
    vals = iter([{"ok": True, "v": 1}, {"ok": True, "v": 2}])
    assert A.cached_heavy("t", lambda: next(vals), ttl=0.05)["v"] == 1
    time.sleep(0.08)
    assert A.cached_heavy("t", lambda: next(vals), ttl=0.05)["v"] == 2


def test_busy_slot_times_out_honestly(monkeypatch):
    monkeypatch.setattr(A, "_HEAVY_WAIT_SEC", 0.05)
    held = threading.Event()
    release = threading.Event()

    def holder():
        with A._HEAVY_LOCK:
            held.set()
            release.wait(2)

    t = threading.Thread(target=holder)
    t.start()
    held.wait(2)
    try:
        out = A.cached_heavy("busy", lambda: {"ok": True})
    finally:
        release.set()
        t.join(2)
    assert out["ok"] is False and out["error"] == "composition_busy"


def test_overview_fan_out_builds_home_once(monkeypatch):
    import scripts.lib.cio_observability as obs
    import scripts.lib.current_pin_integrity as pin

    home_builds = {"n": 0}

    def home():
        home_builds["n"] += 1
        time.sleep(0.15)
        return {"ok": True, "cio_now": {}}

    def brain():
        # The real brain composes home too; it must reuse the shared build.
        return {"ok": True, "home_seen": bool(A.cached_heavy("home", A.get_cio_home)), "_serving": {"pin_match": True}}

    monkeypatch.setattr(A, "get_cio_home", home)
    monkeypatch.setattr(A, "get_cio_brain_v1", brain)
    monkeypatch.setattr(A, "get_agent_research_ops", lambda: {"ok": True})
    monkeypatch.setattr(A, "get_data_health_v1", lambda: {"ok": True})
    monkeypatch.setattr(obs, "build_observability", lambda **kw: {"ok": True, "brain_home": kw["brain"]["home_seen"]})
    monkeypatch.setattr(pin, "collect_process_freshness", lambda: {"ok": True})

    out = {}
    threads = [
        threading.Thread(target=lambda: out.setdefault("home", A.cached_heavy("home", A.get_cio_home))),
        threading.Thread(target=lambda: out.setdefault("obs", A.cached_heavy("observability", A.get_cio_observability))),
    ]
    [t.start() for t in threads]
    [t.join(5) for t in threads]
    assert out["home"]["ok"] is True and out["obs"]["brain_home"] is True
    assert home_builds["n"] == 1


def test_api_census_resolves_the_producer_behind_cached_heavy():
    import cio_api_contract_census as census

    lines = [
        '                if p == "brain":',
        '                    return 200, _cio.cached_heavy("brain", _cio.get_cio_brain_v1)',
        '                if p == "desk-note":',
        '                    return 200, _cio.cached_heavy("desk-note", _cio.get_cio_desk_note, ttl=300.0)',
    ]
    aliases = {"_cio": "api_v3_cio.py"}
    assert census._producer_after(lines, 0, aliases) == "api_v3_cio.py::get_cio_brain_v1"
    assert census._producer_after(lines, 2, aliases) == "api_v3_cio.py::get_cio_desk_note"
