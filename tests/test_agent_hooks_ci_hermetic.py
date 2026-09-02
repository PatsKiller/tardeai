"""Hermetic hooks prerequisite tests (CI clean-clone / worktree-local).

Does not rely on the operator ambient ``core.hooksPath``. Uses isolated
temporary repositories only. Does not weaken HOOKS_PATH_MISSING.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.lib.agent_session_receipt import start_session

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_ai_work_policy.sh"


def _run(cmd: list[str], *, cwd: Path, env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess:
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=merged,
        text=True,
        capture_output=True,
        check=check,
    )


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    return _run(["git", *args], cwd=cwd, check=check).stdout.strip()


def _seed_policy_tree(path: Path) -> None:
    """Minimal tracked tree so the canonical installer can configure hooks."""
    (path / "AI_WORK_POLICY.md").write_text("# AI work policy (test fixture)\n", encoding="utf-8")
    (path / "AGENTS.md").write_text(
        "Policy-Version: 1.2.0\nStatus: PROPOSED\nEffective-Date: PENDING\n",
        encoding="utf-8",
    )
    (path / "docs").mkdir(parents=True, exist_ok=True)
    (path / "docs" / "INDEX.md").write_text("# index\n", encoding="utf-8")
    hooks = path / ".githooks"
    hooks.mkdir(exist_ok=True)
    for name in ("pre-commit", "pre-push"):
        src = ROOT / ".githooks" / name
        dst = hooks / name
        shutil.copy2(src, dst)
        dst.chmod(0o755)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init"], cwd=path)
    _run(["git", "config", "user.email", "hooks-ci@example.test"], cwd=path)
    _run(["git", "config", "user.name", "Hooks CI"], cwd=path)
    # Ensure no inherited hooksPath in this repo
    _run(["git", "config", "--unset-all", "core.hooksPath"], cwd=path, check=False)
    _seed_policy_tree(path)
    _run(["git", "add", "AI_WORK_POLICY.md", "AGENTS.md", "docs", ".githooks"], cwd=path)
    _run(["git", "commit", "-m", "seed"], cwd=path)
    return path


def _hooks_path(cwd: Path) -> str:
    proc = _run(["git", "config", "--get", "core.hooksPath"], cwd=cwd, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _install_hooks(cwd: Path) -> None:
    # Invoke the tracked installer with cwd = target repo so show-toplevel is cwd.
    _run(["bash", str(INSTALLER)], cwd=cwd)


def _assert_hook_self_test(cwd: Path) -> None:
    assert (cwd / ".githooks" / "pre-commit").is_file()
    assert (cwd / ".githooks" / "pre-push").is_file()
    assert os.access(cwd / ".githooks" / "pre-commit", os.X_OK)
    assert os.access(cwd / ".githooks" / "pre-push", os.X_OK)
    # Unauthorized push must be refused (exit nonzero).
    proc = _run(
        [str(cwd / ".githooks" / "pre-push")],
        cwd=cwd,
        env={"TRADEAI_REMOTE_PUSH_AUTHORIZED": "0"},
        check=False,
    )
    assert proc.returncode != 0, "pre-push must block unauthorized sync"


def test_mutating_hooks_path_missing_fails_closed_no_writes(tmp_path: Path):
    """Absent core.hooksPath → HOOKS_PATH_MISSING; no receipt/lease writes."""
    main = _init_repo(tmp_path / "main")
    assert _hooks_path(main) == ""
    coord = tmp_path / "coord-must-not-exist"
    receipt = start_session(
        agent_id="grok",
        repo_root=main,
        claimed_paths=["docs/INDEX.md"],
        docs_read=["AGENTS.md", "AI_WORK_POLICY.md"],
        mode="mutating",
        acknowledge_dirty=True,
        expected_worktree=main,
        cwd=main,
        coordination_root_path=coord,
        task_scope="hooks-absent",
    )
    assert receipt["ok"] is False
    assert any("HOOKS_PATH_MISSING" in e for e in receipt["errors"])
    assert not coord.exists(), "identity/hooks failure must not create coordination writes"
    assert not list((tmp_path / "coord-must-not-exist").glob("**/*")) if coord.exists() else True


def test_mutating_with_docs_and_claims_ok_hermetic_worktree(tmp_path: Path):
    """Linked worktree: installer sets worktree-local hooksPath; mutating OK."""
    main = _init_repo(tmp_path / "main")
    wt = tmp_path / "linked-wt"
    _run(["git", "worktree", "add", str(wt), "HEAD"], cwd=main)
    assert _hooks_path(wt) == ""
    _install_hooks(wt)
    assert _hooks_path(wt) == ".githooks"
    # Confirm worktree-local scope (git_dir != common)
    git_dir = Path(_git(wt, "rev-parse", "--absolute-git-dir"))
    common = Path(_git(wt, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (wt / common).resolve()
    assert git_dir != common.resolve()
    _assert_hook_self_test(wt)

    coord = tmp_path / "coord-wt"
    receipt = start_session(
        agent_id="grok",
        repo_root=wt,
        claimed_paths=["docs/INDEX.md"],
        docs_read=["AGENTS.md", "AI_WORK_POLICY.md", "docs/INDEX.md"],
        docs_searched=["hooks", "lease"],
        mode="mutating",
        acknowledge_dirty=True,
        expected_worktree=wt,
        cwd=wt,
        coordination_root_path=coord,
        task_scope="hooks-hermetic-wt",
    )
    assert receipt["ok"] is True, receipt.get("errors")
    assert receipt.get("lease")
    assert receipt["hook_installation"]["core.hooksPath"] == ".githooks"
    assert (coord / "receipts").is_dir()


def test_clean_ci_clone_installer_then_mutating_ok(tmp_path: Path):
    """Normal checkout (clone): hooks absent → installer → self-test → mutating OK."""
    origin = _init_repo(tmp_path / "origin")
    clone = tmp_path / "clone"
    _run(["git", "clone", str(origin), str(clone)], cwd=tmp_path)
    # Fresh clone must not inherit hooksPath
    _run(["git", "config", "--unset-all", "core.hooksPath"], cwd=clone, check=False)
    assert _hooks_path(clone) == ""

    _install_hooks(clone)
    assert _hooks_path(clone) == ".githooks"
    git_dir = Path(_git(clone, "rev-parse", "--absolute-git-dir"))
    common = Path(_git(clone, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (clone / common).resolve()
    assert git_dir.resolve() == common.resolve(), "plain clone should use clone-local hooksPath"
    _assert_hook_self_test(clone)

    coord = tmp_path / "coord-clone"
    receipt = start_session(
        agent_id="grok",
        repo_root=clone,
        claimed_paths=["docs/INDEX.md"],
        docs_read=["AGENTS.md", "AI_WORK_POLICY.md", "docs/INDEX.md"],
        mode="mutating",
        acknowledge_dirty=True,
        expected_worktree=clone,
        cwd=clone,
        coordination_root_path=coord,
        task_scope="hooks-hermetic-clone",
    )
    assert receipt["ok"] is True, receipt.get("errors")
    assert receipt.get("lease")
    assert not any("HOOKS_PATH_MISSING" in e for e in (receipt.get("errors") or []))
