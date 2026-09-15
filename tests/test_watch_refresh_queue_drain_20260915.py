"""2026-09-15: stale QUEUED refresh jobs get a worker; decision packets never carry NaN into PostgreSQL."""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Cur:
    def __init__(self, swept, orphaned):
        self._swept, self._orphaned, self._last = swept, orphaned, None

    def execute(self, sql, params=None):
        self._last = sql

    def fetchall(self):
        return self._swept

    def fetchone(self):
        return (self._orphaned,)


class _Conn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur

    def commit(self):
        pass


@pytest.fixture()
def wdr():
    return _load("wdr_t", "scripts/watch_decision_refresh.py")


def test_orphaned_queue_without_worker_spawns_drain(monkeypatch, wdr):
    monkeypatch.setattr(wdr, "_conn", lambda: _Conn(_Cur([], 573)))
    monkeypatch.setattr(wdr, "_refresh_worker_running", lambda: False)
    spawned = []
    monkeypatch.setattr(wdr, "_spawn_workers", lambda n: spawned.append(n) or n)
    out = wdr.sweep_stale()
    assert out["stale_queued"] == 573
    assert spawned == [wdr.WORKERS_PER_RUN] and out["workers_spawned"] == wdr.WORKERS_PER_RUN


def test_live_worker_means_no_second_spawn(monkeypatch, wdr):
    monkeypatch.setattr(wdr, "_conn", lambda: _Conn(_Cur([], 12)))
    monkeypatch.setattr(wdr, "_refresh_worker_running", lambda: True)
    monkeypatch.setattr(wdr, "_spawn_workers", lambda n: pytest.fail("must not spawn while a worker is alive"))
    assert wdr.sweep_stale()["workers_spawned"] == 0


def test_no_orphans_no_spawn(monkeypatch, wdr):
    monkeypatch.setattr(wdr, "_conn", lambda: _Conn(_Cur([], 0)))
    monkeypatch.setattr(wdr, "_refresh_worker_running", lambda: False)
    monkeypatch.setattr(wdr, "_spawn_workers", lambda n: pytest.fail("nothing to drain"))
    assert wdr.sweep_stale()["workers_spawned"] == 0


def test_spawn_count_never_exceeds_orphans(monkeypatch, wdr):
    monkeypatch.setattr(wdr, "_conn", lambda: _Conn(_Cur([], 1)))
    monkeypatch.setattr(wdr, "_refresh_worker_running", lambda: False)
    got = []
    monkeypatch.setattr(wdr, "_spawn_workers", lambda n: got.append(n) or n)
    wdr.sweep_stale()
    assert got == [1]


def test_worker_detection_is_false_for_this_process(wdr):
    assert wdr._refresh_worker_running() in (True, False)


def test_scheduler_run_calls_sweep_before_planning():
    src = (ROOT / "scripts" / "watch_decision_scheduler.py").read_text(encoding="utf-8")
    assert src.index("swept = wdr.sweep_stale()") < src.index("plan = build_plan(conn)\n    out =")


def test_packet_json_replaces_nan_and_infinity():
    svc = _load("sds_t", "scripts/shadow_decision_service.py")
    packet = {"a": float("nan"), "b": [1.0, float("inf"), {"c": -float("inf")}], "d": "ok", "e": 2.5}
    text = svc._pg_json(packet)
    assert "NaN" not in text and "Infinity" not in text
    assert json.loads(text) == {"a": None, "b": [1.0, None, {"c": None}], "d": "ok", "e": 2.5}


def test_packet_insert_uses_finite_json():
    src = (ROOT / "scripts" / "shadow_decision_service.py").read_text(encoding="utf-8")
    assert "_pg_json(packet), packet.get(\"source_commit_sha\")" in src
    assert "json.dumps(packet, default=str), packet.get(\"source_commit_sha\")" not in src
