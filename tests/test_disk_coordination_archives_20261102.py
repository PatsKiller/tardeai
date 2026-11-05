"""Archived coordination records never hold a disk candidate (2026-11-02).

``agent_claim.py compact`` archives an ended claim to ``claims/claims_history.jsonl`` and an ended worklog to
``claims/worklog_archive/``; both keep the absolute paths they mention. The standing scan used to read them,
so closing a claim moved its references instead of dropping them and ``~/.cache/rtc`` scratch stayed held by
claims closed days earlier. AGENTS.md §24.13 makes the hold a *live* claim or worklog; an archive is neither.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts import disk_hygiene as DH

NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


def _coord(tmp_path):
    base = tmp_path / "coordination"
    (base / "claims").mkdir(parents=True)
    (base / "worklogs").mkdir()
    (base / "handoffs").mkdir()
    (base / "handoffs" / "PROGRESS_LOG.md").write_text("progress log\n")
    return base


def _claim(base, claim_id, worktree, status="active"):
    (base / "claims" / f"{claim_id}.json").write_text(json.dumps({
        "schema": "AgentClaim@v1", "claim_id": claim_id, "status": status,
        "worktree": str(worktree), "session": claim_id,
    }))
    return claim_id


def test_is_archived_coordination_paths():
    assert DH.is_archived_coordination("claims/claims_history.jsonl")
    assert DH.is_archived_coordination("claims/worklog_archive/a.worklog.md")
    assert not DH.is_archived_coordination("claims/20261102T000000Z-claude-abc.json")
    assert not DH.is_archived_coordination("worklogs/20261102T000000Z-claude-abc.md")
    assert not DH.is_archived_coordination("handoffs/PROGRESS_LOG.md")
    # A lookalike name outside the archive is not archived.
    assert not DH.is_archived_coordination("claims/notes/claims_history.jsonl")


def test_live_claim_holds_but_archives_do_not(tmp_path):
    base = _coord(tmp_path)
    live_path = tmp_path / "scratch" / "live-held"
    archived_only = tmp_path / "scratch" / "archived-held"
    worklog_archived = tmp_path / "scratch" / "worklog-archived"

    _claim(base, "20261102T000000Z-claude-live", live_path)
    (base / "claims" / "claims_history.jsonl").write_text(
        json.dumps({"claim_id": "20261101T000000Z-claude-old", "status": "done",
                    "worktree": str(archived_only)}) + "\n")
    (base / "claims" / "worklog_archive").mkdir()
    (base / "claims" / "worklog_archive" / "20261101T000000Z-claude-old.worklog.md").write_text(
        f"# worklog\n- scratch: {worklog_archived}\n")

    out = DH.scan_coordination(base, NOW)
    refs = out["references"]

    assert str(live_path) in refs, "a live claim must still hold its worktree"
    assert str(archived_only) not in refs, "an archived claim must not hold a path"
    assert str(worklog_archived) not in refs, "an archived worklog must not hold a path"
    assert [c["claim_id"] for c in out["live_claims"]] == ["20261102T000000Z-claude-live"]
    assert out["archived_files"] == 2


def test_archived_symlink_does_not_refuse_the_scan(tmp_path):
    base = _coord(tmp_path)
    _claim(base, "20261102T000000Z-claude-live", tmp_path / "scratch" / "x")
    target = tmp_path / "target.md"
    target.write_text("x\n")
    (base / "claims" / "worklog_archive").mkdir()
    (base / "claims" / "worklog_archive" / "link.md").symlink_to(target)

    out = DH.scan_coordination(base, NOW)  # archived, so never read and never a symlink refusal
    assert str(target) not in out["references"]


def test_history_growing_past_the_scan_limit_is_ignored(tmp_path, monkeypatch):
    """A large archive must not turn every standing apply into coordination_scan_limit."""
    base = _coord(tmp_path)
    _claim(base, "20261102T000000Z-claude-live", tmp_path / "scratch" / "x")
    big = base / "claims" / "claims_history.jsonl"
    big.write_bytes(b"x" * (33 * 1024 * 1024))  # over the 32 MiB per-file cap

    out = DH.scan_coordination(base, NOW)  # skipped before the size accounting
    assert out["archived_files"] == 1
    assert out["live_claims"]


def test_released_claim_is_not_live(tmp_path):
    base = _coord(tmp_path)
    gone = tmp_path / "scratch" / "released"
    _claim(base, "20261102T000000Z-claude-done", gone, status="done")

    out = DH.scan_coordination(base, NOW)
    assert out["live_claims"] == []
    # Still a coordination document while it sits in claims/, so its path is still a reference until compaction.
    assert str(gone) in out["references"]
