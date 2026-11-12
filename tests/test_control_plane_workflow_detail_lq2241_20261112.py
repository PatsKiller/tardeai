"""LQ-20261107-2241: /workflows/<id> must not retain the whole lineage (synthetic fixtures only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import scripts.control_plane_api as api


def _lineage(tmp_path, monkeypatch, lines):
    d = tmp_path / "data" / "cio"
    d.mkdir(parents=True)
    (d / "cio_workflow_lineage.jsonl").write_text("".join(
        (l if isinstance(l, str) else json.dumps(l)) + "\n" for l in lines))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(api, "_domain_paths", lambda domain: (d / "cio_workflow_lineage.jsonl",))


def _typed(n_other=50):
    rows = []
    for i in range(n_other):
        w = f"wf_other_{i}"
        rows += [{"record_type": "envelope", "workflow_id": w, "checkpoint_id": f"c{i}"},
                 {"record_type": "node", "workflow_id": w, "node_id": f"n{i}", "node_type": "Research"},
                 {"record_type": "edge", "workflow_id": w, "from": "a", "to": "b"}]
    rows += [{"record_type": "envelope", "workflow_id": "wf_target", "research_request_id": "rr_1", "checkpoint_id": "c1"},
             {"record_type": "node", "workflow_id": "wf_target", "node_id": "node_tgt_a", "node_type": "Alpha"},
             {"record_type": "node", "workflow_id": "wf_target", "node_id": "n2", "node_type": "Alpha"},
             {"record_type": "edge", "workflow_id": "wf_target", "from": "node_tgt_a", "to": "n2"},
             {"record_type": "envelope", "workflow_id": "wf_target", "checkpoint_id": "c2"}]
    return rows


def _detail(wf):
    return api.handle(f"/api/v3/control-plane/workflows/{wf}", query={})


def test_detail_retains_only_the_requested_workflow(tmp_path, monkeypatch):
    _lineage(tmp_path, monkeypatch, _typed())
    seen = {"max": 0}
    real = api._read_jsonl

    def spy(path, **kw):
        out = real(path, **kw)
        seen["max"] = max(seen["max"], len(out[0] if isinstance(out, tuple) else out))
        return out
    monkeypatch.setattr(api, "_read_jsonl", spy)
    status, body = _detail("wf_target")
    assert status == 200
    # fail-before: the old code retained all 155 rows in one read
    assert seen["max"] <= 5, seen


def _strip(resp):
    status, body = resp
    body = json.loads(json.dumps(body, default=str))
    body.pop("as_of", None)
    return status, body


def _legacy(monkeypatch):
    """The pre-fix load: every row of the lineage, unfiltered."""
    monkeypatch.setattr(api, "_workflow_rows_for", lambda wf, info=None: api._select_rows(api._domain_paths("workflows"), domain=""))


FIXTURES = {
    "typed": lambda: _typed(),
    "typed_dup_envelopes": lambda: _typed(2) + [{"record_type": "envelope", "workflow_id": "wf_target", "checkpoint_id": "c3", "event_id": "ev9"}],
    "untyped": lambda: [{"workflow_id": f"w{i}", "status": "ok", "research_request_id": f"r{i}"} for i in range(20)],
    "typed_plus_no_workflow_id_rows": lambda: _typed(2) + [{"status": "orphan", "workflow_id": ""}],
    "typed_store_with_untyped_workflow": lambda: _typed(3) + [
        {"workflow_id": "wf_legacy", "status": "ok", "identifiers": {"research_request_id": "lg1"}},
        {"workflow_id": "wf_legacy", "status": "done"}],
    "no_workflow_id_anywhere": lambda: [{"id": "wf_target", "status": "x"}, {"id": "other"}],
}


@pytest.mark.parametrize("name", sorted(FIXTURES))
@pytest.mark.parametrize("wf", ["wf_target", "rr_1", "ev9", "node_tgt_a", "w7", "r7", "wf_nope", "wf_legacy", "lg1"])
def test_detail_body_equals_legacy_whole_store_load(tmp_path, monkeypatch, name, wf):
    _lineage(tmp_path, monkeypatch, FIXTURES[name]())
    new = _strip(_detail(wf))
    _legacy(monkeypatch)
    old = _strip(_detail(wf))
    assert new == old


def test_detail_result_shape_typed(tmp_path, monkeypatch):
    _lineage(tmp_path, monkeypatch, _typed())
    status, body = _detail("wf_target")
    assert status == 200
    text = json.dumps(body, sort_keys=True)
    assert "wf_other_" not in text and "node_tgt_a" in text and "n2" in text


def test_detail_matches_by_non_workflow_id_identifier(tmp_path, monkeypatch):
    _lineage(tmp_path, monkeypatch, _typed())
    status, body = _detail("rr_1")
    item = body["data"]["item"] if "item" in body["data"] else body["data"]
    assert status == 200 and item["workflow_id"] == "wf_target"


def test_detail_untyped_rows_still_match(tmp_path, monkeypatch):
    rows = [{"workflow_id": f"w{i}", "status": "ok"} for i in range(30)]
    _lineage(tmp_path, monkeypatch, rows)
    status, body = _detail("w7")
    item = body["data"]["item"] if "item" in body["data"] else body["data"]
    assert status == 200 and item["workflow_id"] == "w7"


def test_detail_unknown_workflow_is_not_found_not_crash(tmp_path, monkeypatch):
    _lineage(tmp_path, monkeypatch, _typed(3))
    status, _ = _detail("wf_nope")
    assert status in (404, 200)


def test_one_corrupt_line_is_degraded_and_counted(tmp_path, monkeypatch):
    # LQ-20261107-2407 changed the strict read: the list already tolerated a few corrupt lines, the detail now does too.
    rows = _typed(3)
    rows.insert(4, "{not json")
    _lineage(tmp_path, monkeypatch, rows)
    status, body = _detail("wf_target")
    assert body["data_quality"] == "DEGRADED"
    assert body["data"]["meta"]["skipped_corrupt_lines"] == 1


def test_many_corrupt_lines_are_still_invalid_schema(tmp_path, monkeypatch):
    rows = _typed(3)
    for _ in range(12):  # above _corrupt_limit (max(10, lines // 1000))
        rows.insert(4, "{not json")
    _lineage(tmp_path, monkeypatch, rows)
    status, body = _detail("wf_target")
    assert "INVALID" in json.dumps(body.get("data_quality", ""))


def test_detail_found_by_node_derived_identifier(tmp_path, monkeypatch):
    _lineage(tmp_path, monkeypatch, _typed())
    status, body = _detail("node_tgt_a")
    assert status == 200
    assert "wf_target" in json.dumps(body) and "wf_other_" not in json.dumps(body)


def _spy_max_rows(monkeypatch):
    seen = {"max": 0}
    real = api._read_jsonl

    def spy(path, **kw):
        out = real(path, **kw)
        seen["max"] = max(seen["max"], len(out[0] if isinstance(out, tuple) else out))
        return out
    monkeypatch.setattr(api, "_read_jsonl", spy)
    return seen


def test_untyped_workflow_in_a_typed_store_is_decided_by_the_whole_store(tmp_path, monkeypatch):
    """REVIEW-2261 F2: the typed/legacy decision must come from the whole store, not the retained subset."""
    _lineage(tmp_path, monkeypatch, FIXTURES["typed_store_with_untyped_workflow"]())
    status, body = _detail("wf_legacy")
    assert status == 200
    # absolute: the old code grouped it (the store is typed), so the default class is the typed one
    assert body["data"]["evidence_class"] == "OPERATOR_REQUESTED_LIVE", body["data"]


def test_untyped_path_retains_only_matching_rows(tmp_path, monkeypatch):
    """REVIEW-2261 M3: a pure untyped store must also stream (nothing else asserted retention there)."""
    _lineage(tmp_path, monkeypatch, [{"workflow_id": f"w{i}", "status": "ok", "research_request_id": f"r{i}"} for i in range(200)])
    seen = _spy_max_rows(monkeypatch)
    status, body = _detail("w7")
    assert status == 200
    assert seen["max"] <= 3, seen


def _json_lineage(tmp_path, monkeypatch, rows):
    d = tmp_path / "data" / "cio"
    d.mkdir(parents=True)
    f = d / "cio_workflow_lineage.json"
    f.write_text(json.dumps(rows))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(api, "_domain_paths", lambda domain: (f,))


def test_typed_json_lineage_is_grouped_like_the_whole_store_load(tmp_path, monkeypatch):
    """REVIEW-2272 M8: a .json store is not streamed (no survey), so ``store_typed`` must come from the whole
    rows, not stay False: typed rows give nodes, the envelope and OPERATOR_REQUESTED_LIVE."""
    _json_lineage(tmp_path, monkeypatch, _typed(3))
    status, body = _detail("wf_target")
    assert status == 200
    data = body["data"]
    assert data["evidence_class"] == "OPERATOR_REQUESTED_LIVE", data
    assert [n["node_id"] for n in data["nodes"]] == ["node_tgt_a", "n2"], data["nodes"]
    assert data["envelope"] is not None
    new = _strip((status, body))
    _legacy(monkeypatch)
    assert new == _strip(_detail("wf_target"))
