"""Policy freshness gates (operator 2026-10-28): claim, pre-commit, pre-push, CI, session start, deploy poller.

Each gate is exercised in a throwaway world (a bare "origin" plus clones under tmp_path) for OK, STALE, UNKNOWN, a
branch that bumps AGENTS.md on top of main (exempt) and offline mode. The hooks run as real subprocesses from copies
of the tracked scripts, so what is tested is what git runs.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import agent_claim as CLI
from scripts.lib import agent_claim_board as B
from scripts.lib import policy_freshness as PF

ROOT = Path(__file__).resolve().parents[1]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


CAPS = _load("scripts/check_agents_policy_state.py", "_pf_check_agents_policy_state")
POLL = _load("scripts/deploy_on_main_poll.py", "_pf_deploy_on_main_poll")

STALE_LINE = "STALE_POLICY: your AGENTS.md is 1.0.0, origin/main is 2.0.0; work from fresh origin/main"


def agents_md(version: str, extra: str = "") -> str:
    return f"# AGENTS.md\n\n```\nPolicy-Version:      {version}\nStatus:              ACTIVE\n```\n\nRules.\n{extra}"


def git(cwd: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True, timeout=60
    ).stdout.strip()


def commit_file(repo: Path, text: str, msg: str, name: str = "AGENTS.md") -> str:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for k, v in (("NAME", "Policy Test"), ("EMAIL", "policy@test.local")):
        monkeypatch.setenv(f"GIT_AUTHOR_{k}", v)
        monkeypatch.setenv(f"GIT_COMMITTER_{k}", v)
    monkeypatch.setenv(PF.ENV_FETCH_TIMEOUT, "20")
    monkeypatch.setenv(CLI.ENV_POLICY_UNDER_PYTEST, "1")  # this file tests the gate itself


HOOK_FILES = (
    "scripts/agent_claim.py",
    "scripts/agent_claim_precommit.sh",
    "scripts/lib/agent_claim_board.py",
    "scripts/lib/agent_claim_lifecycle.py",
    "scripts/lib/agent_claim_worklog.py",
    "scripts/lib/agent_task_board.py",
    "scripts/lib/agent_file_lease.py",
    "scripts/lib/persistent_state_root.py",
    "scripts/lib/policy_freshness.py",
    "scripts/lib/tradeai_push_budget.py",
    ".githooks/pre-push",
    "scripts/agent_session_start.sh",
)


@pytest.fixture
def world(tmp_path):
    """origin with main at 1.0.0 carrying copies of the hook scripts; ``agent`` clones it (hooks installed)."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    up = tmp_path / "upstream"
    git(tmp_path, "clone", "-q", str(origin), str(up))
    git(up, "checkout", "-q", "-b", "main")
    for rel in HOOK_FILES:
        (up / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, up / rel)
    (up / "scripts" / "__init__.py").write_text("")
    (up / "scripts" / "lib" / "__init__.py").write_text("")
    (up / "scripts" / "check_no_secrets.py").write_text("import sys\nsys.exit(0)\n")
    os.chmod(up / ".githooks/pre-push", os.stat(up / ".githooks/pre-push").st_mode | stat.S_IEXEC)
    (up / "AGENTS.md").write_text(agents_md("1.0.0"))
    git(up, "add", ".")
    git(up, "commit", "-q", "-m", "policy 1.0.0")
    git(up, "push", "-q", "origin", "main")
    agent = tmp_path / "agent"
    git(tmp_path, "clone", "-q", str(origin), str(agent))

    def advance(version: str) -> None:
        commit_file(up, agents_md(version), f"policy {version}")
        git(up, "push", "-q", "origin", "main")

    return {"origin": origin, "up": up, "agent": agent, "advance": advance, "claims": tmp_path / "claims"}


def _hook_env(w: dict, **extra: str) -> dict:
    env = {
        **os.environ,
        "TRADEAI_AGENT_CLAIMS_DIR": str(w["claims"]),
        "AGENT_CLAIM_NO_GH": "1",
        "AGENT_CLAIM_SESSION": "me",
        "TRADEAI_SKIP_SECRETS_SCAN": "1",
        "TRADEAI_PUSH_BUDGET_PATH": str(w["agent"] / ".git/tradeai-push-budget.json"),
        "HOME": str(w["claims"].parent / "home"),
        **extra,
    }
    env.pop("PYTEST_CURRENT_TEST", None)
    return env


