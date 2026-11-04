"""BOARD row 78 (operator P0): the Work pipeline's sources must not lie.

Three live defects, each pinned here:
1. the PR census called ``gh`` with no repository, so from the release directory it failed with
   "fatal: not a git repository" and the pipeline's clock froze (last good value Oct 31);
2. a failed ``gh`` call reported only gh's stderr, not which command failed;
3. "231 QUEUED" collapsed three different ownership facts into one number.

Red first: each test below fails on the pre-fix code (no ``--repo`` in the argv; no command in the message; no
``queued_by_owner`` in the summary).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import work_pipeline as W  # noqa: E402


def test_the_pr_census_names_the_repository_on_every_call():
    seen: list[list[str]] = []

    def runner(argv):
        seen.append(argv)
        if argv[:2] == ["gh", "pr"]:
            return "[]", None
        return '{"sha": "0123456789abcdef"}', None

    census = W.PrCensus(runner=runner, release=None)
    census._refresh()
    pr_calls = [a for a in seen if a[:3] in (["gh", "pr", "list"], ["gh", "pr", "view"])]
    assert pr_calls, "no gh pr call was made"
    for argv in pr_calls:
        assert "--repo" in argv, f"gh pr call without --repo: {argv}"
        assert argv[argv.index("--repo") + 1] == W.LC.default_repo()


def test_a_failed_gh_call_says_which_command_failed(monkeypatch):
    class Proc:
        returncode = 1
        stdout = ""
        stderr = "fatal: not a git repository (or any of the parent directories)\n"

    monkeypatch.setattr(W.subprocess, "run", lambda *a, **k: Proc())
    out, warning = W._gh_runner(["gh", "pr", "list", "--repo", "PatsKiller/tardeai", "--state", "open"])
    assert out is None
    assert "gh exited 1" in warning and "--repo" in warning, warning
    assert "not a git repository" in warning


def _item(owner_kind: str) -> dict:
    return {"stage": "queued", "finished": False, "rag": "grey", "who": {"kind": owner_kind},
            "next": {"owner": "agent"}, "waiting_for_batch": False}


def test_the_queued_count_is_split_by_who_owns_it():
    items = [_item("operator")] * 38 + [_item("agent")] * 87 + [_item("none")] * 106
    summary = W.summarize(items)
    assert summary["counts"]["queued"] == 231
    assert summary["queued_by_owner"] == {"operator": 38, "agent": 87, "nobody": 106}, summary["queued_by_owner"]


# ── review R1/R2 (cx-openai-4, 2026-11-04): a source that could not be read must never look fresh ────────────────────

import json as _json
import os as _os
import time as _time


def _coord(tmp_path):
    d = tmp_path / "coordinator"
    (d).mkdir()
    (d / "BOARD.md").write_text("# COORDINATION BOARD\n", encoding="utf-8")
    (d / "pending_operator_decisions.json").write_text(_json.dumps({"updated_at": "2026-11-04T12:00:00Z", "items": []}),
                                                       encoding="utf-8")
    (d / "AUDIT_FIX_QUEUE.json").write_text(_json.dumps({"as_of": "2026-11-04T14:00:00Z", "items": []}), encoding="utf-8")
    return d


def test_a_valid_source_is_ok_with_its_published_clock(tmp_path):
    readers = W.read_coordination_sources(coord_dir=_coord(tmp_path))
    assert readers["audit_queue"]["ok"] is True
    assert readers["audit_queue"]["as_of"].startswith("2026-11-04T14:00:00")
    assert readers["operator_decisions"]["as_of"].startswith("2026-11-04T12:00:00")


def test_a_corrupt_json_source_is_unavailable_and_keeps_no_fresh_clock(tmp_path):
    d = _coord(tmp_path)
    (d / "AUDIT_FIX_QUEUE.json").write_text("{", encoding="utf-8")          # truncated mid-object
    _os.utime(d / "AUDIT_FIX_QUEUE.json", None)                            # ...with a current mtime
    readers = W.read_coordination_sources(coord_dir=d, last_success={"audit_queue": "2026-11-04T10:00:00Z"})
    row = readers["audit_queue"]
    assert row["ok"] is False, row
    assert row["as_of"] is None, "a failed read must not borrow the file mtime"
    assert "not valid JSON" in (row["error"] or "")
    assert row["last_success_at"] == "2026-11-04T10:00:00Z", "the last real success must survive the failure"


def test_a_wrong_shaped_json_source_is_unavailable(tmp_path):
    d = _coord(tmp_path)
    (d / "AUDIT_FIX_QUEUE.json").write_text("[]", encoding="utf-8")
    row = W.read_coordination_sources(coord_dir=d)["audit_queue"]
    assert row["ok"] is False and row["as_of"] is None
    assert "wrong shape" in (row["error"] or "")


def test_a_read_denied_source_is_unavailable(tmp_path):
    d = _coord(tmp_path)
    f = d / "AUDIT_FIX_QUEUE.json"
    f.chmod(0)
    try:
        if _os.access(f, _os.R_OK):  # running as root would defeat the mode; the test still asserts the contract below
            pass
        row = W.read_coordination_sources(coord_dir=d)["audit_queue"]
        assert row["ok"] is False, row
        assert row["as_of"] is None
        assert "read denied" in (row["error"] or "") or "unreadable" in (row["error"] or ""), row["error"]
    finally:
        f.chmod(0o600)


def test_the_persisted_last_success_survives_a_failure(tmp_path):
    d = _coord(tmp_path)
    state = tmp_path / "work_pipeline_sources.json"
    first = W.read_coordination_sources(coord_dir=d)
    W._save_source_state(state, first)
    assert _json.loads(state.read_text())["last_success"]["audit_queue"].startswith("2026-11-04T14:00:00")
    (d / "AUDIT_FIX_QUEUE.json").write_text("{", encoding="utf-8")
    second = W.read_coordination_sources(coord_dir=d, last_success=W._load_source_state(state))
    assert second["audit_queue"]["ok"] is False
    assert second["audit_queue"]["last_success_at"].startswith("2026-11-04T14:00:00"), second["audit_queue"]
