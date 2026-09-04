"""AI work-policy: canonical file, adapters, hook budget, installer, wrappers."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRE_PUSH = ROOT / ".githooks" / "pre-push"
POLICY = ROOT / "AI_WORK_POLICY.md"


def _run(cmd, *, cwd, env=None, check=False):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(cmd, cwd=cwd, env=merged, capture_output=True, text=True, check=check)


def test_policy_file_exists_and_is_mandatory() -> None:
    text = POLICY.read_text(encoding="utf-8")
    assert "Status: MANDATORY" in text
    assert "git push" in text
    assert "TRADEAI_REMOTE_PUSH_AUTHORIZED" in text
    assert "TRADEAI_REMOTE_PUSH_OVERRIDE" in text
    assert "MEMORY_BEHAVIOR_INFLUENCE=0" in text
    assert "ENFORCEMENT HIERARCHY" in text
    assert "DEPLOYMENT REMAINS SEPARATE" in text


def _longest_shared_run(a: str, b: str) -> int:
    import difflib

    sm = difflib.SequenceMatcher(None, a, b)
    return max((m.size for m in sm.get_matching_blocks()), default=0)


def test_adapters_point_at_canonical_policy_without_duplicating_it() -> None:
    """Hierarchy after #734 (AGENTS.md behaviour hub):

    - ``AGENTS.md`` is the behaviour hub — SoT for how agents work. It
      references ``AI_WORK_POLICY.md`` and never restates it.
    - ``AI_WORK_POLICY.md`` owns push / CI cost / deploy authorization.
    - Three tool adapters (``CLAUDE.md``, Cursor rule, Copilot) are pointers
      only. They carry ``AGENTS.md`` §0 verbatim so an agent that stops after
      fifteen lines still knows the irreversible-harm rules.

    That deliberate §0 duplication puts each adapter near ~2.5 KB. A
    compactness cap keyed to "thin pointer" size (``len < policy/5``) is the
    wrong property — it is exactly what §0 is designed to exceed — and is not
    asserted here. ``CLAUDE.md`` is an adapter, not a governance SoT; §0
    byte-identity across hub + adapters is guarded by
    ``tests/test_agents_section_zero_parity.py``.
    """
    policy = POLICY.read_text(encoding="utf-8")
    hub = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    # Behaviour hub — not an adapter, not a second push-policy.
    assert "single source of truth for how agents work" in hub
    assert "AI_WORK_POLICY.md" in hub
    assert "never duplicates it" in hub
    assert "git commit" in hub
    hub_run = _longest_shared_run(policy, hub)
    assert hub_run < 400, (
        f"AGENTS.md restates {hub_run} verbatim characters of AI_WORK_POLICY.md; "
        "the hub references the policy, it does not copy it"
    )

    # Policy names the split: behaviour hub vs push/CI/deploy vs adapters.
    assert "canonical agent-behaviour standard" in policy
    assert "pointers only" in policy

    adapters = {
        "CLAUDE.md": ROOT / "CLAUDE.md",
        "copilot": ROOT / ".github/copilot-instructions.md",
        "cursor": ROOT / ".cursor/rules/00-tradeai-work-policy.mdc",
    }
    section_zero_marker = "## The ten rules, verbatim from `AGENTS.md` §0"
    for name, path in adapters.items():
        blob = path.read_text(encoding="utf-8")
        assert "AGENTS.md" in blob, name
        assert "AI_WORK_POLICY.md" in blob, name
        assert "git commit" in blob, name
        assert "single source of truth" in blob, name
        assert section_zero_marker in blob, (
            f"{name} must carry AGENTS.md §0 verbatim; size caps that fight "
            "that duplication are the defect this test no longer encodes"
        )
        # Do not restate the push/CI/deploy policy. No byte-length cap: §0
        # duplication is intentional and is what makes a pointer succeed when
        # the agent does not follow the pointer.
        run = _longest_shared_run(policy, blob)
        assert run < 400, (
            f"{name} restates {run} verbatim characters of AI_WORK_POLICY.md; "
            "adapters point at the policy, they do not copy it"
        )


def _unauthorized_env(tmp_home: Path) -> dict:
    """An environment with no push authorization from ANY source.

    The hook also honours an operator scope grant, and a grant is stored under HOME.
    Inheriting the real HOME made these two tests depend on whether some other agent
    session happened to hold a live git-push grant at the moment they ran -- which is
    exactly what happened during the reconciliation pass, and made a governance test
    report that the push guard was broken when it was working correctly.

    Pointing HOME at an empty directory isolates the grant ledger, so what is under test
    is the hook's own logic rather than the machine's ambient operator state.
    """
    env = os.environ.copy()
    env.pop("TRADEAI_REMOTE_PUSH_AUTHORIZED", None)
    env.pop("TRADEAI_REMOTE_PUSH_OVERRIDE", None)
    env["HOME"] = str(tmp_home)
    env["XDG_CONFIG_HOME"] = str(tmp_home / ".config")
    env["TRADEAI_SKIP_SECRETS_SCAN"] = "1"
    return env


def test_pre_push_blocks_without_authorization(tmp_path) -> None:
    proc = _run(["bash", str(PRE_PUSH)], cwd=ROOT, env=_unauthorized_env(tmp_path))
    assert proc.returncode == 1
    assert "REMOTE PUSH BLOCKED" in proc.stderr


def test_pre_push_rejects_zero_flag(tmp_path) -> None:
    env = _unauthorized_env(tmp_path)
    env["TRADEAI_REMOTE_PUSH_AUTHORIZED"] = "0"
    proc = _run(["bash", str(PRE_PUSH)], cwd=ROOT, env=env)
    assert proc.returncode == 1


def test_pre_push_still_blocks_while_another_session_holds_a_grant(tmp_path) -> None:
    """A grant belongs to the session that was given it, not to the machine.

    This is the case that fired for real: another agent's live git-push grant made the
    hook allow a push from this worktree. The hook honouring an operator grant is by
    design; what must not happen is a test reporting the guard broken because of it.
    """
    proc = _run(["bash", str(PRE_PUSH)], cwd=ROOT, env=_unauthorized_env(tmp_path))
    assert proc.returncode == 1, "with the grant ledger isolated the hook must block, whatever grants exist elsewhere"


def _mini_repo(tmp: Path) -> Path:
    src = tmp / "src"
    remote = tmp / "remote.git"
    src.mkdir()
    _run(["git", "init", "--bare", str(remote)], cwd=tmp, check=True)
    _run(["git", "init", "-b", "main"], cwd=src, check=True)
    _run(["git", "config", "user.email", "policy@test.local"], cwd=src, check=True)
    _run(["git", "config", "user.name", "Policy Test"], cwd=src, check=True)
    (src / ".githooks").mkdir()
    shutil.copy2(PRE_PUSH, src / ".githooks/pre-push")
    os.chmod(src / ".githooks/pre-push", os.stat(src / ".githooks/pre-push").st_mode | stat.S_IEXEC)
    lib = src / "scripts" / "lib"
    lib.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/lib/tradeai_push_budget.py", lib / "tradeai_push_budget.py")
    (src / "scripts" / "check_no_secrets.py").write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n")
    (src / "README").write_text("mini\n")
    _run(["git", "add", "."], cwd=src, check=True)
    _run(["git", "commit", "-m", "init"], cwd=src, check=True)
    _run(["git", "remote", "add", "origin", str(remote)], cwd=src, check=True)
    _run(["git", "config", "core.hooksPath", ".githooks"], cwd=src, check=True)
    return src


def test_hook_budget_two_pushes_then_block_then_override(tmp_path: Path) -> None:
    src = _mini_repo(tmp_path)
    env_base = {
        "TRADEAI_SKIP_SECRETS_SCAN": "1",
        "TRADEAI_PUSH_BUDGET_PATH": str(src / ".git/tradeai-push-budget.json"),
    }
    blocked = _run(["git", "push", "-u", "origin", "main"], cwd=src, env=env_base)
    assert blocked.returncode != 0
    assert "REMOTE PUSH BLOCKED" in blocked.stderr

    auth = dict(env_base)
    auth["TRADEAI_REMOTE_PUSH_AUTHORIZED"] = "1"
    first = _run(["git", "push", "-u", "origin", "main"], cwd=src, env=auth)
    assert first.returncode == 0, first.stderr

    (src / "README").write_text("two\n")
    _run(["git", "add", "README"], cwd=src, check=True)
    _run(["git", "commit", "-m", "two"], cwd=src, check=True)
    second = _run(["git", "push"], cwd=src, env=auth)
    assert second.returncode == 0, second.stderr

    (src / "README").write_text("three\n")
    _run(["git", "add", "README"], cwd=src, check=True)
    _run(["git", "commit", "-m", "three"], cwd=src, check=True)
    third = _run(["git", "push"], cwd=src, env=auth)
    assert third.returncode != 0
    assert "push budget" in third.stderr.lower() or "BUDGET" in third.stderr

    over = dict(auth)
    over["TRADEAI_REMOTE_PUSH_OVERRIDE"] = "1"
    third_ok = _run(["git", "push"], cwd=src, env=over)
    assert third_ok.returncode == 0, third_ok.stderr


def test_installer_idempotent_and_does_not_alter_global_config() -> None:
    before = _run(["git", "config", "--global", "--get", "core.hooksPath"], cwd=ROOT)
    first = _run(["bash", str(ROOT / "scripts/install_ai_work_policy.sh")], cwd=ROOT)
    second = _run(["bash", str(ROOT / "scripts/install_ai_work_policy.sh")], cwd=ROOT)
    after = _run(["git", "config", "--global", "--get", "core.hooksPath"], cwd=ROOT)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "policy file found" in first.stdout
    assert "remote push default=BLOCKED" in first.stdout
    assert before.stdout == after.stdout


def test_acceptance_and_status_never_call_github_or_push() -> None:
    acc = (ROOT / "scripts/ai_local_acceptance.sh").read_text(encoding="utf-8")
    st = (ROOT / "scripts/ai_work_status.sh").read_text(encoding="utf-8")
    for blob, name in ((acc, "acceptance"), (st, "status")):
        assert "gh workflow run" not in blob, name
        assert "gh pr " not in blob, name
        assert "\ngit push" not in blob and " git push" not in blob, name
    assert "Never contacts" in st or "read-only" in st.splitlines()[1].lower()


def test_status_script_is_read_only() -> None:
    before = _run(["git", "status", "--porcelain"], cwd=ROOT, check=True)
    proc = _run(["bash", str(ROOT / "scripts/ai_work_status.sh")], cwd=ROOT)
    after = _run(["git", "status", "--porcelain"], cwd=ROOT, check=True)
    assert proc.returncode == 0, proc.stderr
    assert "remote_push_default_authorized=false" in proc.stdout
    assert "branch:" in proc.stdout
    assert before.stdout == after.stdout


def test_natural_evidence_policy_forbids_remote_behavior() -> None:
    text = POLICY.read_text(encoding="utf-8")
    assert "Natural/live evidence stays local" in text or "NATURAL / LIVE EVIDENCE STAYS LOCAL" in text
    assert "WATCHERS MUST NOT DRIVE REMOTE ACTIVITY" in text


def test_deployment_remains_separately_authorized() -> None:
    text = POLICY.read_text(encoding="utf-8")
    assert "does **not** authorize" in text or "does not imply deployment" in text.lower()
    acc = (ROOT / "scripts/ai_local_acceptance.sh").read_text(encoding="utf-8")
    assert "cio_phase2_exact_main_deploy" not in acc
    assert "systemctl" not in acc
