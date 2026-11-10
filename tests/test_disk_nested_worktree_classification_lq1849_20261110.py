"""LQ-20261107-1849: a `.git` FILE inside agent scratch is three shapes, and only one of them is a linked worktree.

Before this ticket every `.git` file whose gitdir still existed took one path: ``archive_worktree`` (a ref) then
``git worktree remove`` from ``common-dir``'s parent. That is right for a linked worktree of a repo that still
exists, and wrong for the two shapes the live host is stuck on:

* a **standalone repo** whose git dir is its own (``separate/.git`` -> ``separate-metadata``): the archive ref is
  written INSIDE the dir rule T then removes, so the archive dies with it, and ``git -C <parent> worktree remove``
  cannot run because the parent is not a repo -- the apply report says
  ``nested_worktree_remove_failed:worktree:.:git_worktree_remove_rc:128``;
* a **half-built registration** a test fixture left behind (``common.git/worktrees/<name>`` holding only
  ``commondir``): git answers 128 and there is nothing to archive -- the apply report says
  ``nested_worktree_unreadable:worktree:pytest-29/...`` and holds forever.

The rule these tests pin: a dir is removed only after every commit in it is preserved in a verified bundle that
lives OUTSIDE it (or, for a linked worktree whose main repo is usable, in an archive ref written into the surviving
common dir). Nothing is loosened for a git dir that stores any object, ref or reflog.
"""

import subprocess
from pathlib import Path

import pytest

from scripts import disk_hygiene as DH

ARCHIVE_NS = "refs/archive/closeout"  # the production namespace (disk_hygiene.py:1621)
GIT = [
    "git", "-c", "core.fsmonitor=false", "-c", "protocol.file.allow=always",
    "-c", "user.email=synthetic@example.invalid", "-c", "user.name=synthetic",
]


