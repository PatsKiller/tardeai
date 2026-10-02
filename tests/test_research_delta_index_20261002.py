"""latest_delta: per-symbol index rebuilt only when the store changes.

GET /api/v3/advisory called latest_delta once per desk row and re-parsed the
34 MB research_thesis_deltas.jsonl each time (~35 s per request, 2026-10-02).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import research_prompt_context as rpc  # noqa: E402


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_latest_row_per_symbol_and_parses_once(tmp_path, monkeypatch):
    store = tmp_path / "deltas.jsonl"
    _write(store, [{"symbol": "aaa", "n": 1}, {"symbol": "BBB", "n": 2}, {"symbol": "AAA", "n": 3}])
    monkeypatch.setenv("RESEARCH_THESIS_DELTA_PATH", str(store))
    calls = {"n": 0}
    real = rpc._read_jsonl

    def counting(path):
        calls["n"] += 1
        return real(path)

    monkeypatch.setattr(rpc, "_read_jsonl", counting)
    assert rpc.latest_delta("AAA")["n"] == 3
    assert rpc.latest_delta("bbb")["n"] == 2
    assert rpc.latest_delta("ZZZ") is None
    assert calls["n"] == 1


def test_index_refreshes_when_store_changes(tmp_path, monkeypatch):
    store = tmp_path / "deltas.jsonl"
    _write(store, [{"symbol": "AAA", "n": 1}])
    monkeypatch.setenv("RESEARCH_THESIS_DELTA_PATH", str(store))
    assert rpc.latest_delta("AAA")["n"] == 1
    _write(store, [{"symbol": "AAA", "n": 1}, {"symbol": "AAA", "n": 9}])
    os.utime(store, ns=(store.stat().st_atime_ns, store.stat().st_mtime_ns + 1_000_000))
    assert rpc.latest_delta("AAA")["n"] == 9


def test_returned_row_is_a_copy(tmp_path, monkeypatch):
    store = tmp_path / "deltas.jsonl"
    _write(store, [{"symbol": "AAA", "n": 1}])
    monkeypatch.setenv("RESEARCH_THESIS_DELTA_PATH", str(store))
    rpc.latest_delta("AAA")["n"] = 99
    assert rpc.latest_delta("AAA")["n"] == 1