# ------------------------------------------------------------------------------------------- claim gate


def _claim(w: dict, monkeypatch, *paths: str) -> int:
    monkeypatch.chdir(w["agent"])
    return CLI.main(
        [
            "--claims-dir",
            str(w["claims"]),
            "--session",
            "s1",
            "--no-gh",
            "claim",
            "--task",
            "t",
            "--paths",
            *(paths or ("docs/a.md",)),
        ]
    )


def test_claim_ok_records_policy_version_and_blob(world, monkeypatch, capsys):
    assert _claim(world, monkeypatch) == 0
    doc = B.ClaimBoard(world["claims"]).views()[0][0].doc
    blob = git(world["agent"], "rev-parse", "HEAD:AGENTS.md")
    assert (doc["policy_version"], doc["policy_blob"], doc["policy_check"]) == ("1.0.0", blob, "OK")


def test_claim_refused_on_stale_policy(world, monkeypatch, capsys):
    world["advance"]("2.0.0")
    assert _claim(world, monkeypatch) == 1
    err = capsys.readouterr().err
    assert STALE_LINE in err and "refused: claim is not allowed under a stale AGENTS.md" in err
    assert B.ClaimBoard(world["claims"]).views()[0] == []  # nothing was written


def test_claim_add_next_and_take_are_gated_too(world, monkeypatch, capsys):
    assert _claim(world, monkeypatch) == 0
    world["advance"]("2.0.0")
    rc = CLI.main(["--claims-dir", str(world["claims"]), "--session", "s1", "--no-gh", "claim", "--add", "docs/b.md"])
    assert rc == 1 and STALE_LINE in capsys.readouterr().err
    rc = CLI.main(["--claims-dir", str(world["claims"]), "--session", "s1", "--no-gh", "next"])
    assert rc == 1 and STALE_LINE in capsys.readouterr().err


