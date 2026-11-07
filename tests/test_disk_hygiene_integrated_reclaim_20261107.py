"""LQ-20261107-190: a worktree whose commits are all in the live-integration branch is reclaimable before the 7-day idle
window; scratch honours an hours threshold. Claims / open PRs / cwd holds are separate checks and are not waived here."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import disk_hygiene as DH  # noqa: E402


def _g(repo, *a):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *a], check=True, capture_output=True)


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _g(r, "init", "-q", "-b", "main")
    (r / "a").write_text("1")
    _g(r, "add", "a"); _g(r, "commit", "-qm", "base")
    _g(r, "branch", "wt/live-integration-20261106")
    return r


GLOB = "refs/heads/wt/live-integration-*"


def test_ancestor_is_integrated(tmp_path):
    r = _repo(tmp_path)
    assert DH.integration_basis(r, _head(r), GLOB) == "ancestor"


def test_patch_equivalent_is_integrated(tmp_path):
    r = _repo(tmp_path)
    _g(r, "checkout", "-q", "-b", "feat")
    (r / "b").write_text("x"); _g(r, "add", "b"); _g(r, "commit", "-qm", "feat")
    feat = _head(r)
    _g(r, "checkout", "-q", "wt/live-integration-20261106")
    (r / "c").write_text("y"); _g(r, "add", "c"); _g(r, "commit", "-qm", "other")
    _g(r, "cherry-pick", feat)
    assert DH.integration_basis(r, feat, GLOB) == "patch-equivalent"


def test_unintegrated_commit_is_not(tmp_path):
    r = _repo(tmp_path)
    _g(r, "checkout", "-q", "-b", "feat")
    (r / "b").write_text("x"); _g(r, "add", "b"); _g(r, "commit", "-qm", "feat")
    assert DH.integration_basis(r, _head(r), GLOB) is None


def test_no_integration_ref_is_not_integrated(tmp_path):
    r = _repo(tmp_path)
    assert DH.integration_basis(r, _head(r), "refs/heads/nope-*") is None


def test_idle_hold_waived_only_when_integrated_and_past_floor():
    day = 86400
    assert DH.worktree_idle_hold(0.5 * day, 7, None, 6) == "worktree_not_idle_7_days"
    assert DH.worktree_idle_hold(0.5 * day, 7, "ancestor", 6) is None
    assert DH.worktree_idle_hold(3 * 3600, 7, "ancestor", 6) == "worktree_not_idle_6_hours_integrated"
    assert DH.worktree_idle_hold(None, 7, "ancestor", 6) == "worktree_not_idle_7_days"


def test_scratch_threshold_prefers_hours():
    assert DH.scratch_idle_seconds({"idle_days": 2}) == 2 * 86400
    assert DH.scratch_idle_seconds({"idle_days": 2, "idle_hours": 12}) == 12 * 3600
