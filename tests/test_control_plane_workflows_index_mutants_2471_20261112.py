"""LQ-20261107-2471 — tests that close the LQ-2464 review's surviving index mutants (M2, M3, M4, M6, M9).

REVIEW-LQ-20261107-2464 (cc-sonnet-3) ran 14 mutants against fae33284c and killed 9; M2 (fingerprint
invalidation), M3 (shorter-file invalidation), M4 (inode invalidation), M6 (corrupt limit in the index
builder) and M9 ("the file moved under the index" guard) survived because no test distinguishes their
absence. Each test below removes exactly one such protection from the decision path and asserts the
error the protection exists to prevent:

* M6  an over-limit corrupt file must be INVALID_SCHEMA, never a partial AVAILABLE page.
* M2  an in-place rewrite that changes the head must be rescanned even though the size is unchanged.
* M4  a replacement file (new inode) with the same size and the same fingerprint windows but a
      different middle line must be rescanned.
* M9  when a stale index points at a line that is no longer the envelope it was indexed as, the page
      must fall back to the full read instead of serving whatever is there.
* M3  a shorter file must be rescanned even when the fingerprint happens to match. Under blake2b a
      truncation practically always changes the fingerprint, so the size check is defence in depth;
      this test simulates the collision it guards against by pinning ``_jsonl_fingerprint``.

Synthetic fixtures only; no live server, no DB, no network, no broker.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.control_plane_api as api

PAD = "x" * 600


def _env(wf, ck="c1"):
    return {"record_type": "envelope", "workflow_id": wf, "checkpoint_id": ck, "pad": PAD}


def _fixture(n):
    return [_env(f"wf_{i:04d}") for i in range(n)]


def _put(tmp_path, monkeypatch, lines):
    d = tmp_path / "data" / "cio"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "cio_workflow_lineage.jsonl"
    p.write_text("".join(json.dumps(line) + "\n" for line in lines))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(api, "_domain_paths", lambda domain: (p,))
    api._jsonl_cache_clear()
    api._wf_index_clear()
    return p


def _list(query=None):
    return api.handle("/api/v3/control-plane/workflows", query=query or {})


def _data(resp):
    return resp[1]["data"]


def _line(value):
    return json.dumps(value) + "\n"


def _same_length(envelope_line, value):
    """``value`` serialised to exactly the byte length of ``envelope_line`` (padding its ``pad``)."""
    target = len(envelope_line)
    value = dict(value)
    value["pad"] = ""
    extra = target - len(json.dumps(value))
    assert extra >= 0, (target, len(json.dumps(value)))
    value["pad"] = "y" * extra
    out = json.dumps(value)
    assert len(out) == target
    return out


def _replace_line(path, index, replacement_text):
    """Rewrite one line in place, same inode, same total size (caller guarantees equal length)."""
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    assert len(lines[index]) == len(replacement_text)
    lines[index] = replacement_text
    with path.open("r+") as handle:
        handle.seek(0)
        handle.write("".join(lines))
        handle.truncate()


def test_over_limit_corrupt_file_is_invalid_schema_not_a_partial_page(tmp_path, monkeypatch):
    # M6: with the builder's corrupt-limit check removed the index has envelopes to serve, so LIST would
    # answer AVAILABLE with a page and total 5 instead of the full read's INVALID_SCHEMA / total 0.
    rows = _fixture(5)
    bad = ['{"torn": '] * 40  # complete non-JSON lines, far above max(10, lines // 1000)
    _put(tmp_path, monkeypatch, rows[:2] + bad + rows[2:])
    status, body = _list()
    assert body["data_quality"] == "INVALID_SCHEMA"
    assert body["data"]["items"] == []
    assert body["data"]["pagination"]["total"] == 0


def test_same_size_rewrite_with_a_changed_head_is_rescanned(tmp_path, monkeypatch):
    # M2: same inode, same size, so only the fingerprint check can notice the rewrite.
    p = _put(tmp_path, monkeypatch, _fixture(40))
    assert _data(_list())["pagination"]["total"] == 40  # build the index
    first = json.dumps(_env("wf_0000"))
    node = _same_length(first, {"record_type": "node", "workflow_id": "wf_0000", "node_id": "n0"})
    assert p.stat().st_size == sum(len(l) for l in (_line(e) for e in _fixture(40)))
    _replace_line(p, 0, node + "\n")
    got = _data(_list({"limit": "1", "offset": "1"}))
    # The served line (wf_0001) still matches the stale index; only the rebuild exposes the change.
    assert got["pagination"]["total"] == 39
    assert [r["workflow_id"] for r in got["items"]] == ["wf_0002"]


def test_replacement_file_with_a_new_inode_is_rescanned(tmp_path, monkeypatch):
    # M4: os.replace gives a new inode; size and both fingerprint windows (head, before the offset) are
    # unchanged because the changed line is in the middle, so only the dev/ino check notices.
    p = _put(tmp_path, monkeypatch, _fixture(40))
    assert _data(_list())["pagination"]["total"] == 40
    lines = [_line(e) for e in _fixture(40)]
    lines[20] = _same_length(json.dumps(_env("wf_0020")),
                             {"record_type": "node", "workflow_id": "wf_0020", "node_id": "n20"}) + "\n"
    other = p.with_name(p.name + ".new")
    other.write_text("".join(lines))
    assert other.stat().st_size == p.stat().st_size
    os.replace(other, p)
    got = _data(_list({"limit": "1"}))
    assert got["pagination"]["total"] == 39
    assert [r["workflow_id"] for r in got["items"]] == ["wf_0000"]


def test_a_line_that_moved_under_the_index_falls_back_to_the_full_read(tmp_path, monkeypatch):
    # M9: middle line changed in place (same inode, same size, outside both fingerprint windows). The
    # index is stale; its offset now holds a node row. Without the guard the page would serve that row
    # as an item and report the stale total.
    p = _put(tmp_path, monkeypatch, _fixture(40))
    assert _data(_list())["pagination"]["total"] == 40
    node = _same_length(json.dumps(_env("wf_0020")),
                        {"record_type": "node", "workflow_id": "wf_0020", "node_id": "n20"})
    _replace_line(p, 20, node + "\n")
    status, body = _list()
    assert body["data_quality"] == "AVAILABLE"
    got = body["data"]
    assert got["pagination"]["total"] == 39
    assert {r["record_type"] for r in got["items"]} == {"envelope"}
    assert "wf_0020" not in [r["workflow_id"] for r in got["items"]]


def test_shorter_file_is_rescanned_even_when_the_fingerprint_matches(tmp_path, monkeypatch):
    # M3: the size check is defence in depth behind the fingerprint. A blake2b collision (or a
    # truncation crafted so both windows still match) is the one case only the size check catches; pin
    # the fingerprint to simulate it. The served lines are all still valid, so only total differs.
    monkeypatch.setattr(api, "_jsonl_fingerprint", lambda handle, offset: "collision")
    p = _put(tmp_path, monkeypatch, _fixture(40))
    assert _data(_list({"limit": "5"}))["pagination"]["total"] == 40
    p.write_text("".join(_line(e) for e in _fixture(20)))  # truncate in place: same inode, shorter
    got = _data(_list({"limit": "5"}))
    assert got["pagination"]["total"] == 20
    assert [r["workflow_id"] for r in got["items"]] == [f"wf_{i:04d}" for i in range(5)]
