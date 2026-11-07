"""LQ-20261107-177 (latency half, T-20261107-9bf308): the agents GET parses only what was appended.

Measured on the live host 2026-11-07 (GET-only, ``127.0.0.1:7777``): ``/api/v3/control-plane/agents``
took 5-17 s cold and 10.3 s at 14:38 ET, because ``_read_jsonl`` JSON-parsed every line of the 138 MB,
ever-growing ``data/cio/agent_run_traces.jsonl`` on every request to keep one row per agent.

A tail read would drop agents that have not woken recently (an AVAILABLE envelope over partial data,
the defect the other half of this item fixes). Instead a compacting read resumes from the byte offset it
reached last time, starting from the compacted rows it kept. The compactor is idempotent and already
runs mid-stream, so resuming is the same computation as one long stream. Pinned here:

* an append costs only the appended lines, and the result equals a fresh full read;
* truncation, rotation (a new inode) and an in-place rewrite each fall back to a full read;
* a torn final line answers exactly as a full read does (INVALID_SCHEMA), is never cached, and the
  completed line is picked up next time;
* a corrupt line is never cached as AVAILABLE;
* callers cannot mutate the cache through the rows they are handed;
* a reader without a compactor (a plain list) is unchanged: no cache.

COVERS = ["scripts/control_plane_api.py"]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.control_plane_api as api  # noqa: E402


def _trace(i: int, agent: str | None = None, status: str = "completed") -> dict:
    return {
        "agent": agent or f"a{i % 3}",
        "role": "material_scan",
        "started_at": f"2026-11-07T{i // 60 % 24:02d}:{i % 60:02d}:00Z",
        "ended_at": f"2026-11-07T{i // 60 % 24:02d}:{i % 60:02d}:04Z",
        "status": status,
        "trigger": "material_scan",
        "trace_id": f"tr_{i}",
        "decision": {"current_action": "WAIT", "decision_id": f"dec_{i}"},
    }


def _lines(rows: list[dict]) -> str:
    return "".join(json.dumps(r) + "\n" for r in rows)


class _CountingJson:
    """Delegates to ``json`` and counts ``loads`` (the per-line parse)."""

    def __init__(self) -> None:
        self.loads_calls = 0

    def loads(self, s, *a, **kw):
        self.loads_calls += 1
        return json.loads(s, *a, **kw)

    def __getattr__(self, name):
        return getattr(json, name)


@pytest.fixture
def counting(monkeypatch):
    c = _CountingJson()
    monkeypatch.setattr(api, "json", c)
    api._jsonl_cache_clear()
    yield c
    api._jsonl_cache_clear()


def _read(path: Path):
    return api._read_jsonl(path, compact=api._agents_from_traces)


def _full(path: Path):
    """What an uncached read answers for this file right now."""
    api._jsonl_cache_clear()
    try:
        return _read(path)
    finally:
        api._jsonl_cache_clear()


def test_an_append_parses_only_the_appended_lines(tmp_path, counting):
    path = tmp_path / "agent_run_traces.jsonl"
    path.write_text(_lines([_trace(i) for i in range(500)]), encoding="utf-8")
    first, q1 = _read(path)
    assert q1 == "AVAILABLE" and counting.loads_calls >= 500

    with path.open("a", encoding="utf-8") as fh:
        fh.write(_lines([_trace(i, status="failed" if i == 501 else "completed") for i in (500, 501, 502)]))
    counting.loads_calls = 0
    second, q2 = _read(path)
    assert q2 == "AVAILABLE"
    assert counting.loads_calls == 3, f"re-parsed {counting.loads_calls} lines for a 3-line append"
    assert second == _full(path)[0]


def test_an_unchanged_file_is_not_parsed_again(tmp_path, counting):
    path = tmp_path / "agent_run_traces.jsonl"
    path.write_text(_lines([_trace(i) for i in range(50)]), encoding="utf-8")
    first, _ = _read(path)
    counting.loads_calls = 0
    again, _ = _read(path)
    assert counting.loads_calls == 0 and again == first


@pytest.mark.parametrize("every", [2, 7, 5000])
def test_many_appends_match_a_full_read(tmp_path, counting, monkeypatch, every):
    monkeypatch.setattr(api, "_JSONL_COMPACT_EVERY", every)
    path = tmp_path / "agent_run_traces.jsonl"
    path.write_text("", encoding="utf-8")
    i = 0
    for batch in (1, 4, 0, 9, 2, 13):
        with path.open("a", encoding="utf-8") as fh:
            fh.write(
                _lines([_trace(i + k, status="failed" if (i + k) % 5 == 0 else "completed") for k in range(batch)])
            )
        i += batch
        got = _read(path)
        assert got == _full(path), f"diverged after {i} rows"


def test_truncation_falls_back_to_a_full_read(tmp_path, counting):
    path = tmp_path / "agent_run_traces.jsonl"
    path.write_text(_lines([_trace(i) for i in range(30)]), encoding="utf-8")
    _read(path)
    path.write_text(_lines([_trace(0, agent="solo")]), encoding="utf-8")
    rows, q = _read(path)
    assert q == "AVAILABLE" and [r["agent_id"] for r in rows] == ["solo"]


def test_rotation_to_a_new_file_falls_back_to_a_full_read(tmp_path, counting):
    path = tmp_path / "agent_run_traces.jsonl"
    path.write_text(_lines([_trace(i) for i in range(3)]), encoding="utf-8")
    _read(path)
    fresh = tmp_path / "next.jsonl"
    fresh.write_text(_lines([_trace(i, agent="rotated") for i in range(40)]), encoding="utf-8")
    os.replace(fresh, path)
    rows, _ = _read(path)
    assert [r["agent_id"] for r in rows] == ["rotated"]


def test_an_in_place_rewrite_of_the_same_size_is_not_served_stale(tmp_path, counting):
    path = tmp_path / "agent_run_traces.jsonl"
    path.write_text(_lines([_trace(i, agent="aaaa") for i in range(20)]), encoding="utf-8")
    _read(path)
    # Same byte length, same inode, different content.
    path.write_text(_lines([_trace(i, agent="bbbb") for i in range(20)]), encoding="utf-8")
    rows, _ = _read(path)
    assert [r["agent_id"] for r in rows] == ["bbbb"]


def test_a_torn_final_line_answers_like_a_full_read_and_is_picked_up_when_complete(tmp_path, counting):
    path = tmp_path / "agent_run_traces.jsonl"
    whole = json.dumps(_trace(7, agent="late")) + "\n"
    path.write_text(_lines([_trace(i) for i in range(6)]) + whole[:25], encoding="utf-8")
    assert _read(path) == _full(path)
    assert _read(path)[1] == "INVALID_SCHEMA"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(whole[25:])
    rows, q = _read(path)
    assert q == "AVAILABLE" and "late" in {r["agent_id"] for r in rows}
    assert (rows, q) == _full(path)


def test_a_complete_final_line_without_a_newline_is_read(tmp_path, counting):
    path = tmp_path / "agent_run_traces.jsonl"
    path.write_text(_lines([_trace(i) for i in range(4)]) + json.dumps(_trace(9, agent="nonl")), encoding="utf-8")
    rows, q = _read(path)
    assert q == "AVAILABLE" and "nonl" in {r["agent_id"] for r in rows}
    assert (rows, q) == _full(path)


def test_a_corrupt_line_is_never_cached_as_available(tmp_path, counting):
    path = tmp_path / "agent_run_traces.jsonl"
    path.write_text(_lines([_trace(1)]) + "{not json\n" + _lines([_trace(2)]), encoding="utf-8")
    assert _read(path) == (None, "INVALID_SCHEMA")
    assert _read(path) == (None, "INVALID_SCHEMA")


def test_callers_cannot_mutate_the_cache(tmp_path, counting):
    path = tmp_path / "agent_run_traces.jsonl"
    path.write_text(_lines([_trace(i) for i in range(9)]), encoding="utf-8")
    rows, _ = _read(path)
    rows[0]["agent_id"] = "tampered"
    rows.append({"agent_id": "extra"})
    again, _ = _read(path)
    assert {r["agent_id"] for r in again} == {"a0", "a1", "a2"}


def test_a_read_without_a_compactor_is_not_cached(tmp_path, counting):
    path = tmp_path / "plain.jsonl"
    path.write_text(_lines([{"k": i} for i in range(5)]), encoding="utf-8")
    api._read_jsonl(path)
    counting.loads_calls = 0
    rows, q = api._read_jsonl(path)
    assert q == "AVAILABLE" and len(rows) == 5 and counting.loads_calls == 5


def test_the_agents_endpoint_reads_the_appended_wake(tmp_path, counting, monkeypatch):
    for name in ("TRADEAI_STATE_ROOT", "TRADEAI_ROOT", "TRADEAI_PERSISTENT_STATE_ROOT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    path = cio / "agent_run_traces.jsonl"
    path.write_text(_lines([_trace(i, agent="alex") for i in range(200)]), encoding="utf-8")
    status, body = api.handle("/api/v3/control-plane/agents")
    assert status == 200 and body["data"]["items"][0]["last_artifact"] == "tr_199"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(_lines([_trace(200, agent="alex")]))
    counting.loads_calls = 0
    status, body = api.handle("/api/v3/control-plane/agents")
    assert body["data"]["items"][0]["last_artifact"] == "tr_200"
    assert counting.loads_calls < 50, counting.loads_calls
