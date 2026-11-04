"""Caller-root regression with real Git metadata and an enabled local scan hook.

The shell probe executes the wrapper's exact resolution block, ending BEFORE
passwd-home/trusted-checker lookup. It never replaces production trust paths.
The real checker handles HEAD/dirty state; only external policy/claim/remote
sources are fixture answers. Actual do_push uses its original hook-enabling
pins and a local bare remote. This is routing/content proof, not evidence that
an installed wrapper/checker passed production byte-identity qualification.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "wt/synthetic-caller-root"
SESSION = "synthetic-caller-session"

# This fixture recorder invokes a byte-identical copy of the real scanner. Its
# ROOT and optional .env lookup therefore remain inside the synthetic worktree.
RECORDER = r"""import hashlib, json, subprocess, sys
from pathlib import Path
root = Path.cwd()
updates = sys.stdin.read()
subprocess.run([sys.executable, str(root / "scripts/check_no_secrets.py"), "--tree"], check=True)
def git(*args):
    return subprocess.check_output(["/usr/bin/git", *args], cwd=root).decode().strip()
files = subprocess.check_output(["/usr/bin/git", "ls-files", "-z"], cwd=root).decode().split("\0")
row = {"root": str(root), "head": git("rev-parse", "HEAD"), "updates": updates,
       "files": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files if name}}
common = Path(git("rev-parse", "--git-common-dir"))
if not common.is_absolute():
    common = root / common
with (common / "d13-scan.jsonl").open("a") as stream:
    stream.write(json.dumps(row) + "\n")
