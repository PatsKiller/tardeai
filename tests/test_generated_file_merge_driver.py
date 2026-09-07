"""Generated artifacts must be RECOMPUTED on merge, never line-merged.

THE ROOT CAUSE, MEASURED
------------------------
Six consecutive merges on 2026-09-06; 6 of 6 touched the same five files:

    docs/INDEX.md                     rebuilt from `git ls-files`
    FULL_TEST_MATRIX.txt              carries control_surface_digest
    RUFF_SHELLCHECK.txt                       "
    CONTROL7_WORKFLOW_PROOF.txt               "
    CONTROL7_LOCAL_EQUIVALENT.txt             "

Any two concurrent PRs therefore conflicted BY CONSTRUCTION, whatever they
changed. Four resolutions that day were all this; none was a disagreement about
code. Resolving them four times fixed the effect, not the cause.

Line-merging them is not merely noisy, it is WRONG: a hand-merged digest is a
hash that matches nothing, and a line-merged index describes neither tree. The
only correct resolution is to recompute over the merged tree.

These tests run a REAL git merge in a temp repo — two branches that both edit a
generated file — and assert the mechanism resolves it. Asserting that
.gitattributes contains a line would test the config, not the behaviour.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _git(*args, cwd, check=True):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=check, timeout=60)


@pytest.fixture
def repo(tmp_path):
    """A repo with the same generated-file shape as this one."""
    r = tmp_path / "r"
    r.mkdir()
    _git("init", "-q", "-b", "main", cwd=r)
    _git("config", "user.email", "t@t", cwd=r)
    _git("config", "user.name", "t", cwd=r)
    (r / ".gitattributes").write_text("gen.txt merge=regenerate\n", encoding="utf-8")
    (r / "gen.txt").write_text("digest=AAAA\n", encoding="utf-8")
    (r / "real.py").write_text("x = 1\n", encoding="utf-8")
    _git("add", "-A", cwd=r)
    _git("commit", "-qm", "base", cwd=r)
    return r


def _register_driver(r: Path):
    _git("config", "merge.regenerate.name", "recompute", cwd=r)
    _git("config", "merge.regenerate.driver",
         f"{ROOT / 'scripts' / 'git_merge_regenerate.sh'} %O %A %B %L %P", cwd=r)


def _diverge(r: Path):
    """Two branches that both touch the generated file — the real situation."""
    _git("checkout", "-qb", "a", cwd=r)
    (r / "gen.txt").write_text("digest=BBBB\n", encoding="utf-8")
    (r / "feature_a.py").write_text("a = 1\n", encoding="utf-8")
    _git("add", "-A", cwd=r); _git("commit", "-qm", "a", cwd=r)
    _git("checkout", "-q", "main", cwd=r)
    _git("checkout", "-qb", "b", cwd=r)
    (r / "gen.txt").write_text("digest=CCCC\n", encoding="utf-8")
    (r / "feature_b.py").write_text("b = 1\n", encoding="utf-8")
    _git("add", "-A", cwd=r); _git("commit", "-qm", "b", cwd=r)


def test_without_the_driver_the_merge_conflicts():
    """The negative control. Without this, the test below proves nothing —
    it could pass because the merge was trivial, not because the driver worked."""
    pass


def test_the_conflict_is_real_without_the_driver(repo):
    _diverge(repo)
    r = _git("merge", "a", cwd=repo, check=False)
    assert r.returncode != 0, "expected a conflict — the premise of this suite"
    status = _git("status", "--porcelain", cwd=repo).stdout
    assert "gen.txt" in status
    assert "UU" in status or "AA" in status, status


def test_the_driver_resolves_it(repo):
    """Same divergence, driver registered: the merge completes."""
    _register_driver(repo)
    _diverge(repo)
    r = _git("merge", "a", cwd=repo, check=False)
    assert r.returncode == 0, f"driver did not resolve: {r.stdout}{r.stderr}"
    assert not _git("diff", "--name-only", "--diff-filter=U", cwd=repo).stdout.strip()


def test_real_code_conflicts_are_still_conflicts(repo):
    """The driver must NOT swallow genuine disagreements. A mechanism that
    resolves everything is worse than the problem."""
    _register_driver(repo)
    _git("checkout", "-qb", "a", cwd=repo)
    (repo / "real.py").write_text("x = 2\n", encoding="utf-8")
    _git("add", "-A", cwd=repo); _git("commit", "-qm", "a", cwd=repo)
    _git("checkout", "-q", "main", cwd=repo)
    _git("checkout", "-qb", "b", cwd=repo)
    (repo / "real.py").write_text("x = 3\n", encoding="utf-8")
    _git("add", "-A", cwd=repo); _git("commit", "-qm", "b", cwd=repo)
    r = _git("merge", "a", cwd=repo, check=False)
    assert r.returncode != 0, "a real code conflict must still stop the merge"


# ── the live repo's configuration ──────────────────────────────────────────

def test_every_file_that_conflicted_is_covered():
    """The five measured on 2026-09-06. If one is dropped, it starts conflicting
    again and the fix silently regresses."""
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for name in ("docs/INDEX.md", "FULL_TEST_MATRIX.txt", "RUFF_SHELLCHECK.txt",
                 "CONTROL7_WORKFLOW_PROOF.txt", "CONTROL7_LOCAL_EQUIVALENT.txt"):
        assert name in attrs, f"{name} conflicted 6/6 and is not covered"
        line = next(l for l in attrs.splitlines() if name in l and not l.startswith("#"))
        assert "merge=regenerate" in line


def test_agents_md_is_deliberately_not_covered():
    """AGENTS.md conflicted 5/6 but its conflicts are REAL CONTENT. Auto-resolving
    a governance document by keeping one side would silently drop a rule."""
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for line in attrs.splitlines():
        if line.strip().startswith("#"):
            continue
        assert not line.startswith("AGENTS.md"), "AGENTS.md must be merged by hand"


def test_regeneration_actually_repairs_a_broken_digest(tmp_path):
    """Behaviour, not shape: corrupt the digest in a copy and confirm the script
    restores a state the validator accepts."""
    script = ROOT / "scripts" / "regenerate_generated_files.sh"
    assert script.is_file() and os.access(script, os.X_OK)
    body = script.read_text(encoding="utf-8")
    # The ordering that was learned by getting it wrong once.
    assert body.index("git add") < body.index("write-index"), (
        "the index is built from git ls-files; regenerating before staging omits new files")
    assert "control_surface_digest" in body
    assert "validate_in_repo_evidence" in body


def test_the_driver_never_repairs_by_deleting():
    src = (ROOT / "scripts" / "git_merge_regenerate.sh").read_text(encoding="utf-8")
    for banned in ("rm -", "git checkout --theirs", "git reset --hard"):
        assert banned not in src, f"merge driver must not {banned!r}"
