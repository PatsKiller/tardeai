"""Cursor git-push grant is honored by the pre-push hook (peek, no consume)."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRE_PUSH = ROOT / ".githooks" / "pre-push"
HOOKS = ROOT / ".cursor" / "hooks"


def _run(cmd, *, cwd, env=None):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(cmd, cwd=cwd, env=merged, capture_output=True, text=True)


def _grant_git_push(adir: Path, *, uses: int = 5, reason: str = "test grant") -> None:
    adir.mkdir(mode=0o700, parents=True, exist_ok=True)
    exp = int(time.time()) + 3600
    subprocess.run(
        [
            "python3",
            str(HOOKS / "guard_ledger.py"),
            "grant",
            "--tier",
            "git-push",
            "--expires",
            str(exp),
            "--uses",
            str(uses),
            "--reason",
            reason,
        ],
        env={**os.environ, "GUARD_APPROVALS_DIR": str(adir)},
        check=True,
        capture_output=True,
        text=True,
    )


def test_git_push_grant_active_when_present(tmp_path: Path) -> None:
    adir = tmp_path / "approvals"
    _grant_git_push(adir)
    from scripts.lib.guard_push_auth import git_push_grant_active, push_authorized_by_guard

    rec = git_push_grant_active(adir=adir)
    assert rec is not None
    assert rec.get("reason") == "test grant"
    ok, reason = push_authorized_by_guard(adir=adir)
    assert ok is True
    assert reason == "test grant"


def test_git_push_grant_absent_when_empty(tmp_path: Path) -> None:
    adir = tmp_path / "approvals"
    subprocess.run(
        ["python3", str(HOOKS / "guard_ledger.py"), "init"],
        env={**os.environ, "GUARD_APPROVALS_DIR": str(adir)},
        check=True,
        capture_output=True,
        text=True,
    )
    from scripts.lib.guard_push_auth import push_authorized_by_guard

    ok, _ = push_authorized_by_guard(adir=adir)
    assert ok is False


def _mini_repo(tmp: Path, *, adir: Path | None = None) -> Path:
    import shutil

    src = tmp / "src"
    remote = tmp / "remote.git"
    src.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote)], cwd=tmp, check=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=src, check=True)
    subprocess.run(["git", "config", "user.email", "policy@test.local"], cwd=src, check=True)
    subprocess.run(["git", "config", "user.name", "Policy Test"], cwd=src, check=True)
    (src / ".githooks").mkdir()
    shutil.copy2(PRE_PUSH, src / ".githooks/pre-push")
    os.chmod(src / ".githooks/pre-push", os.stat(src / ".githooks/pre-push").st_mode | stat.S_IEXEC)
    lib = src / "scripts" / "lib"
    lib.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/lib/tradeai_push_budget.py", lib / "tradeai_push_budget.py")
    shutil.copy2(ROOT / "scripts/lib/guard_push_auth.py", lib / "guard_push_auth.py")
    hooks = src / ".cursor" / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy2(HOOKS / "guard_ledger.py", hooks / "guard_ledger.py")
    (src / "scripts" / "check_no_secrets.py").write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n")
    (src / "README").write_text("mini\n")
    subprocess.run(["git", "add", "."], cwd=src, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=src, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=src, check=True)
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=src, check=True)
    if adir is not None:
        _grant_git_push(adir)
    return src


def test_pre_push_allows_push_under_git_push_grant(tmp_path: Path) -> None:
    adir = tmp_path / "approvals"
    src = _mini_repo(tmp_path, adir=adir)
    env = {
        "TRADEAI_SKIP_SECRETS_SCAN": "1",
        "TRADEAI_PUSH_BUDGET_PATH": str(src / ".git/tradeai-push-budget.json"),
        "GUARD_APPROVALS_DIR": str(adir),
        "PYTHONPATH": str(src),
    }
    proc = _run(["bash", str(PRE_PUSH)], cwd=src, env=env)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "Cursor git-push grant active" in proc.stdout

    push = _run(["git", "push", "-u", "origin", "main"], cwd=src, env=env)
    assert push.returncode == 0, push.stderr + push.stdout


def test_pre_push_guard_grant_covers_push_budget(tmp_path: Path) -> None:
    adir = tmp_path / "approvals"
    src = _mini_repo(tmp_path, adir=adir)
    env = {
        "TRADEAI_SKIP_SECRETS_SCAN": "1",
        "TRADEAI_PUSH_BUDGET_PATH": str(src / ".git/tradeai-push-budget.json"),
        "GUARD_APPROVALS_DIR": str(adir),
        "PYTHONPATH": str(src),
    }
    for i in range(3):
        if i:
            (src / "README").write_text(f"push{i}\n")
            subprocess.run(["git", "add", "README"], cwd=src, check=True)
            subprocess.run(["git", "commit", "-m", f"push{i}"], cwd=src, check=True)
        cmd = ["git", "push", "-u", "origin", "main"] if i == 0 else ["git", "push", "origin", "main"]
        push = _run(cmd, cwd=src, env=env)
        assert push.returncode == 0, push.stderr + push.stdout