def git(*args, cwd):
    proc = subprocess.run(GIT + [str(a) for a in args], cwd=str(cwd), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, f"git {args} failed: {proc.stdout}{proc.stderr}"
    return proc.stdout


def item(root: Path, bdir: Path, *bundles: str) -> dict:
    return {"path": str(root), "bundle_dir": str(bdir), "archive_ns": ARCHIVE_NS, "bundles": list(bundles)}


def make_repo(path: Path) -> None:
    path.mkdir(parents=True)
    git("init", "-q", "-b", "main", cwd=path)
    (path / "proof.txt").write_text("synthetic fixture\n")
    git("add", "proof.txt", cwd=path)
    git("commit", "-q", "-m", "synthetic commit", cwd=path)


def bundle_files(bdir: Path) -> list[Path]:
    return sorted(bdir.rglob("*.bundle")) if bdir.exists() else []


# --- shape 1: a registration that names no commit (the livefold fixture arena) --------------------------------


def test_a_half_built_registration_names_no_commit_and_is_not_held(tmp_path):
    root, bdir = tmp_path / "root", tmp_path / "bundles"
    repo = root / "pytest-29" / "test_case" / "repo"
    repo.mkdir(parents=True)
    admin = root / "common.git" / "worktrees" / "wt"
    admin.mkdir(parents=True)
    (root / "common.git" / "config").write_text("[core]\n\trepositoryformatversion = 0\n")
    (admin / "commondir").write_text("../..\n")
    (repo / ".git").write_text(f"gitdir: {admin}\n")

    assert DH._worktree_names_no_commit(repo) is True
    assert DH.bundle_nested(item(root, bdir, "worktree:pytest-29/test_case/repo")) is None
    assert bundle_files(bdir) == []  # nothing to bundle, and no bundle claimed


def test_a_registration_with_a_reflog_fails_closed(tmp_path):
    root, bdir = tmp_path / "root", tmp_path / "bundles"
    repo = root / "repo"
    repo.mkdir(parents=True)
    admin = root / "common.git" / "worktrees" / "wt"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n")
    (admin / "logs").mkdir()
    (admin / "logs" / "HEAD").write_text("0000 1111 synthetic\n")
    (repo / ".git").write_text(f"gitdir: {admin}\n")

    assert DH.bundle_nested(item(root, bdir, "worktree:repo")) == "nested_worktree_unreadable:worktree:repo"


def test_an_admin_dir_with_no_commondir_keeps_todays_refusal(tmp_path):
    # the pinned 2026-10-31 shape: `gitdir:` names an empty dir, so nothing can be archived and nothing is removed
    root, bdir = tmp_path / "root", tmp_path / "bundles"
    repo = root / "wt"
    repo.mkdir(parents=True)
    (tmp_path / "fixture-repo" / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (repo / ".git").write_text(f"gitdir: {tmp_path / 'fixture-repo' / '.git' / 'worktrees' / 'wt'}\n")

    how = DH.bundle_nested(item(root, bdir, "worktree:."))
    assert how is not None and how.startswith("nested_worktree_unreadable")


# --- shape 2: a standalone repo whose git dir is its own (review-2581's `separate`) --------------------------


def standalone(root: Path, name: str = "separate") -> Path:
    """A work tree whose ``.git`` FILE points at a git dir that is its own (git-dir == common-dir)."""
    repo, meta = root / name, root / "separate-metadata"
    make_repo(repo)
    (repo / ".git").rename(meta)
    (repo / ".git").write_text(f"gitdir: {meta}\n")
    assert git("rev-parse", "--git-dir", cwd=repo).strip() == str(meta)
    return repo


def test_a_standalone_git_file_repo_is_bundled_outside_itself(tmp_path):
    root, bdir = tmp_path / "root", tmp_path / "bundles"
    repo = standalone(root)

    assert DH.bundle_nested(item(root, bdir, "worktree:separate")) is None
    (out,) = bundle_files(bdir)
    assert out.parent == bdir / "root" and out.name.startswith("separate-") and out.suffix == ".bundle"
    heads = git("bundle", "list-heads", out, cwd=root)
    assert "refs/heads/main" in heads and "HEAD" in heads
    # the archive ref the old path wrote lives INSIDE the dir about to go: it must not be what preserves this repo
    assert git("for-each-ref", "refs/archive/", cwd=repo).strip() == ""


def test_a_standalone_repo_with_uncommitted_work_is_held(tmp_path):
    root, bdir = tmp_path / "root", tmp_path / "bundles"
    repo = standalone(root)
    (repo / "uncommitted.txt").write_text("not committed\n")

    assert DH.bundle_nested(item(root, bdir, "worktree:separate")) == "nested_worktree_dirty:worktree:separate"
    assert bundle_files(bdir) == []


def test_an_empty_standalone_repo_is_not_bundled(tmp_path):
    root, bdir = tmp_path / "root", tmp_path / "bundles"
    repo, meta = root / "empty", root / "empty-metadata"
    repo.mkdir(parents=True)
    git("init", "-q", "-b", "main", cwd=repo)
    (repo / ".git").rename(meta)
    (repo / ".git").write_text(f"gitdir: {meta}\n")

    assert DH.bundle_nested(item(root, bdir, "worktree:empty")) is None
    assert bundle_files(bdir) == []


# --- shape 3: a linked worktree -- unchanged when its main repo exists, bundled when it does not ---------------


def test_a_linked_worktree_with_its_main_repo_is_archived_then_removed(tmp_path):
    root, bdir = tmp_path / "root", tmp_path / "bundles"
    main = root / "main"
    make_repo(main)
    linked = root / "wt-linked"
    git("worktree", "add", "-q", "-b", "side", linked, cwd=main)

    assert DH.bundle_nested(item(root, bdir, "worktree:wt-linked")) is None
    assert not linked.exists()
    assert git("for-each-ref", "refs/archive/", cwd=main).strip()  # the ref survives in the main repo
    assert bundle_files(bdir) == []


def test_a_linked_worktree_whose_main_repo_is_gone_is_bundled(tmp_path):
    # review-2581-resolver's `linked`: the common dir was moved out from under the worktree, so no main repo exists
    root, bdir = tmp_path / "root", tmp_path / "bundles"
    main = root / "main"
    make_repo(main)
    linked = root / "linked"
    git("worktree", "add", "-q", "-b", "side", linked, cwd=main)
    moved = root / "moved-common"
    (main / ".git").rename(moved)
    (linked / ".git").write_text(f"gitdir: {moved / 'worktrees' / 'linked'}\n")
    assert git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=linked).strip() == str(moved)

    assert DH.bundle_nested(item(root, bdir, "worktree:linked")) is None
    (out,) = bundle_files(bdir)
    assert "refs/heads/side" in git("bundle", "list-heads", out, cwd=root)
    assert linked.exists()  # bundle_nested preserves; the caller's rmtree removes


def test_two_roots_with_the_same_basename_do_not_share_one_bundle(tmp_path):
    # `.../review-2581.../separate` and `.../review-d13.../separate` are both plan items: one bundle path for both
    # would let the second overwrite the first after the first dir was already removed.
    bdir = tmp_path / "bundles"
    first, second = tmp_path / "a" / "separate", tmp_path / "b" / "separate"
    for repo in (first, second):
        make_repo(repo)
        (repo / ".git").rename(repo.parent / "metadata")
        (repo / ".git").write_text(f"gitdir: {repo.parent / 'metadata'}\n")

    assert DH.bundle_nested(item(first, bdir, "worktree:.")) is None
    assert DH.bundle_nested(item(second, bdir, "worktree:.")) is None
    assert len(bundle_files(bdir)) == 2