def test_claim_unknown_warns_and_proceeds(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "solo"
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    commit_file(repo, agents_md("1.0.0"), "init")
    monkeypatch.chdir(repo)
    rc = CLI.main(
        ["--claims-dir", str(tmp_path / "claims"), "--session", "s1", "--no-gh", "claim", "--task", "t", "--paths", "x"]
    )
    assert rc == 0 and "WARN: UNKNOWN_POLICY" in capsys.readouterr().err
    assert B.ClaimBoard(tmp_path / "claims").views()[0][0].doc["policy_check"] == "UNKNOWN"


def test_claim_exempt_branch_bumping_agents_md(world, monkeypatch):
    git(world["agent"], "checkout", "-q", "-b", "bump")
    commit_file(world["agent"], agents_md("2.0.0"), "bump")
    assert _claim(world, monkeypatch) == 0


def test_claim_offline_with_fresh_last_fetch_proceeds_with_warning(world, monkeypatch, capsys):
    git(world["agent"], "remote", "set-url", "origin", str(world["origin"]) + "-gone")
    assert _claim(world, monkeypatch) == 0
    assert "offline: compared with origin/main as last fetched" in capsys.readouterr().err


def test_gate_is_off_under_pytest_unless_a_test_opts_in(monkeypatch):
    monkeypatch.delenv(CLI.ENV_POLICY_UNDER_PYTEST)
    assert CLI._policy_gate("claim") == (True, {"policy_check": "skipped_test"})
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.setattr(PF, "evaluate", lambda *a, **k: PF.Freshness(PF.STALE, "1.0.0", "2.0.0"))
    assert CLI._policy_gate("claim")[0] is False
    monkeypatch.setattr(CLI, "_pf", lambda: None)  # library missing: a warning, never a crash or a silent pass
    assert CLI._policy_gate("claim") == (True, {"policy_check": "UNKNOWN"})


# ------------------------------------------------------------------------------------------- pre-commit


def _precommit(w: dict) -> subprocess.CompletedProcess:
    (w["agent"] / "docs").mkdir(exist_ok=True)
    (w["agent"] / "docs" / "a.md").write_text("x")
    git(w["agent"], "add", "docs/a.md")
    return subprocess.run(
        ["bash", "scripts/agent_claim_precommit.sh"],
        cwd=w["agent"],
        env=_hook_env(w),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_precommit_ok_continues(world):
    p = _precommit(world)
    assert p.returncode == 0, p.stderr
    assert "STALE_POLICY" not in p.stderr and "UNKNOWN_POLICY" not in p.stderr


def test_precommit_refuses_stale(world):
    world["advance"]("2.0.0")
    p = _precommit(world)
    assert p.returncode == 1 and STALE_LINE in p.stderr and "commit refused under a stale AGENTS.md" in p.stderr


def test_precommit_exempt_bump_branch(world):
    world["advance"]("2.0.0")
    git(world["agent"], "pull", "-q", "origin", "main")
    (world["agent"] / "AGENTS.md").write_text(agents_md("3.0.0"))
    git(world["agent"], "add", "AGENTS.md")
    assert _precommit(world).returncode == 0


def test_precommit_unknown_and_missing_lib_warn_not_block(world):
    git(world["agent"], "remote", "remove", "origin")
    git(world["agent"], "update-ref", "-d", "refs/remotes/origin/main")
    p = _precommit(world)
    assert p.returncode == 0 and "UNKNOWN_POLICY" in p.stderr and "a warning, not a pass" in p.stderr
    (world["agent"] / "scripts/lib/policy_freshness.py").unlink()
    p = _precommit(world)
    assert p.returncode == 0 and "freshness NOT verified" in p.stderr


def test_precommit_offline_stale_still_refuses(world):
    world["advance"]("2.0.0")
    git(world["agent"], "fetch", "-q", "origin")
    git(world["agent"], "remote", "set-url", "origin", str(world["origin"]) + "-gone")
    p = _precommit(world)
    assert p.returncode == 1 and "offline: compared with origin/main" in p.stderr


# ------------------------------------------------------------------------------------------- pre-push


def _push(w: dict, branch: str) -> subprocess.CompletedProcess:
    git(w["agent"], "config", "core.hooksPath", ".githooks")
    return subprocess.run(
        ["git", "push", "-q", "origin", branch],
        cwd=w["agent"],
        env=_hook_env(w, TRADEAI_REMOTE_PUSH_AUTHORIZED="1"),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_prepush_ok_pushes(world):
    git(world["agent"], "checkout", "-q", "-b", "feat/ok")
    commit_file(world["agent"], "x\n", "work", name="docs/a.md")
    p = _push(world, "feat/ok")
    assert p.returncode == 0, p.stderr
    assert git(world["origin"], "rev-parse", "--verify", "-q", "refs/heads/feat/ok", check=False)


def test_prepush_refuses_stale_before_budget_or_grant(world):
    git(world["agent"], "checkout", "-q", "-b", "feat/old")
    commit_file(world["agent"], "x\n", "work", name="docs/a.md")
    world["advance"]("2.0.0")
    p = _push(world, "feat/old")
    assert p.returncode != 0 and STALE_LINE in p.stderr and "REMOTE PUSH BLOCKED (stale policy)" in p.stderr
    assert not (world["agent"] / ".git/tradeai-push-budget.json").exists()  # no budget count was charged
    assert not git(world["origin"], "rev-parse", "--verify", "-q", "refs/heads/feat/old", check=False)


def test_prepush_exempt_bump_and_unauthorized_still_blocked_first(world):
    git(world["agent"], "checkout", "-q", "-b", "feat/bump")
    commit_file(world["agent"], agents_md("2.0.0"), "bump")
    assert _push(world, "feat/bump").returncode == 0
    p = subprocess.run(
        ["git", "push", "-q", "origin", "feat/bump"],
        cwd=world["agent"],
        env=_hook_env(world, TRADEAI_REMOTE_PUSH_AUTHORIZED="0"),
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0 and "REMOTE PUSH BLOCKED." in p.stderr  # authorization is still checked first


def test_prepush_offline_falls_back(world):
    git(world["agent"], "checkout", "-q", "-b", "feat/off")
    commit_file(world["agent"], "x\n", "work", name="docs/a.md")
    push_url = str(world["origin"])
    git(world["agent"], "remote", "set-url", "origin", push_url + "-gone")
    git(world["agent"], "remote", "set-url", "--push", "origin", push_url)  # fetch fails, push still reaches origin
    p = _push(world, "feat/off")
    assert p.returncode == 0, p.stderr


# ------------------------------------------------------------------------------------------- CI


def test_ci_rule_fails_a_pr_behind_the_base_tip():
    old, new = agents_md("25.0.1"), agents_md("26.0.0")
    errs = CAPS.check_not_behind(old, new, old)
    assert errs and errs[0].startswith("STALE_POLICY: this PR's AGENTS.md is 25.0.1, the base branch has 26.0.0")


def test_ci_rule_passes_up_to_date_bumping_and_no_base():
    v26, v27 = agents_md("26.0.0"), agents_md("27.0.0")
    assert CAPS.check_not_behind(v26, v26, v26) == []
    assert CAPS.check_not_behind(v27, v26, v26) == []  # the PR bumps on top of main
    assert CAPS.check_not_behind(agents_md("26.0.1"), agents_md("26.1.0"), v26) == []  # the PR bumps: rule 5 governs
    assert CAPS.check_not_behind(v26, None, None) == []  # push to main / local run


def test_ci_script_end_to_end(world, monkeypatch, capsys):
    a = world["agent"]
    git(a, "checkout", "-q", "-b", "feat/x")
    world["advance"]("2.0.0")
    git(a, "fetch", "-q", "origin")
    monkeypatch.chdir(a)
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    monkeypatch.setattr(CAPS, "check", lambda text, on_main: [])  # rules 1-4 need a real history table
    assert CAPS.main([]) == 1 and "STALE_POLICY" in capsys.readouterr().out
    git(a, "merge", "-q", "origin/main")
    assert CAPS.main([]) == 0 and "not behind origin/main (2.0.0): ok" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------- session start


def test_session_start_prints_stale_loudly_and_exits_zero(world):
    world["advance"]("2.0.0")
    p = subprocess.run(
        ["bash", "scripts/agent_session_start.sh"],
        cwd=world["agent"],
        env=_hook_env(world),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert p.returncode == 0 and STALE_LINE in p.stdout and "!!!!!!!!" in p.stdout
    git(world["agent"], "pull", "-q", "origin", "main")
    p = subprocess.run(
        ["bash", "scripts/agent_session_start.sh"],
        cwd=world["agent"],
        env=_hook_env(world),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert p.returncode == 0 and "policy OK: AGENTS.md 2.0.0 matches origin/main" in p.stdout


# ------------------------------------------------------------------------------------------- deploy poller hook


def test_poller_broadcast_is_dry_unless_apply_and_never_raises(monkeypatch, tmp_path):
    import scripts.lib.policy_version_broadcast as PB

    seen = []
    monkeypatch.setattr(PB, "run", lambda repo, *, apply: seen.append(apply) or {"action": "none", "mode": "x"})
    assert POLL._policy_broadcast({"reason": "fetch_failed: x"}, repo=tmp_path, apply=True)["action"] == "skipped"
    POLL._policy_broadcast({}, repo=tmp_path, apply=False)
    POLL._policy_broadcast({}, repo=tmp_path, apply=True)
    assert seen == [False, True]
    monkeypatch.setattr(PB, "run", lambda repo, *, apply: 1 / 0)
    assert POLL._policy_broadcast({}, repo=tmp_path, apply=True)["action"] == "error"


def test_poller_main_passes_apply_only_without_dry_run(monkeypatch, tmp_path):
    import scripts.lib.deploy_on_main as DOM

    monkeypatch.setattr(DOM, "poll_once", lambda **k: {"action": "noop", "outcome": "noop"})
    got = []
    monkeypatch.setattr(POLL, "_policy_broadcast", lambda result, *, repo, apply: got.append(apply) or {})
    POLL.main(["--repo", str(tmp_path), "--apply", "--dry-run", "--no-fetch"])
    POLL.main(["--repo", str(tmp_path), "--apply", "--no-fetch"])
    assert got == [False, True]


# ------------------------------------------------------------------------------------------- template + docs


def test_pr_template_carries_the_project_copy_checklist():
    t = (ROOT / ".github/pull_request_template.md").read_text()
    assert "update the claude.ai Project copy of AGENTS.md" in t
    assert t.startswith("<!--") and "## In plain English" in t


def test_cursor_rule_runs_the_freshness_check():
    assert "scripts/lib/policy_freshness.py" in (ROOT / "docs/ops/agent_start/cursor-rule.md").read_text()