"""


class Repos:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "empty-home"
        self.home.mkdir()
        self.env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "LANG": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1"}
        self.canonical = tmp / "canonical"
        self.caller = tmp / "caller worktree"
        self.remote = tmp / "remote.git"
        self.git("init", "--bare", "--initial-branch=main", str(self.remote), cwd=tmp)
        self.git("init", "--initial-branch=main", str(self.canonical), cwd=tmp)
        self.git("config", "user.name", "Synthetic Fixture")
        self.git("config", "user.email", "synthetic@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("remote", "add", "origin", str(self.remote))
        (self.canonical / "scripts").mkdir()
        shutil.copyfile(ROOT / "scripts/check_no_secrets.py", self.canonical / "scripts/check_no_secrets.py")
        (self.canonical / "scripts/d13_scan_fixture.py").write_text(RECORDER)
        hooks = self.canonical / ".githooks"
        hooks.mkdir()
        hook = hooks / "pre-push"
        hook.write_text("#!/bin/sh\nset -eu\nexec /usr/bin/python3 scripts/d13_scan_fixture.py\n")
        hook.chmod(0o755)
        (self.canonical / "payload.txt").write_text("synthetic base\n")
        self.git("add", ".")
        self.git("commit", "-m", "synthetic base")
        self.main = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("worktree", "add", "-b", BRANCH, str(self.caller))
        (self.caller / "payload.txt").write_text("synthetic feature content\n")
        self.git("add", "payload.txt", cwd=self.caller)
        self.git("commit", "-m", "synthetic feature", cwd=self.caller)

    def git(self, *args: str, cwd: Path | None = None, check: bool = True):
        result = subprocess.run(
            ["/usr/bin/git", *args], cwd=cwd or self.canonical, env=self.env, capture_output=True, text=True, timeout=30
        )
        if check:
            assert result.returncode == 0, (args, result.stdout, result.stderr)
        return result

    def resolve(self, cwd: Path):
        source = (ROOT / "bin/agent-push").read_text()
        start = source.index('  session="${AGENT_CLAIM_SESSION:-}"')
        end = source.index('  home="', start)
        # Exact source slice: no altered Git command or injected dispatcher.
        probe = self.canonical / "bin/resolve-caller"
        probe.parent.mkdir(exist_ok=True)
        probe.write_text(
            "#!/bin/bash -p\nset -euo pipefail\nPATH=/usr/bin:/bin\n" + source[start:end] + '\nprintf "%s\\n" "$top"\n'
        )
        return subprocess.run(
            ["/bin/bash", "-p", str(probe)], cwd=cwd, env=self.env, capture_output=True, text=True, timeout=10
        )


@pytest.fixture
def repos(tmp_path):
    return Repos(tmp_path)


@pytest.fixture
def checker(repos, monkeypatch):
    name = "d13_actual_guard_under_test"
    spec = importlib.util.spec_from_file_location(name, ROOT / ".cursor/hooks/guard_push_free.py")
    guard = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, guard)
    spec.loader.exec_module(guard)
    monkeypatch.setattr(guard, "passwd_home", lambda: repos.home)
    cfg = {
        "canonical_url": str(repos.remote),
        "ls_remote_timeout": 10,
        "push_timeout": 30,
        "credential_helper": "synthetic-unused",
    }
    monkeypatch.setattr(guard, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(guard, "ls_remote", lambda *a: {"refs/heads/main": repos.main})
    monkeypatch.setattr(guard, "check_policy", lambda *a: {"version": "30.0.0"})
    monkeypatch.setattr(guard, "check_prepush", lambda *a: None)
    monkeypatch.setattr(guard, "check_broker_paths", lambda *a: None)
    monkeypatch.setattr(guard, "check_budget", lambda *a: {"count": 0, "budget": 2})
    monkeypatch.setattr(
        guard,
        "find_plan",
        lambda *a, **kw: {
            "source": "claim+ratified-policy",
            "approval_ref": "synthetic-policy",
            "scope": {"paths": ["payload.txt"]},
            "session": SESSION,
        },
    )
    monkeypatch.setattr(guard, "standing_policy_module", lambda: types.SimpleNamespace(revoked_marker=lambda: False))
    events = []

    def audit(row, cfg):
        events.append(row)
        return {"chain_hash": "synthetic-" + str(len(events))}

    monkeypatch.setattr(guard, "audit", audit)
    return guard, events


def evaluated(repos, checker):
    resolved = repos.resolve(repos.caller)
    assert resolved.returncode == 0, resolved.stderr
    assert Path(resolved.stdout.strip()) == repos.caller
    guard, _ = checker
    return guard.evaluate(resolved.stdout.strip(), BRANCH, SESSION, bind_session=True)


def test_clean_caller_is_resolved_instead_of_helper_checkout(repos, checker):
    result = evaluated(repos, checker)
    assert result["allow"] is True and result["repo"] == str(repos.caller)
    assert result["head"] == repos.git("rev-parse", "HEAD", cwd=repos.caller).stdout.strip()
    assert result["preview"]["pre_push_executed"] is False
    assert checker[1] == []


def test_nested_caller_directory_still_resolves_its_worktree(repos):
    result = repos.resolve(repos.caller / "scripts")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(repos.caller)


@pytest.mark.parametrize("staged", [False, True])
def test_dirty_caller_still_refused_before_remote_lookup(repos, checker, monkeypatch, staged):
    (repos.caller / "payload.txt").write_text("uncommitted synthetic change\n")
    if staged:
        repos.git("add", "payload.txt", cwd=repos.caller)

    def no_remote(*args):
        raise AssertionError("dirty caller reached remote lookup")

    monkeypatch.setattr(checker[0], "ls_remote", no_remote)
    with pytest.raises(checker[0].Refused, match="uncommitted changes"):
        evaluated(repos, checker)
    assert checker[1] == []


def test_canonical_refused_even_with_requested_feature_branch(repos):
    result = repos.resolve(repos.canonical)
    assert result.returncode != 0
    assert "refused" in result.stderr.lower()
    assert not result.stdout.strip()


def test_main_remains_forbidden_in_real_checker(repos, checker):
    with pytest.raises(checker[0].Refused, match="not an allowed feature-branch"):
        checker[0].evaluate(str(repos.canonical), "main", SESSION, bind_session=True)


def test_non_repository_fails_closed_without_fallback(repos):
    result = repos.resolve(repos.tmp)
    assert result.returncode != 0
    assert "refused" in result.stderr.lower()
    assert not result.stdout.strip()


def test_wrong_checked_out_branch_still_refused(repos, checker):
    repos.git("switch", "-c", "wt/different-synthetic", cwd=repos.caller)
    with pytest.raises(checker[0].Refused, match="not the checked-out HEAD"):
        evaluated(repos, checker)


def test_real_local_push_hook_scans_exact_pushed_content(repos, checker):
    event = evaluated(repos, checker)
    guard, events = checker
    # These are the original production pins, including the ENABLED fixture hook.
    assert f"core.hooksPath={repos.caller / '.githooks'}" in event["pins"]
    result = guard.do_push(event, SESSION, str(repos.caller))
    assert result["allow"] is True, result
    assert [row["event"] for row in events] == ["grant-free-push-intent", "grant-free-push"]
    remote_head = repos.git("rev-parse", f"refs/heads/{BRANCH}", cwd=repos.remote).stdout.strip()
    rows = [json.loads(line) for line in (repos.canonical / ".git/d13-scan.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    scan = rows[0]
    assert scan["root"] == str(repos.caller)
    assert scan["head"] == event["head"] == remote_head
    assert event["head"] in scan["updates"] and f"refs/heads/{BRANCH}" in scan["updates"]
    for name, digest in scan["files"].items():
        blob = subprocess.run(
            ["/usr/bin/git", "show", f"{remote_head}:{name}"],
            cwd=repos.remote,
            env=repos.env,
            capture_output=True,
            check=True,
        ).stdout
        assert hashlib.sha256(blob).hexdigest() == digest, name
    assert (repos.caller / "scripts/check_no_secrets.py").read_bytes() == (
        ROOT / "scripts/check_no_secrets.py"
    ).read_bytes()


def test_actual_scanner_refusal_prevents_local_remote_update(repos, checker):
    # Intentionally invalid synthetic pattern, never a real credential.
    (repos.caller / "payload.txt").write_text("ghp_" + "S" * 36 + "\n")
    repos.git("add", "payload.txt", cwd=repos.caller)
    repos.git("commit", "-m", "synthetic scanner negative", cwd=repos.caller)
    event = evaluated(repos, checker)
    result = checker[0].do_push(event, SESSION, str(repos.caller))
    assert result["allow"] is False and result["outcome"] == "failed"
    assert repos.git("rev-parse", "--verify", f"refs/heads/{BRANCH}", cwd=repos.remote, check=False).returncode != 0
    assert not (repos.canonical / ".git/d13-scan.jsonl").exists()
