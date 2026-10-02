"""Heavy CIO GET compositions: shared TTL, single flight, bounded concurrency.

Step 18 live walk (2026-10-02): loading the CIO overview built brain (~460 MB),
home (~400 MB) and observability (~520 MB) concurrently and wedged
portfolio-server under MemoryHigh=1.5G.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.api_v3_cio as cio  # noqa: E402


def _reset(monkeypatch):
    monkeypatch.setattr(cio, "_HEAVY_CACHE", {})
    monkeypatch.setattr(cio, "_HEAVY_LOCKS", {})


def test_shared_within_ttl_and_rebuilt_after(monkeypatch):
    _reset(monkeypatch)
    calls = {"n": 0}

    def build():
        calls["n"] += 1
        return {"ok": True, "n": calls["n"]}

    assert cio.cached_heavy("t", build, ttl=60)["n"] == 1
    second = cio.cached_heavy("t", build, ttl=60)
    assert second["n"] == 1 and calls["n"] == 1
    assert second["_composition_cache"]["ttl_seconds"] == 60
    assert cio.cached_heavy("t", build, ttl=0)["n"] == 2


def test_failures_are_not_cached(monkeypatch):
    _reset(monkeypatch)
    results = iter([{"ok": False, "error": "x"}, {"ok": True}])
    assert cio.cached_heavy("f", lambda: next(results))["ok"] is False
    assert cio.cached_heavy("f", lambda: next(results))["ok"] is True


def test_at_most_one_heavy_build_at_a_time(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(cio, "_HEAVY_SEM", threading.BoundedSemaphore(1))
    live = {"now": 0, "max": 0}
    guard = threading.Lock()

    def build():
        with guard:
            live["now"] += 1
            live["max"] = max(live["max"], live["now"])
        time.sleep(0.05)
        with guard:
            live["now"] -= 1
        return {"ok": True}

    threads = [threading.Thread(target=cio.cached_heavy, args=(name, build)) for name in ("brain", "home", "observability", "dashboard")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert live["max"] == 1


def test_routes_use_the_guard():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    for name in ("brain", "home", "observability", "investment-product", "dashboard", "desk-note"):
        assert f'_cio.cached_heavy("{name}"' in src, name


def test_options_desk_summary_is_not_raw_json():
    src = (ROOT / "scripts" / "options_research_bridge.py").read_text(encoding="utf-8")
    assert "json.dumps(summary.get('strategy_counts')" not in src
