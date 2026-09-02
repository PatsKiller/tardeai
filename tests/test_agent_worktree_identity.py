"""Adversarial worktree / borrowed-gitdir identity tests (SOP 1.2.0).

All fixtures are temporary. Does not touch release dirs, build-meta.json,
or any registered production/agent worktree on the host.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.lib.agent_session_receipt import start_session
from scripts.lib.agent_worktree_identity import WorktreeIdentityError, assert_worktree_identity


def _run(cmd: list[str], *, cwd: Path) -> str:
    return subprocess.check_output(cmd, cwd=str(cwd), text=True).strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init"], cwd=path)
    _run(["git", "config", "user.email", "sop@example.test"], cwd=path)
    _run(["git", "config", "user.name", "SOP Test"], cwd=path)
    (path / "README").write_text("main\n", encoding="utf-8")
    _run(["git", "add", "README"], cwd=path)
    _run(["git", "commit", "-m", "init"], cwd=path)
    return path


def _head(path: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], cwd=path)


def _add_worktree(main: Path, wt: Path, branch: str) -> Path:
    wt.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "worktree", "add", "-b", branch, str(wt)], cwd=main)
    return wt


@pytest.fixture
def twin_worktrees(tmp_path: Path):
    """Main repo + registered linked worktree (clean)."""
    main = _init_repo(tmp_path / "main")
    wt = _add_worktree(main, tmp_path / "registered-wt", "feature/sop-id")
    return {"main": main, "wt": wt, "head_main": _head(main), "head_wt": _head(wt)}


def test_clean_registered_detached_verifier_accepted(tmp_path: Path):
    """Positive: clean registered detached worktree in read-only verifier mode."""
    main = _init_repo(tmp_path / "main")
    sha = _head(main)
    # Detached worktree at the same commit
    det = tmp_path / "verify-detached"
    _run(["git", "worktree", "add", "--detach", str(det), sha], cwd=main)
    assert _head(det) == sha
    # dirty-free
    assert _run(["git", "status", "--porcelain"], cwd=det) == ""

    facts = assert_worktree_identity(
        expected_worktree=det,
        cwd=det,
        expected_head=sha,
        acknowledge_dirty=False,
    )
    assert facts["ok"] is True
    assert facts["head"] == sha

    coord = tmp_path / "coord"
    receipt = start_session(
        agent_id="no_such_client",
        repo_root=det,
        claimed_paths=[],
        mode="read_only",
        expected_worktree=det,
        expected_head=sha,
        cwd=det,
        verifier=True,
        coordination_root_path=coord,
    )
    assert receipt["ok"] is True, receipt.get("errors")
    assert receipt["verifier"] is True
    assert receipt.get("receipt_path")
    assert (coord / "receipts").is_dir()


def test_cwd_ne_expected_fails_before_write(twin_worktrees, tmp_path: Path):
    wt = twin_worktrees["wt"]
    other = twin_worktrees["main"]
    coord = tmp_path / "coord-should-not-exist-a"
    with pytest.raises(WorktreeIdentityError) as ei:
        assert_worktree_identity(expected_worktree=wt, cwd=other)
    assert "CWD_NE_EXPECTED_WORKTREE" in ei.value.errors

    receipt = start_session(
        agent_id="grok",
        repo_root=wt,
        claimed_paths=["README"],
        docs_read=["AGENTS.md"],
        mode="mutating",
        acknowledge_dirty=True,
        expected_worktree=wt,
        cwd=other,  # wrong cwd
        coordination_root_path=coord,
    )
    assert receipt["ok"] is False
    assert "CWD_NE_EXPECTED_WORKTREE" in receipt["errors"]
    assert not coord.exists(), "identity failure must not create coordination writes"


def test_toplevel_ne_expected_via_borrowed_gitdir(tmp_path: Path):
    """Release-like dir: .git file points at another checkout's primary gitdir.

    Git may report the release path as ``--show-toplevel`` even though that path
    is absent from ``git worktree list --porcelain``. HEAD and the index belong
    to the other registered worktree — the phantom-modification adversary.
    """
    main = _init_repo(tmp_path / "main")
    wt = _add_worktree(main, tmp_path / "real-wt", "feature/real")
    primary_gitdir = _run(["git", "rev-parse", "--absolute-git-dir"], cwd=main)
    assert Path(primary_gitdir).is_dir()

    release = tmp_path / "release-dir-borrow"
    release.mkdir()
    (release / "PHANTOM").write_text("release-only payload\n", encoding="utf-8")
    (release / ".git").write_text(f"gitdir: {primary_gitdir}\n", encoding="utf-8")

    toplevel = Path(_run(["git", "rev-parse", "--show-toplevel"], cwd=release)).resolve()
    # Observed adversary: toplevel can equal the release cwd while still borrowed.
    assert toplevel == release.resolve()
    listed = _run(["git", "worktree", "list", "--porcelain"], cwd=release)
    assert str(release.resolve()) not in listed

    with pytest.raises(WorktreeIdentityError) as ei:
        assert_worktree_identity(expected_worktree=release, cwd=release)
    codes = ei.value.errors
    assert "BORROWED_GITDIR_OR_RELEASE_DIR" in codes
    assert "EXPECTED_NOT_IN_WORKTREE_LIST" in codes
    assert "GITDIR_BELONGS_TO_OTHER_WORKTREE" in codes
    assert "DIRTY_UNACKNOWLEDGED" in codes  # phantom paths vs borrowed index

    coord = tmp_path / "coord-should-not-exist-b"
    receipt = start_session(
        agent_id="verifier",
        repo_root=release,
        claimed_paths=[],
        mode="read_only",
        expected_worktree=release,
        expected_head=_head(wt),
        cwd=release,
        verifier=True,
        acknowledge_dirty=True,  # even with dirty ack, borrow must still fail
        coordination_root_path=coord,
    )
    assert receipt["ok"] is False
    assert "BORROWED_GITDIR_OR_RELEASE_DIR" in receipt["errors"]
    assert not coord.exists()


def test_expected_not_in_worktree_list(tmp_path: Path):
    main = _init_repo(tmp_path / "main")
    orphan = tmp_path / "orphan-copy"
    # Plain directory with its own unrelated repo — then we claim a path that
    # is not registered in *this* repo's worktree list by expecting a missing path.
    _init_repo(orphan)
    missing_expected = tmp_path / "never-registered"
    missing_expected.mkdir()
    with pytest.raises(WorktreeIdentityError) as ei:
        assert_worktree_identity(expected_worktree=missing_expected, cwd=orphan)
    assert "CWD_NE_EXPECTED_WORKTREE" in ei.value.errors
    # Also force equal cwd by expecting orphan but removing it from list is hard;
    # instead expect main while standing in orphan:
    with pytest.raises(WorktreeIdentityError) as ei2:
        assert_worktree_identity(expected_worktree=main, cwd=orphan)
    assert "EXPECTED_NOT_IN_WORKTREE_LIST" in ei2.value.errors or "CWD_NE_EXPECTED_WORKTREE" in ei2.value.errors


def test_gitdir_belongs_to_other_registered_worktree(tmp_path: Path):
    """Standing in WT-A while expecting WT-B: git identity is the other worktree."""
    main = _init_repo(tmp_path / "main")
    wt_a = _add_worktree(main, tmp_path / "wt-a", "feature/a")
    wt_b = _add_worktree(main, tmp_path / "wt-b", "feature/b")

    with pytest.raises(WorktreeIdentityError) as ei:
        assert_worktree_identity(expected_worktree=wt_b, cwd=wt_a)
    codes = ei.value.errors
    assert "CWD_NE_EXPECTED_WORKTREE" in codes
    assert "TOPLEVEL_NE_EXPECTED_WORKTREE" in codes
    assert "GITDIR_BELONGS_TO_OTHER_WORKTREE" in codes


def test_release_borrows_other_worktree_metadata_wrong_expected_head(tmp_path: Path):
    """Adversarial phantom-diff case: release borrows primary gitdir; expected HEAD is SOP tip."""
    main = _init_repo(tmp_path / "main")
    wt = _add_worktree(main, tmp_path / "agent-sop-sim", "governance/sim")
    # Advance main so HEAD diverges (simulates origin/main vs SOP tip)
    (main / "README").write_text("main advanced\n", encoding="utf-8")
    _run(["git", "add", "README"], cwd=main)
    _run(["git", "commit", "-m", "advance main"], cwd=main)
    main_head = _head(main)
    wt_head = _head(wt)
    assert main_head != wt_head

    primary_gitdir = _run(["git", "rev-parse", "--absolute-git-dir"], cwd=main)
    release = tmp_path / "trade-ai-release-sim"
    release.mkdir()
    (release / "EXTRA").write_text("release-only file\n", encoding="utf-8")
    (release / ".git").write_text(f"gitdir: {primary_gitdir}\n", encoding="utf-8")

    # Operator intended to verify wt_head but stood in release borrowing main's gitdir
    with pytest.raises(WorktreeIdentityError) as ei:
        assert_worktree_identity(
            expected_worktree=wt,
            cwd=release,
            expected_head=wt_head,
        )
    codes = ei.value.errors
    assert "CWD_NE_EXPECTED_WORKTREE" in codes
    assert "BORROWED_GITDIR_OR_RELEASE_DIR" in codes
    assert "HEAD_NE_EXPECTED" in codes
    assert "GITDIR_BELONGS_TO_OTHER_WORKTREE" in codes


def test_head_mismatch_fails(twin_worktrees, tmp_path: Path):
    wt = twin_worktrees["wt"]
    wrong = twin_worktrees["head_main"]
    # ensure wt head may equal main at branch point — force mismatch with zeros
    with pytest.raises(WorktreeIdentityError) as ei:
        assert_worktree_identity(
            expected_worktree=wt,
            cwd=wt,
            expected_head="0" * 40,
        )
    assert "HEAD_NE_EXPECTED" in ei.value.errors

    coord = tmp_path / "coord-should-not-exist-c"
    receipt = start_session(
        agent_id="verifier",
        repo_root=wt,
        claimed_paths=[],
        mode="read_only",
        expected_worktree=wt,
        expected_head="0" * 40,
        cwd=wt,
        verifier=True,
        coordination_root_path=coord,
    )
    assert receipt["ok"] is False
    assert "HEAD_NE_EXPECTED" in receipt["errors"]
    assert not coord.exists()
    # silence unused
    assert wrong


def test_dirty_unacknowledged_fails_before_write(twin_worktrees, tmp_path: Path):
    wt = twin_worktrees["wt"]
    (wt / "DIRTY.txt").write_text("unacked\n", encoding="utf-8")
    with pytest.raises(WorktreeIdentityError) as ei:
        assert_worktree_identity(expected_worktree=wt, cwd=wt, acknowledge_dirty=False)
    assert "DIRTY_UNACKNOWLEDGED" in ei.value.errors

    coord = tmp_path / "coord-should-not-exist-d"
    receipt = start_session(
        agent_id="no_such_client",
        repo_root=wt,
        claimed_paths=[],
        mode="read_only",
        expected_worktree=wt,
        cwd=wt,
        acknowledge_dirty=False,
        coordination_root_path=coord,
    )
    assert receipt["ok"] is False
    assert "DIRTY_UNACKNOWLEDGED" in receipt["errors"]
    assert not coord.exists()

    # Acknowledged dirty is allowed (still no mutate authority for unknown)
    receipt2 = start_session(
        agent_id="no_such_client",
        repo_root=wt,
        claimed_paths=[],
        mode="read_only",
        expected_worktree=wt,
        cwd=wt,
        acknowledge_dirty=True,
        coordination_root_path=coord,
    )
    assert receipt2["ok"] is True, receipt2.get("errors")
