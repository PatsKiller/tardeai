"""Deploy poller layout and exact checkout alignment, using only temporary Git fixtures."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from scripts.lib import deploy_on_main as deploy

ROOT = Path(__file__).resolve().parents[1]
REAL_RUN = subprocess.run


def git(repo, *args):
    result = REAL_RUN(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    repo = tmp_path / "canonical"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    hooks = tmp_path / "empty-hooks"
    hooks.mkdir()
    git(repo, "config", "core.hooksPath", str(hooks))
    (repo / "scripts").mkdir()
    (repo / "scripts/cio_phase2_exact_main_deploy.sh").write_text("# fixture only; native calls are injected\n")
    (repo / "version").write_text("base\n")
    git(repo, "add", "scripts/cio_phase2_exact_main_deploy.sh", "version")
    git(repo, "commit", "--quiet", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "version").write_text("target\n")
    git(repo, "add", "version")
    git(repo, "commit", "--quiet", "-m", "target")
    target = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", target)
    git(repo, "checkout", "--quiet", "--detach", base)
    return SimpleNamespace(repo=repo, base=base, target=target)


def native_spy(monkeypatch, checkout, *, prepare_rc=0, suppress_merge=False):
    calls = []

    def run(args, **kwargs):
        if args[0] == "bash":
            calls.append((args, git(checkout.repo, "rev-parse", "HEAD"), kwargs))
            rc = prepare_rc if args[-1] == "prepare" else 0
            return SimpleNamespace(returncode=rc, stdout="", stderr="fixture CI refusal" if rc else "")
        if suppress_merge and "merge" in args:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return REAL_RUN(args, **kwargs)

    monkeypatch.setattr(deploy.subprocess, "run", run)
    return calls


def test_current_code_uses_explicit_git_checkout_from_source_unit(tmp_path, monkeypatch):
    home = tmp_path / "home"
    release = home / "trade-ai-releases/portfolio-server/release-without-git"
    (release / "scripts").mkdir(parents=True)
    (release / "scripts/deploy_on_main_poll.py").write_bytes((ROOT / "scripts/deploy_on_main_poll.py").read_bytes())
    (release.parent / "CURRENT").symlink_to(release, target_is_directory=True)
    canonical = home / "trade-ai-v12-rebuild/trade-ai-v12-rebuild"
    canonical.mkdir(parents=True)
    source = (ROOT / "config/systemd/user/tradeai-deploy-on-main.service").read_text()
    line = next(line for line in source.splitlines() if line.startswith("ExecStart="))
    argv = shlex.split(line.split("=", 1)[1].replace("%h", str(home)))
    assert argv[argv.index("--repo") + 1] == str(canonical)
    spec = importlib.util.spec_from_file_location("fixture_release_poller", argv[1])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ROOT == release and not (release / ".git").exists()
    seen = []
    monkeypatch.setattr(deploy, "poll_once", lambda **kw: seen.append(kw) or {"action": "noop"})
    assert module.main(argv[2:]) == 0
    assert seen == [{"repo": canonical.resolve(), "dry_run": False, "fetch": True, "apply": True}]


def test_clean_checkout_fast_forwards_exact_target_before_native_prepare(checkout, monkeypatch):
    calls = native_spy(monkeypatch, checkout)
    rc, message = deploy.run_deploy_script(checkout.repo, checkout.target)
    assert rc == 0 and message.startswith("checkout_fast_forwarded")
    assert [call[0][-1] for call in calls] == ["prepare", "promote"]
    assert all(call[1] == checkout.target for call in calls)
    assert git(checkout.repo, "status", "--porcelain") == ""


def test_already_at_target_does_not_create_commit_or_move_history(checkout, monkeypatch):
    git(checkout.repo, "merge", "--ff-only", checkout.target)
    calls = native_spy(monkeypatch, checkout)
    rc, message = deploy.run_deploy_script(checkout.repo, checkout.target)
    assert rc == 0 and message.startswith("checkout_already_at_target")
    assert git(checkout.repo, "rev-parse", "HEAD") == checkout.target and len(calls) == 2


@pytest.mark.parametrize("kind", ["tracked", "untracked"])
def test_dirty_checkout_is_preserved_and_refused_before_prepare(checkout, monkeypatch, kind):
    path = checkout.repo / ("version" if kind == "tracked" else "untracked-fixture")
    path.write_text("operator work\n")
    calls = native_spy(monkeypatch, checkout)
    rc, reason = deploy.run_deploy_script(checkout.repo, checkout.target)
    assert rc and reason == "checkout_dirty" and not calls
    assert git(checkout.repo, "rev-parse", "HEAD") == checkout.base
    assert path.read_text() == "operator work\n"


def test_divergent_checkout_is_never_reset_or_rewritten(checkout, monkeypatch):
    (checkout.repo / "version").write_text("unrelated local work\n")
    git(checkout.repo, "add", "version")
    git(checkout.repo, "commit", "--quiet", "-m", "local branch work")
    local = git(checkout.repo, "rev-parse", "HEAD")
    calls = native_spy(monkeypatch, checkout)
    rc, reason = deploy.run_deploy_script(checkout.repo, checkout.target)
    assert rc and reason == "checkout_not_fast_forward" and not calls
    assert git(checkout.repo, "rev-parse", "HEAD") == local


def test_target_must_still_be_exact_origin_main(checkout, monkeypatch):
    calls = native_spy(monkeypatch, checkout)
    rc, reason = deploy.run_deploy_script(checkout.repo, checkout.base)
    assert rc and reason == "checkout_target_not_current_main" and not calls
    assert git(checkout.repo, "rev-parse", "HEAD") == checkout.base


def test_failed_alignment_readback_never_prepares(checkout, monkeypatch):
    calls = native_spy(monkeypatch, checkout, suppress_merge=True)
    rc, reason = deploy.run_deploy_script(checkout.repo, checkout.target)
    assert rc and reason == "checkout_head_mismatch" and not calls


def test_native_ci_or_grant_refusal_still_stops_before_promote(checkout, monkeypatch):
    monkeypatch.delenv("ALLOW_MAINTREE_GIT", raising=False)
    calls = native_spy(monkeypatch, checkout, prepare_rc=23)
    rc, message = deploy.run_deploy_script(checkout.repo, checkout.target)
    assert rc == 23 and "prepare:rc=23" in message
    assert [call[0][-1] for call in calls] == ["prepare"]
    assert all("ALLOW_MAINTREE_GIT" not in call[2]["env"] for call in calls)


def test_dry_run_does_not_move_checkout_or_invoke_native(checkout, monkeypatch):
    calls = native_spy(monkeypatch, checkout)
    rc, message = deploy.run_deploy_script(checkout.repo, checkout.target, dry_run=True)
    assert rc == 0 and message == "dry_run:would_prepare_promote" and not calls
    assert git(checkout.repo, "rev-parse", "HEAD") == checkout.base


@pytest.fixture
def isolated_poll(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(deploy, "state_dir", lambda: state)
    monkeypatch.setattr(deploy, "write_receipt", lambda **kw: None)
    monkeypatch.setattr(deploy, "decide", lambda **kw: deploy.PollDecision("promote", "fixture", "a" * 40, "b" * 40))
    monkeypatch.setattr(deploy, "run_deploy_script", lambda *a, **kw: pytest.fail("prepare reached"))
    return state


def test_stop_recheck_prevents_checkout_alignment(isolated_poll, monkeypatch):
    monkeypatch.setattr(deploy, "stop_latched", lambda *a: (True, "fixture-stop"))
    out = deploy.poll_once(repo=isolated_poll, fetch=False, apply=True)
    assert out["outcome"] == "refuse" and out["reason"] == "stop_under_lock:fixture-stop"


def test_delegation_revoked_under_lock_prevents_checkout_alignment(isolated_poll, monkeypatch):
    monkeypatch.setattr(deploy, "stop_latched", lambda *a: (False, "ABSENT"))
    monkeypatch.setattr(deploy, "deploy_delegation_armed", lambda: (False, "REVOKED"))
    out = deploy.poll_once(repo=isolated_poll, fetch=False, apply=True)
    assert out["outcome"] == "refuse" and out["reason"] == "delegation_under_lock:REVOKED"


def test_global_lock_busy_prevents_checkout_alignment(isolated_poll, monkeypatch):
    from scripts.lib import release_control

    class Busy:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            raise release_control.LockBusy("fixture")

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(release_control, "GlobalReleaseLock", Busy)
    out = deploy.poll_once(repo=isolated_poll, fetch=False, apply=True)
    assert out["outcome"] == "refuse" and out["reason"] == "global_release_lock_busy"


def test_new_ci_gate_is_valid_and_includes_the_fixture():
    from scripts.lib.ci_gates import validate

    path = ROOT / "config/ci_gates/deploy_on_main_repo_20261026.json"
    gate = validate(json.loads(path.read_text()), stem=path.stem)
    assert gate["files"] == ["tests/test_deploy_on_main_repo_20261026.py"]
