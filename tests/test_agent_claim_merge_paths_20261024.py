"""Merge precommit scopes: real local git, isolated claim board, pinned clock, no remote or DB."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import agent_claim as CLI
from scripts.lib import agent_claim_board as B

NOW = datetime(2026, 10, 24, 4, 0, tzinfo=timezone.utc)
OWN = ["own.txt", "own added.txt", "deleted.txt"]
INHERITED = ["inherited.txt", "main added.txt"]


def _git(repo: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL"}}
    env.update(
        HOME=str(repo.parent),
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_AUTHOR_DATE="2026-10-24T04:00:00Z",
        GIT_COMMITTER_DATE="2026-10-24T04:00:00Z",
    )
    return subprocess.run(
        ["git", "-c", "core.hooksPath=" + os.devnull, *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def setup(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Merge fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    for path in ("own.txt", "inherited.txt", "deleted.txt"):
        (repo / path).write_text("base\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "work")
    (repo / "own.txt").write_text("my change\n")
    (repo / "own added.txt").write_text("my addition\n")
    (repo / "deleted.txt").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "own work")
    _git(repo, "checkout", "main")
    (repo / "inherited.txt").write_text("main changed this\n")
    (repo / "main added.txt").write_text("main addition\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "main work")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "checkout", "work")
    _git(repo, "merge", "--no-ff", "--no-commit", "main")
    board = B.ClaimBoard(tmp_path / "claims", now=lambda: NOW)
    policy = tmp_path / "policy.md"
    policy.write_text(
        "```\nPolicy-Version: 20.1.0\nStatus: ACTIVE\n```\n\n"
        "| Version | Date | Status | Class | Summary | Approval |\n"
        "|---|---|---|---|---|---|\n"
        "| 20.1.0 | 2026-10-23 | ACTIVE | MINOR | fixture | operator |\n"
    )
    monkeypatch.chdir(repo)
    monkeypatch.setattr(CLI, "_board", lambda args: board)
    monkeypatch.delenv(B.ENV_OVERRIDE, raising=False)
    return repo, board, policy


def _claim(board, session, paths, branch):
    row = board.claim(vendor="codex", session=session, agent="fixture", task="fixture", paths=paths, branch=branch)
    board.worklog(row["claim_id"]).create(row, plan=["fixture work"])


def _precommit(policy, paths):
    return CLI.main(
        [
            "--no-gh",
            "--session",
            "mine",
            "--vendor",
            "codex",
            "precommit",
            "--json",
            "--agents-md",
            str(policy),
            "--exclude-branch",
            "work",
            "--paths",
            *paths,
        ]
    )


def test_merge_excludes_inherited_main_but_checks_own_changes(setup, capsys):
    repo, board, policy = setup
    _claim(board, "mine", OWN, "work")
    _claim(board, "other", INHERITED, "main")
    supplied = _git(repo, "diff", "--cached", "--name-only").splitlines()
    assert set(supplied) == set(INHERITED)  # exactly what the existing hook supplies
    assert _precommit(policy, supplied) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["path_basis"] == "MERGE_HEAD"
    assert set(result["evaluated_paths"]) == set(OWN)
    assert result["conflicts"] == result["uncovered"] == []


def test_merge_does_not_trust_caller_to_omit_own_unclaimed_file(setup, capsys):
    _, board, policy = setup
    _claim(board, "mine", OWN[1:], "work")
    assert _precommit(policy, ["own added.txt"]) == CLI.PRECOMMIT_BLOCK
    result = json.loads(capsys.readouterr().out)
    assert result["uncovered"] == ["own.txt"]


def test_manual_merge_resolution_of_main_file_requires_own_claim(setup, capsys):
    repo, board, policy = setup
    _claim(board, "mine", OWN, "work")
    _claim(board, "other", INHERITED, "main")
    (repo / "inherited.txt").write_text("new resolution authored during merge\n")
    _git(repo, "add", "inherited.txt")
    assert _precommit(policy, ["own.txt"]) == CLI.PRECOMMIT_BLOCK
    result = json.loads(capsys.readouterr().out)
    assert "inherited.txt" in result["evaluated_paths"]
    assert result["conflicts"] and "inherited.txt" in result["uncovered"]


def test_normal_commit_keeps_caller_scope_and_existing_enforcement(setup, capsys):
    repo, board, policy = setup
    _git(repo, "commit", "-qm", "finish fixture merge")
    _claim(board, "mine", ["own.txt"], "work")
    assert _precommit(policy, ["own.txt"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["path_basis"] == "caller" and result["evaluated_paths"] == ["own.txt"]
    assert _precommit(policy, ["unclaimed.txt"]) == CLI.PRECOMMIT_BLOCK


def test_merge_with_no_own_delta_checks_an_empty_scope(setup, capsys):
    repo, _, policy = setup
    # A real merge index resolved entirely to the incoming parent's tree has no
    # worker-authored delta, although HEAD's staged list still reports main files.
    _git(repo, "read-tree", "MERGE_HEAD")
    assert _precommit(policy, INHERITED) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["path_basis"] == "MERGE_HEAD" and result["evaluated_paths"] == []


def test_linked_worktree_reads_its_own_merge_marker(setup, tmp_path, monkeypatch, capsys):
    repo, board, policy = setup
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-qb", "linked", str(linked), "HEAD")
    _git(linked, "merge", "--no-ff", "--no-commit", "main")
    _claim(board, "mine", OWN, "work")
    monkeypatch.chdir(linked)
    assert (linked / ".git").is_file()
    assert _precommit(policy, INHERITED) == 0
    assert json.loads(capsys.readouterr().out)["path_basis"] == "MERGE_HEAD"


def test_unaccepted_feature_merge_cannot_hide_incoming_unclaimed_files(setup, capsys):
    repo, _, policy = setup
    _git(repo, "commit", "-qm", "finish main merge")
    _git(repo, "checkout", "-qb", "unaccepted-feature")
    (repo / "unclaimed.txt").write_text("unreviewed feature change\n")
    _git(repo, "add", "unclaimed.txt")
    _git(repo, "commit", "-qm", "unaccepted feature")
    _git(repo, "checkout", "work")
    _git(repo, "merge", "--no-ff", "--no-commit", "unaccepted-feature")
    assert _precommit(policy, ["own.txt"]) == CLI.PRECOMMIT_BLOCK
    result = json.loads(capsys.readouterr().out)
    assert result["path_basis"] == "MERGE_HEAD+HEAD"
    assert result["uncovered"] == ["unclaimed.txt"]


def test_unknown_main_ref_keeps_both_parent_scopes(setup, capsys):
    repo, board, policy = setup
    _claim(board, "mine", OWN, "work")
    _git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    assert _precommit(policy, ["own.txt"]) == CLI.PRECOMMIT_BLOCK
    result = json.loads(capsys.readouterr().out)
    assert result["path_basis"] == "MERGE_HEAD+HEAD"
    assert set(result["uncovered"]) == set(INHERITED)


@pytest.mark.parametrize("failure", ["invalid_head", "git_error", "timeout", "no_repository"])
def test_unknown_merge_scope_fails_closed_before_claim_evaluation(setup, tmp_path, monkeypatch, capsys, failure):
    repo, _, policy = setup
    real_run = subprocess.run
    if failure == "invalid_head":
        marker = Path(_git(repo, "rev-parse", "--git-path", "MERGE_HEAD").strip())
        marker.write_text("not-a-commit\n")
    elif failure in {"git_error", "timeout"}:

        def run(args, **kwargs):
            if args[:2] == ["git", "diff"]:
                if failure == "timeout":
                    raise subprocess.TimeoutExpired(args, 10)
                raise subprocess.CalledProcessError(128, args, stderr="fixture git failure")
            return real_run(args, **kwargs)

        monkeypatch.setattr(CLI.subprocess, "run", run)
    else:
        empty = tmp_path / "outside"
        empty.mkdir()
        monkeypatch.chdir(empty)
    monkeypatch.setattr(CLI, "_board", lambda args: pytest.fail("unknown path scope reached claim evaluation"))
    assert _precommit(policy, ["own.txt"]) == 3
    assert "gate crashed" in capsys.readouterr().err
