"""ANCHOR: CONTROL_PLANE_WORKFLOWS_INDEX_LQ2407_20261112 — workflow LIST holds an offset index; DETAIL tolerates a torn line.

LQ-20261107-2407 (design LQ-2398 c1+c2). LIST keeps ``workflow_id -> (offset, length)`` and parses only the page
(no process-wide row cache, no deepcopy). DETAIL streams and skips corrupt complete lines like the list does
(``meta.skipped_corrupt_lines``, DEGRADED) instead of INVALID_SCHEMA for every workflow. Synthetic fixtures only.
"""
from __future__ import annotations

import json
import sys
import tracemalloc
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.control_plane_api as api

PAD = "x" * 600


def _env(wf, ck, **kw):
    return {"record_type": "envelope", "workflow_id": wf, "checkpoint_id": ck, "pad": PAD, **kw}


def _fixture(n=300, dup=3, torn_at=None):
    """n workflows, each with ``dup`` envelopes (the last is the latest) plus node/edge rows; optional torn line."""
    lines = []
    for ck in range(dup):
        for i in range(n):
            wf = f"wf_{i:04d}"
            lines.append(_env(wf, f"c{ck}"))
            if ck == 0:
                lines.append({"record_type": "node", "workflow_id": wf, "node_id": f"n{i}", "node_type": "R"})
                lines.append({"record_type": "edge", "workflow_id": wf, "from": "a", "to": "b"})
    if torn_at is not None:
        lines.insert(torn_at, '{"record_type": "node", "workflow_id": "wf_0001", "node_id": "n1", {"record_type": "edge"')
    return lines


def _put(tmp_path, monkeypatch, lines, tail=""):
    d = tmp_path / "data" / "cio"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "cio_workflow_lineage.jsonl"
    p.write_text("".join((l if isinstance(l, str) else json.dumps(l)) + "\n" for l in lines) + tail)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(api, "_domain_paths", lambda domain: (p,))
    api._jsonl_cache_clear()
    getattr(api, "_wf_index_clear", lambda: None)()
    return p


def _list(query=None):
    return api.handle("/api/v3/control-plane/workflows", query=query or {})


def _detail(wf):
    return api.handle(f"/api/v3/control-plane/workflows/{wf}", query={})


def _old_list(monkeypatch, query=None):
    """The same request through the pre-index full read."""
    with monkeypatch.context() as m:
        m.setattr(api, "_workflow_page_from_index", lambda *a, **k: None, raising=False)
        api._jsonl_cache_clear()
        return _list(query)


def _norm(resp):
    status, body = resp
    return status, {k: v for k, v in body.items() if k != "as_of"}


def _items(resp):
    return (resp[1].get("data") or {})


@pytest.mark.parametrize("query", [{}, {"limit": "7"}, {"limit": "7", "offset": "290"}, {"limit": "200", "offset": "250"},
                                   {"offset": "9999"}, {"limit": "1", "offset": "0"}])
def test_list_page_equals_the_full_read(tmp_path, monkeypatch, query):
    _put(tmp_path, monkeypatch, _fixture())
    new = _list(query)
    old = _old_list(monkeypatch, query)
    assert _norm(new) == _norm(old)
    assert _items(new)["pagination"]["total"] == 300
    if not query.get("offset") == "9999":
        assert all(r["checkpoint_id"] == "c2" for r in _items(new)["items"])  # the latest envelope wins


def test_list_equals_the_full_read_with_a_torn_line_and_reports_it(tmp_path, monkeypatch):
    _put(tmp_path, monkeypatch, _fixture(torn_at=40))
    new = _list({"limit": "50", "offset": "100"})
    old = _old_list(monkeypatch, {"limit": "50", "offset": "100"})
    assert _norm(new) == _norm(old)
    assert _items(new)["skipped_corrupt_lines"] == 1


def test_list_torn_final_line_is_answered_and_never_cached(tmp_path, monkeypatch):
    p = _put(tmp_path, monkeypatch, _fixture(n=5, dup=1), tail=json.dumps(_env("wf_new", "c9"))[:-1])
    first = _items(_list())
    assert first["pagination"]["total"] == 5  # a half-written final line is not a workflow yet
    p.write_text(p.read_text() + "}\n")  # the append completes
    second = _items(_list())
    assert second["pagination"]["total"] == 6
    assert second["items"][-1]["workflow_id"] == "wf_new"


def test_list_resumes_after_an_append_and_rescans_after_a_rewrite(tmp_path, monkeypatch):
    p = _put(tmp_path, monkeypatch, _fixture(n=10, dup=1))
    assert _items(_list())["pagination"]["total"] == 10
    with p.open("a") as fh:
        fh.write(json.dumps(_env("wf_0003", "c7")) + "\n" + json.dumps(_env("wf_extra", "c1")) + "\n")
    got = _items(_list({"limit": "200"}))
    assert got["pagination"]["total"] == 11
    assert next(r for r in got["items"] if r["workflow_id"] == "wf_0003")["checkpoint_id"] == "c7"
    p.write_text(json.dumps(_env("wf_only", "c1")) + "\n")  # shorter file: full re-scan
    got = _items(_list())
    assert [r["workflow_id"] for r in got["items"]] == ["wf_only"]
    assert got == _items(_old_list(monkeypatch))


