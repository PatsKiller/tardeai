"""The upload check diffs a live-line branch against the served release.

ANCHOR: PREFLIGHT_BASE_REF_LQ1568_20261109

origin/main can be an ancestor of the served release and still be far behind
it. A three-dot diff against origin/main then treats tests that already
shipped on that release as files this branch added. Synthetic repos only.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _mod():
    name = "preflight_upload_lq1568"
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "preflight_upload.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True, timeout=60,
    )
    return proc.stdout.strip()


def _commit(root: Path, message: str) -> str:
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "-A")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD")


def _init(root: Path) -> None:
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _commit(root, "root")


def test_a_branch_cut_from_the_served_release_diffs_only_its_own_tests(tmp_path: Path):
    root = tmp_path / "repo"
    _init(root)
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    (root / "tests").mkdir()
    (root / "tests" / "test_live_already.py").write_text("def test_live():\n    assert True\n", encoding="utf-8")
    live = _commit(root, "served release")
    _git(root, "checkout", "-qb", "wt/cut-from-live")
    (root / "tests" / "test_branch_new.py").write_text("def test_new():\n    assert True\n", encoding="utf-8")
    _commit(root, "branch")
    pin = tmp_path / "GIT_SHA"
    pin.write_text(live + "\n", encoding="utf-8")
    mod = _mod()
    mod.SERVED_GIT_SHA_PATH = pin

    assert mod.diff_base(root) == live
    assert mod.touched_test_files(root) == ["tests/test_branch_new.py"]


def test_a_branch_based_on_origin_main_keeps_that_base_when_the_pin_is_not_a_commit(tmp_path: Path):
    root = tmp_path / "repo"
    _init(root)
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "checkout", "-qb", "wt/from-main")
    (root / "tests").mkdir()
    (root / "tests" / "test_only_branch.py").write_text("def test_only():\n    assert True\n", encoding="utf-8")
    _commit(root, "branch")
    pin = tmp_path / "GIT_SHA"
    pin.write_text("0123456789abcdef0123456789abcdef01234567\n", encoding="utf-8")
    mod = _mod()
    mod.SERVED_GIT_SHA_PATH = pin

    assert mod.diff_base(root) == "origin/main"
    assert mod.touched_test_files(root) == ["tests/test_only_branch.py"]


def test_a_diverged_branch_uses_the_served_parent_when_origin_main_is_not_an_ancestor(tmp_path: Path):
    root = tmp_path / "repo"
    _init(root)
    (root / "README.md").write_text("main side\n", encoding="utf-8")
    _commit(root, "origin main")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "checkout", "-qb", "wt/served", "HEAD~1")
    (root / "tests").mkdir()
    (root / "tests" / "test_live_already.py").write_text("def test_live():\n    assert True\n", encoding="utf-8")
    live = _commit(root, "served release")
    (root / "tests" / "test_branch_new.py").write_text("def test_new():\n    assert True\n", encoding="utf-8")
    _commit(root, "branch")
    pin = tmp_path / "GIT_SHA"
    pin.write_text(live + "\n", encoding="utf-8")
    mod = _mod()
    mod.SERVED_GIT_SHA_PATH = pin

    assert mod.diff_base(root) == live
    assert mod.touched_test_files(root) == ["tests/test_branch_new.py"]
