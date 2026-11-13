"""MEM-CONTAIN 2026-11-13 (TEMPORARY CONTAINMENT): global + host-wide build cap, memory guard, per-key dedupe,
last-good on failure, scope-separated keys, and no request-thread build for the wired heavy GETs. Synthetic only."""
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from scripts.lib import shared_get_swr as swr

ROOT = Path(__file__).resolve().parents[1]
_REAL_CGROUP_MEMORY = swr.cgroup_memory


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SWR_SLOT_DIR", raising=False)
    monkeypatch.setenv("SWR_MEMORY_GUARD_PCT", "85")
    monkeypatch.setattr(swr, "cgroup_memory", lambda: (None, None))  # fail-open unless a test says otherwise
    swr.clear()
    yield
    deadline = time.time() + 5
    while swr.running_builds() and time.time() < deadline:
        time.sleep(0.02)
    swr.clear()


def _wait_idle(timeout=5):
    deadline = time.time() + timeout
    while swr.running_builds() and time.time() < deadline:
        time.sleep(0.01)


def _gated(calls, gate, value=None):
    def build():
        calls.append(threading.current_thread().name)
        gate.wait(10)
        return value if value is not None else {"v": len(calls)}
    return build


def test_n_concurrent_identical_requests_start_one_build():
    calls, gate = [], threading.Event()
    out, barrier = [], threading.Barrier(30)

    def req():
        barrier.wait()
        out.append(swr.get("k", 60, _gated(calls, gate)))

    ts = [threading.Thread(target=req) for _ in range(30)]
    [t.start() for t in ts]
    [t.join(5) for t in ts]
    assert len(out) == 30 and len(calls) == 1
    gate.set()
    _wait_idle()
    assert swr.get("k", 60, _gated(calls, gate))["v"] == 1


def test_global_cap_across_keys_is_respected_and_nothing_queues(monkeypatch, capsys):
    monkeypatch.setenv("SWR_MAX_CONCURRENT_BUILDS", "2")
    calls, gate = [], threading.Event()
    outs = [swr.get(f"k{i}", 60, _gated(calls, gate), route=f"/r{i}") for i in range(5)]
    assert len(calls) == 2 and swr.running_builds() == 2
    assert [o["reason"] for o in outs[2:]] == ["build_deferred"] * 3
    assert all(o["build_refused"] == "REFUSED_CAP" for o in outs[2:])
    assert sorted(swr.inflight()) == ["k0", "k1"]  # refused keys did not queue a thread
    gate.set()
    _wait_idle()
    lines = [json.loads(ln.split(" ", 1)[1]) for ln in capsys.readouterr().out.splitlines()
             if ln.startswith("[swr-build] ")]
    assert sum(1 for d in lines if d["outcome"] == "REFUSED_CAP") == 3
    assert sum(1 for d in lines if d["outcome"] == "BUILT") == 2
    built = next(d for d in lines if d["outcome"] == "BUILT")
    for f in ("key", "route", "start", "end", "build_ms", "rss_kb_before", "rss_kb_after", "counters"):
        assert f in built
    # a refused key builds on a later poll once a slot frees
    assert swr.get("k4", 60, _gated(calls, gate))["reason"] == "building"


def test_memory_guard_refuses_to_start_and_records_it(monkeypatch, capsys):
    monkeypatch.setattr(swr, "cgroup_memory", lambda: (2_300_000_000, 2_684_354_560))  # 85.7 %
    calls = []
    out = swr.get("k", 60, lambda: calls.append(1) or {"x": 1}, route="/api/v2/x")
    assert calls == [] and out["status"] == "UNKNOWN" and out["reason"] == "build_deferred"
    assert out["build_refused"] == "REFUSED_MEMORY"
    st = swr.stats()
    assert st["routes"]["/api/v2/x"]["refused_memory"] == 1 and st["refused"]["k"]["outcome"] == "REFUSED_MEMORY"
    assert "REFUSED_MEMORY" in capsys.readouterr().out
    monkeypatch.setattr(swr, "cgroup_memory", lambda: (1_000_000_000, 2_684_354_560))  # 37 %: allowed again
    swr.get("k", 60, lambda: calls.append(1) or {"x": 1})
    _wait_idle()
    assert calls == [1]


def test_memory_guard_fails_open_when_unreadable(monkeypatch):
    def boom():
        raise OSError("no cgroup")
    monkeypatch.setattr(swr, "cgroup_memory", boom)
    calls = []
    swr.get("k", 60, lambda: calls.append(1) or {"x": 1})
    _wait_idle()
    assert calls == [1]


