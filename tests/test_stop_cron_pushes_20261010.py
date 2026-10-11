"""Stop push-from-cron (2026-10-10, operator-approved item 3; AGENTS.md §0 rule 4, AI_WORK_POLICY.md).

Cron L556 (`coder_dispatch.py --from-queue --apply`) and L541 (`backup_generated_docs.sh`) must never
push to a remote or open a PR. Both are local-only by default; a push needs an explicit operator flag
AND TRADEAI_REMOTE_PUSH_AUTHORIZED=1 (and, for coder_dispatch, never from the --from-queue cron argv).

No test here touches a real remote: git is shimmed (argv captured, `push` refused) and the backup
script runs inside a throwaway repo whose `origin` is a local bare repo.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
CODER = ROOT / "scripts" / "coder_dispatch.py"
BACKUP = ROOT / "linux_launchers" / "backup_generated_docs.sh"


# ── coder_dispatch ────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def cd(tmp_path, monkeypatch):
    """Import coder_dispatch with its log handler pointed at tmp and dotenv stubbed out."""
    monkeypatch.setitem(sys.modules, "dotenv", types.SimpleNamespace(load_dotenv=lambda *a, **k: None))
    monkeypatch.delenv("TRADEAI_REMOTE_PUSH_AUTHORIZED", raising=False)
    spec = importlib.util.spec_from_file_location("coder_dispatch_under_test", CODER)
    mod = importlib.util.module_from_spec(spec)
    real_fh = __import__("logging").FileHandler
    with mock.patch("logging.FileHandler", lambda *_a, **_k: real_fh(tmp_path / "cd.log")):
        spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "audit", lambda rec: None)
    monkeypatch.setattr(mod, "ARTIFACT_DIR", tmp_path / "diffs")
    return mod


@pytest.mark.parametrize("from_queue,allow,env,expect", [
    (True, False, None, False),    # the L556 cron argv
    (True, True, "1", False),      # even fully authorized, a queue drain never pushes
    (False, False, "1", False),    # env alone is not enough
    (False, True, None, False),    # flag alone is not enough
    (False, True, "0", False),
    (False, True, "1", True),      # operator, by hand, both
])
def test_push_gate_pr_mode(cd, monkeypatch, from_queue, allow, env, expect):
    if env is not None:
        monkeypatch.setenv("TRADEAI_REMOTE_PUSH_AUTHORIZED", env)
    ok, reason = cd.push_gate("pr", allow, from_queue)
    assert ok is expect, reason


def test_push_gate_advisory_never(cd, monkeypatch):
    monkeypatch.setenv("TRADEAI_REMOTE_PUSH_AUTHORIZED", "1")
    assert cd.push_gate("advisory", True, False)[0] is False


def _wire_fix(cd, monkeypatch, tmp_path, calls):
    """Make dispatch_one reach the commit point with a fake backend and a recording git/gh."""
    wt = tmp_path / "wt"
    wt.mkdir()
    monkeypatch.setattr(cd, "select_backend", lambda reg, kind: {"name": "fake", "display": "Fake", "kind": "cli_agent"})
    monkeypatch.setattr(cd, "_in_git_repo", lambda: True)
    monkeypatch.setattr(cd, "make_worktree", lambda branch, base: wt)
    monkeypatch.setattr(cd, "run_cli_agent", lambda b, prompt, w: (True, "ok"))
    monkeypatch.setattr(cd, "changed_files", lambda w: ["scripts/x.py"])
    monkeypatch.setattr(cd, "verify", lambda reg, w, files: (True, "compiled"))
    monkeypatch.setattr(cd, "remove_worktree", lambda w, br, keep_branch: calls.append(("remove", keep_branch)))

    def fake_git(*args, cwd=None, timeout=120):
        calls.append(("git",) + args)
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    def fake_run(argv, *a, **k):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(argv, 0, "https://example.invalid/pr/1", "")

    monkeypatch.setattr(cd, "_git", fake_git)
    monkeypatch.setattr(cd.subprocess, "run", fake_run)


def _pushed(calls):
    return [c for c in calls if (c[:2] == ("git", "push")) or c[:3] == ("gh", "pr", "create")]


def test_cron_argv_in_pr_mode_commits_locally_only(cd, monkeypatch, tmp_path):
    monkeypatch.setattr(cd, "MODE", "pr")
    monkeypatch.setenv("TRADEAI_REMOTE_PUSH_AUTHORIZED", "1")   # even if .env carried it
    calls: list = []
    _wire_fix(cd, monkeypatch, tmp_path, calls)
    res = cd.dispatch_one({"component": "health:x", "detail": "fix"}, {}, apply=True, from_queue=True)
    assert res["outcome"] == "local_commit" and res["pushed"] is False and res["mode"] == "pr_local"
    assert "from-queue" in res["push_blocked_reason"]
    assert ("git", "commit") == calls[[c[:2] for c in calls].index(("git", "commit"))][:2]
    assert ("remove", True) in calls          # the local branch is kept
    assert _pushed(calls) == []


def test_manual_pr_mode_without_auth_does_not_push(cd, monkeypatch, tmp_path):
    monkeypatch.setattr(cd, "MODE", "pr")
    calls: list = []
    _wire_fix(cd, monkeypatch, tmp_path, calls)
    res = cd.dispatch_one({"component": "c", "detail": "fix"}, {}, apply=True, allow_push=True)
    assert res["outcome"] == "local_commit"
    assert "TRADEAI_REMOTE_PUSH_AUTHORIZED" in res["push_blocked_reason"]
    assert _pushed(calls) == []


def test_operator_authorized_manual_run_still_pushes(cd, monkeypatch, tmp_path):
    monkeypatch.setattr(cd, "MODE", "pr")
    monkeypatch.setenv("TRADEAI_REMOTE_PUSH_AUTHORIZED", "1")
    calls: list = []
    _wire_fix(cd, monkeypatch, tmp_path, calls)
    res = cd.dispatch_one({"component": "c", "detail": "fix"}, {}, apply=True, allow_push=True)
    assert res["outcome"] == "pr_opened" and res["pushed"] is True
    assert len(_pushed(calls)) == 2


def test_advisory_mode_never_pushes(cd, monkeypatch, tmp_path):
    monkeypatch.setattr(cd, "MODE", "advisory")
    monkeypatch.setenv("TRADEAI_REMOTE_PUSH_AUTHORIZED", "1")
    calls: list = []
    _wire_fix(cd, monkeypatch, tmp_path, calls)
    monkeypatch.setattr(cd, "_save_diff_artifact", lambda w, br: tmp_path / "a.diff")
    res = cd.dispatch_one({"component": "c", "detail": "fix"}, {}, apply=True, allow_push=True)
    assert res["outcome"] == "advisory_diff"
    assert _pushed(calls) == []


def test_allow_push_flag_is_parsed():
    src = CODER.read_text(encoding="utf-8")
    assert '"--allow-push"' in src
    assert "from_queue=args.from_queue" in src


# ── backup_generated_docs.sh ──────────────────────────────────────────────────────────────────────

GIT = shutil.which("git")


def _shim(tmp_path: Path) -> tuple[Path, Path]:
    """A `git` on PATH that records argv and REFUSES push (exit 99) unless SHIM_ALLOW_PUSH=1."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "git_argv.log"
    shim = bindir / "git"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{log}"\n'
        'if [ "$1" = "push" ] && [ "${SHIM_ALLOW_PUSH:-0}" != "1" ]; then exit 99; fi\n'
        f'exec "{GIT}" "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    return bindir, log


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "linux_launchers").mkdir(parents=True)
    (repo / "docs" / "project").mkdir(parents=True)
    shutil.copy(BACKUP, repo / "linux_launchers" / BACKUP.name)
    (repo / "docs" / "project" / "STATE_OF_REPO_LATEST.md").write_text("state\n", encoding="utf-8")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    subprocess.run([GIT, "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    subprocess.run([GIT, "-C", str(repo), "config", "user.email", "t@example.invalid"], check=True)
    subprocess.run([GIT, "-C", str(repo), "config", "user.name", "t"], check=True)
    bare = tmp_path / "origin.git"
    subprocess.run([GIT, "init", "-q", "--bare", str(bare)], check=True, env=env)
    subprocess.run([GIT, "-C", str(repo), "remote", "add", "origin", str(bare)], check=True)
    return repo


def _run_backup(tmp_path, repo, *args, env_extra=None):
    bindir, log = _shim(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "TRADEAI_REMOTE_PUSH_AUTHORIZED"}
    env.update({"PATH": f"{bindir}:{env['PATH']}", "GIT_CONFIG_GLOBAL": "/dev/null"})
    env.update(env_extra or {})
    p = subprocess.run(["bash", str(repo / "linux_launchers" / BACKUP.name), *args],
                       cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    argv = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return p, argv


@pytest.mark.skipif(GIT is None, reason="git not installed")
def test_backup_cron_argv_commits_locally_and_never_pushes(tmp_path):
    repo = _repo(tmp_path)
    p, argv = _run_backup(tmp_path, repo, env_extra={"TRADEAI_REMOTE_PUSH_AUTHORIZED": "1"})
    assert p.returncode == 0, p.stdout + p.stderr
    assert "local only" in p.stdout
    assert not [a for a in argv if a.startswith("push")]
    local = subprocess.run([GIT, "-C", str(repo), "rev-parse", "-q", "--verify", "refs/heads/generated-docs-backup"],
                           capture_output=True, text=True)
    assert local.returncode == 0          # the backup commit exists locally
    remote = subprocess.run([GIT, "-C", str(tmp_path / "origin.git"), "branch", "--list"], capture_output=True, text=True)
    assert remote.stdout.strip() == ""    # nothing reached the remote


@pytest.mark.skipif(GIT is None, reason="git not installed")
def test_backup_push_flag_without_authorization_does_not_push(tmp_path):
    repo = _repo(tmp_path)
    p, argv = _run_backup(tmp_path, repo, "--push")
    assert p.returncode == 0 and "local only" in p.stdout
    assert not [a for a in argv if a.startswith("push")]


@pytest.mark.skipif(GIT is None, reason="git not installed")
def test_backup_operator_authorized_push_reaches_local_bare_remote(tmp_path):
    repo = _repo(tmp_path)
    p, argv = _run_backup(tmp_path, repo, "--push",
                          env_extra={"TRADEAI_REMOTE_PUSH_AUTHORIZED": "1", "SHIM_ALLOW_PUSH": "1"})
    assert p.returncode == 0, p.stdout + p.stderr
    assert [a for a in argv if a.startswith("push")]
    assert "operator-authorized push" in p.stdout


def test_backup_rejects_unknown_args(tmp_path):
    p = subprocess.run(["bash", str(BACKUP), "--force"], capture_output=True, text=True, timeout=30)
    assert p.returncode == 64


def test_backup_script_names_no_new_token_reference():
    """The change adds no token handling; the only .env read stays the pre-existing failure ping."""
    src = BACKUP.read_text(encoding="utf-8")
    assert src.count("TELEGRAM_BOT_TOKEN") == 1
    assert "push FAILED (will retry next run)" not in src
