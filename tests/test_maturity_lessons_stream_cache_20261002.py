"""collect_lessons streams the 270 MB KB store and caches until inputs change.

/api/v3/maturity/learning peaked at ~910 MB per request on 2026-10-02 and,
with concurrent CIO page loads, pushed portfolio-server past MemoryHigh=1.5G.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.lib.maturity_control.lessons as L  # noqa: E402


def _root(tmp_path: Path) -> Path:
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    (tmp_path / "data" / "cio").mkdir(parents=True)
    return tmp_path


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_latest_row_per_id_and_application_count(tmp_path, monkeypatch):
    root = _root(tmp_path)
    rt = root / "data" / "runtime"
    _write(rt / "advisory_kb_lessons.jsonl", [
        {"id": "L1", "status": "candidate", "title": "old"},
        {"id": "L1", "status": "candidate", "title": "new"},
        {"id": "L2", "status": "candidate", "title": "two"},
    ])
    _write(rt / "advisory_kb_lesson_applications.jsonl", [{"lesson_id": "L1"}, {"lesson_id": "L2"}])
    monkeypatch.setattr(L, "load_json_map", lambda *_a, **_k: {})
    monkeypatch.setitem(L._LESSONS_CACHE, "key", None)
    out = L.collect_lessons(root=root)
    assert {r["lesson_id"]: r["title"] for r in out["lessons"]} == {"L1": "new", "L2": "two"}
    assert out["application_events"] == 2


def test_cached_until_inputs_change_and_copies_returned(tmp_path, monkeypatch):
    root = _root(tmp_path)
    store = root / "data" / "runtime" / "advisory_kb_lessons.jsonl"
    _write(store, [{"id": "L1", "status": "candidate", "title": "a"}])
    monkeypatch.setattr(L, "load_json_map", lambda *_a, **_k: {})
    monkeypatch.setitem(L._LESSONS_CACHE, "key", None)
    calls = {"n": 0}
    real = L._collect_lessons

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(L, "_collect_lessons", counting)
    first = L.collect_lessons(root=root)
    first["lessons"][0]["title"] = "mutated by caller"
    assert L.collect_lessons(root=root)["lessons"][0]["title"] == "a"
    assert calls["n"] == 1
    _write(store, [{"id": "L1", "status": "candidate", "title": "b"}])
    os.utime(store, ns=(store.stat().st_atime_ns, store.stat().st_mtime_ns + 1_000_000))
    assert L.collect_lessons(root=root)["lessons"][0]["title"] == "b"
    assert calls["n"] == 2
