"""The suite-preflight decision (DSN-20261031-ci-load-reduction §5, D50 item 7).

Every test here is about the direction of the failure: a head that might have changed branch content must
need the suite, because a skipped suite that should have run is a green on untested code.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib import ci_suite_preflight as P  # noqa: E402


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.invalid",
                        "-c", "user.name=t", *args], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    """main + a branch, with origin/main pointing at main so the module's default ref resolves."""
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "a.txt").write_text("a\n")
    git(r, "add", "a.txt")
    git(r, "commit", "-q", "-m", "root")
    git(r, "branch", "-M", "main")
    git(r, "checkout", "-q", "-b", "feature")
    (r / "b.txt").write_text("b\n")
    git(r, "add", "b.txt")
    git(r, "commit", "-q", "-m", "branch work")
    git(r, "update-ref", "refs/remotes/origin/main", git(r, "rev-parse", "main"))
    return r


def _main_moves(repo):
    git(repo, "checkout", "-q", "main")
    (repo / "c.txt").write_text("c\n")
    git(repo, "add", "c.txt")
    git(repo, "commit", "-q", "-m", "main moves")
    git(repo, "update-ref", "refs/remotes/origin/main", git(repo, "rev-parse", "main"))
    git(repo, "checkout", "-q", "feature")


def test_an_ordinary_commit_needs_the_suite(repo):
    out = P.decide(repo, "HEAD")
    assert out["needed"] is True and "not a merge" in out["reason"]


def test_a_merge_of_main_only_does_not_need_the_suite(repo):
    _main_moves(repo)
    git(repo, "merge", "-q", "--no-edit", "main")
    out = P.decide(repo, "HEAD")
    assert out["needed"] is False, out
    assert "merge-of-main-only" in out["reason"]


def test_a_merge_that_also_changes_branch_files_needs_the_suite(repo):
    """A hand-resolved merge: the merge commit itself carries a branch change nobody has run."""
    _main_moves(repo)
    r = subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.invalid", "-c", "user.name=t",
                        "merge", "--no-commit", "main"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    (repo / "b.txt").write_text("b folded into the merge\n")
    git(repo, "add", "b.txt")
    git(repo, "commit", "-q", "-m", "merge main with a folded branch change")
    out = P.decide(repo, "HEAD")
    assert out["needed"] is True, out
    assert "changed the branch's own files" in out["reason"]


def test_an_unreadable_head_needs_the_suite(tmp_path):
    out = P.decide(tmp_path, "deadbeef" * 5)
    assert out["needed"] is True and "could not be read" in out["reason"]


def test_an_unknown_main_needs_the_suite(repo):
    """A merge head whose main ref cannot be resolved must RUN, not skip."""
    _main_moves(repo)
    git(repo, "merge", "-q", "--no-edit", "main")
    out = P.decide(repo, "HEAD", main="origin/does-not-exist")
    assert out["needed"] is True and "safe direction" in out["reason"], out