def test_untyped_store_falls_back_to_the_full_read(tmp_path, monkeypatch):
    _put(tmp_path, monkeypatch, [{"workflow_id": "a", "x": 1}, {"workflow_id": "b", "x": 2}])
    assert _norm(_list()) == _norm(_old_list(monkeypatch))
    assert _items(_list())["pagination"]["total"] == 2


def test_index_holds_no_rows(tmp_path, monkeypatch):
    _put(tmp_path, monkeypatch, _fixture())
    _list()
    assert hasattr(api, "_wf_index_cache"), "no offset index"
    entry = next(iter(api._wf_index_cache.values()))
    assert len(entry["index"]) == 300
    assert all(isinstance(v, tuple) and len(v) == 2 for v in entry["index"].values())
    assert not api._jsonl_cache  # nothing went through the row cache


def test_list_peak_is_small_on_a_realistic_fixture(tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), "PAD", "x" * 4000)  # ~2.5k workflows x 4 KB latest envelope: ~10 MB of rows
    p = _put(tmp_path, monkeypatch, _fixture(n=2500, dup=3, torn_at=200))
    size_mb = p.stat().st_size / 1e6
    assert size_mb > 5, size_mb
    tracemalloc.start()
    _list()  # cold: builds the index
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 10e6, (peak, size_mb)
    assert cur < 5e6, ("retained after the call", cur)
    # the full read holds the projection: far more than the index path
    getattr(api, "_wf_index_clear", lambda: None)()
    tracemalloc.start()
    _old_list(monkeypatch)
    old_cur, old_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert old_cur > 3 * cur and old_peak > 3 * peak, (old_cur, cur, old_peak, peak)


def _torn_detail_fixture():
    rows = _fixture(n=20, dup=2)
    rows.insert(5, '{"record_type": "node", "workflow_id": "wf_0001", "node_id": "n1", {"record_type": "edge"')
    return rows


def test_detail_with_a_corrupt_line_is_degraded_not_invalid_schema(tmp_path, monkeypatch):
    _put(tmp_path, monkeypatch, _torn_detail_fixture())
    status, body = _detail("wf_0001")
    assert status == 200
    assert body["data_quality"] == "DEGRADED", body["data_quality"]
    assert body["data"]["meta"]["skipped_corrupt_lines"] == 1
    assert body["data"]["workflow_id"] == "wf_0001"


def test_detail_unknown_workflow_with_a_corrupt_line_is_degraded_and_says_why(tmp_path, monkeypatch):
    _put(tmp_path, monkeypatch, _torn_detail_fixture())
    status, body = _detail("wf_nope")
    assert body["data_quality"] == "DEGRADED"
    assert body["data"]["meta"]["skipped_corrupt_lines"] == 1


def test_detail_clean_file_is_unchanged_and_has_no_skip_meta(tmp_path, monkeypatch):
    _put(tmp_path, monkeypatch, _fixture(n=20, dup=2))
    status, body = _detail("wf_0001")
    assert status == 200
    assert body["data_quality"] != "INVALID_SCHEMA"
    assert "skipped_corrupt_lines" not in (body["data"].get("meta") or {})


def test_detail_over_the_corrupt_limit_stays_invalid_schema(tmp_path, monkeypatch):
    rows = _fixture(n=5, dup=1)
    bad = ['{"torn": '] * 40  # far above max(10, lines // 1000)
    _put(tmp_path, monkeypatch, rows[:3] + bad + rows[3:])
    status, body = _detail("wf_0001")
    assert body["data_quality"] == "INVALID_SCHEMA"


def test_workflow_less_envelope_with_a_leftover_row_falls_back_to_the_full_read(tmp_path, monkeypatch):
    _put(tmp_path, monkeypatch, [{"record_type": "envelope", "checkpoint_id": "c1"}, {"x": 1, "workflow_id": ""}])
    assert _norm(_list()) == _norm(_old_list(monkeypatch))


def test_in_place_rewrite_that_is_not_shorter_is_rescanned(tmp_path, monkeypatch):
    p = _put(tmp_path, monkeypatch, [_env(f"old_{i}", "c1") for i in range(5)])
    assert [r["workflow_id"] for r in _items(_list())["items"]][0] == "old_0"
    ino = p.stat().st_ino
    with p.open("r+") as fh:  # same inode, longer, different head
        fh.write("".join(json.dumps(_env(f"new_{i}", "c1")) + "\n" for i in range(9)))
    assert p.stat().st_ino == ino
    got = _items(_list())
    assert [r["workflow_id"] for r in got["items"]] == [f"new_{i}" for i in range(9)]
    # the index itself was rebuilt (the page-read check alone would also mask a stale index by falling back)
    assert list(next(iter(api._wf_index_cache.values()))["index"]) == [f"new_{i}" for i in range(9)]


def test_valid_final_envelope_without_newline_is_listed_then_continues(tmp_path, monkeypatch):
    p = _put(tmp_path, monkeypatch, _fixture(n=3, dup=1), tail=json.dumps(_env("wf_tail", "c1")))
    got = _items(_list())
    assert got["pagination"]["total"] == 4 and got["items"][-1]["workflow_id"] == "wf_tail"
    with p.open("a") as fh:
        fh.write("\n" + json.dumps(_env("wf_after", "c1")) + "\n")
    got = _items(_list())
    assert [r["workflow_id"] for r in got["items"]][-2:] == ["wf_tail", "wf_after"]
    assert got["pagination"]["total"] == 5