def test_cgroup_reader_uses_proc_self_cgroup(tmp_path, monkeypatch):
    cg = tmp_path / "sys" / "user.slice" / "x.service"
    cg.mkdir(parents=True)
    (cg / "memory.current").write_text("100\n")
    (cg / "memory.high").write_text("max\n")
    monkeypatch.setattr(swr, "_CGROUP_DIR", [str(cg)])
    assert _REAL_CGROUP_MEMORY() == (100, None)  # "max" = no limit = fail open
    (cg / "memory.high").write_text("200\n")
    assert _REAL_CGROUP_MEMORY() == (100, 200)
    monkeypatch.setattr(swr, "_CGROUP_DIR", [None])
    assert _REAL_CGROUP_MEMORY() == (None, None)


def test_failed_build_keeps_last_good():
    swr.get("k", 0.01, lambda: {"good": 1})
    _wait_idle()
    time.sleep(0.05)

    def bad():
        raise RuntimeError("db down")
    swr.get("k", 0.01, bad)
    _wait_idle()
    out = swr.get("k", 0.01, bad)
    assert out["good"] == 1 and out["stale"] is True and "db down" in out["last_build_error"]


def test_older_build_never_overwrites_newer_result():
    swr._store("k", {"gen": "new"}, started=200.0)
    swr._store("k", {"gen": "old"}, started=100.0)
    assert swr.peek("k", 60) == {"gen": "new"}


def test_entries_are_bounded(monkeypatch):
    monkeypatch.setenv("SWR_MAX_ENTRIES", "3")
    for i in range(6):
        swr._store(f"k{i}", {"i": i}, started=float(i))
    assert swr.peek("k0", 60) is None and swr.peek("k5", 60) == {"i": 5}


def test_host_slot_pool_two_os_processes(tmp_path):
    """Two separate OS processes share the slot dir: with cap 1 only one builds; the same key never builds twice."""
    script = tmp_path / "proc.py"
    script.write_text(textwrap.dedent(f"""
        import json, os, sys, time
        sys.path.insert(0, {str(ROOT)!r})
        from scripts.lib import shared_get_swr as swr
        swr.cgroup_memory = lambda: (None, None)
        key, hold = sys.argv[1], float(sys.argv[2])
        out = swr.get(key, 60, lambda: time.sleep(hold) or {{"pid": os.getpid()}})
        print("RESULT " + json.dumps({{"reason": out.get("reason"), "refused": out.get("build_refused")}}), flush=True)
        t0 = time.time()
        while swr.running_builds() and time.time() - t0 < 10:
            time.sleep(0.02)
    """))
    env = dict(os.environ, SWR_SLOT_DIR=str(tmp_path / "slots"), SWR_MAX_CONCURRENT_BUILDS="1")
    env.pop("PYTEST_CURRENT_TEST", None)

    def run_pair(k1, k2):
        a = subprocess.Popen([sys.executable, str(script), k1, "2"], env=env, stdout=subprocess.PIPE, text=True)
        time.sleep(0.7)  # a holds its slot (and its key lock) for 2 s
        b = subprocess.run([sys.executable, str(script), k2, "0"], env=env, capture_output=True, text=True, timeout=30)
        a_out, _ = a.communicate(timeout=30)
        res = lambda s: json.loads(next(ln for ln in s.splitlines() if ln.startswith("RESULT "))[7:])  # noqa: E731
        return res(a_out), res(b.stdout)

    a, b = run_pair("product-A|principal=p1", "product-B|principal=p1")  # different keys, cap 1
    assert a["reason"] == "building" and b == {"reason": "build_deferred", "refused": "REFUSED_CAP"}
    a, b = run_pair("product-A|principal=p1", "product-A|principal=p1")  # same key in two processes
    assert a["reason"] == "building" and b == {"reason": "build_deferred", "refused": "REFUSED_DUPLICATE"}
    # the kernel released every slot when the processes ended: a third process builds at once
    c = subprocess.run([sys.executable, str(script), "product-A|principal=p1", "0"], env=env, capture_output=True,
                       text=True, timeout=30)
    assert '"reason": "building"' in c.stdout and '"refused": null' in c.stdout


def test_slot_pool_unusable_dir_fails_open(tmp_path, monkeypatch):
    f = tmp_path / "not_a_dir"
    f.write_text("x")
    monkeypatch.setenv("SWR_SLOT_DIR", str(f / "slots"))
    calls = []
    swr.get("k", 60, lambda: calls.append(1) or {"x": 1})
    _wait_idle()
    assert calls == [1]
