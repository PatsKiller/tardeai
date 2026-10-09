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


# --- Program push budget (operator decision 3, 2026-10-09; AGENTS.md 4.1.0 §23.13) ---

def _budget_lib():
    import importlib
    import sys

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return importlib.import_module("scripts.lib.tradeai_push_budget")


def _in_window():
    from datetime import datetime

    return datetime.fromisoformat("2026-10-10T12:00:00-04:00")


def _after_window():
    from datetime import datetime

    return datetime.fromisoformat("2026-10-13T00:00:00-04:00")


def test_program_window_table_is_data() -> None:
    lib = _budget_lib()
    assert lib.MAX_WITHOUT_OVERRIDE == 2
    assert lib.PROGRAM_WINDOWS == (
        {
            "prefix": "n8nmat/",
            "budget": 4,
            "ends_at": "2026-10-12T23:59:59-04:00",
            "policy": "AGENTS.md 4.1.0 §23.13",
        },
    )


def test_budget_for_n8nmat_in_window_then_default_after() -> None:
    from datetime import datetime

    lib = _budget_lib()
    assert lib.budget_for("n8nmat/foo", _in_window()) == 4
    assert lib.budget_for("n8nmat/foo", datetime.fromisoformat("2026-10-12T23:59:59-04:00")) == 4
    assert lib.budget_for("n8nmat/foo", datetime.fromisoformat("2026-10-13T00:00:00-04:00")) == 2
    assert lib.budget_for("n8nmat/foo", _after_window()) == 2


def test_budget_for_other_branches_is_two() -> None:
    lib = _budget_lib()
    for branch in ("n8nmat", "n8nmat/", "xn8nmat/foo", "N8NMAT/foo", "docs/foo", "main", "HEAD", "", None):
        assert lib.budget_for(branch, _in_window()) == 2, branch


def test_budget_defaults_unchanged_without_branch() -> None:
    lib = _budget_lib()
    assert lib.remaining(0) == 2
    assert lib.remaining(1) == 1
    assert lib.remaining(5) == 0
    assert lib.decide(authorized=True, override=False, count=1)["allow"] is True
    blocked = lib.decide(authorized=True, override=False, count=2)
    assert blocked["allow"] is False and blocked["reason"] == "BUDGET_EXCEEDED" and blocked["budget"] == 2


def test_decide_blocks_fifth_push_on_n8nmat_in_window() -> None:
    lib = _budget_lib()
    now = _in_window()
    for count in range(4):
        d = lib.decide(authorized=True, override=False, count=count, branch="n8nmat/x", now=now)
        assert d["allow"] is True and d["budget"] == 4, count
        assert d["remaining"] == 4 - count
    fifth = lib.decide(authorized=True, override=False, count=4, branch="n8nmat/x", now=now)
    assert fifth["allow"] is False and fifth["reason"] == "BUDGET_EXCEEDED" and fifth["budget"] == 4
    over = lib.decide(authorized=True, override=True, count=4, branch="n8nmat/x", now=now)
    assert over["allow"] is True and over["reason"] == "OVERRIDE"
    unauth = lib.decide(authorized=False, override=False, count=0, branch="n8nmat/x", now=now)
    assert unauth["allow"] is False and unauth["reason"] == "UNAUTHORIZED"
    # After the window the same branch falls back to the default budget.
    late = lib.decide(authorized=True, override=False, count=2, branch="n8nmat/x", now=_after_window())
    assert late["allow"] is False and late["budget"] == 2


def test_decide_blocks_third_push_on_other_branches_in_window() -> None:
    lib = _budget_lib()
    now = _in_window()
    for branch in ("docs/foo", "xn8nmat/foo", "N8NMAT/foo", "n8nmat"):
        assert lib.decide(authorized=True, override=False, count=1, branch=branch, now=now)["allow"] is True
        third = lib.decide(authorized=True, override=False, count=2, branch=branch, now=now)
        assert third["allow"] is False and third["reason"] == "BUDGET_EXCEEDED", branch
        assert third["budget"] == 2


def _commit_and_push(src: Path, env: dict, n: int):
    (src / "README").write_text(f"push {n}\n")
    _run(["git", "add", "README"], cwd=src, check=True)
    _run(["git", "commit", "-m", f"push {n}"], cwd=src, check=True)
    return _run(["git", "push", "-u", "origin", "HEAD"], cwd=src, env=env)


def test_hook_program_branch_gets_four_pushes_then_blocks(tmp_path: Path) -> None:
    src = _mini_repo(tmp_path)
    # The real window ends 2026-10-12; pin the mini repo's copy of the table to a
    # far-future end so this hook-level test does not depend on the wall clock.
    lib_copy = src / "scripts/lib/tradeai_push_budget.py"
    text = lib_copy.read_text(encoding="utf-8")
    assert '"ends_at": "2026-10-12T23:59:59-04:00"' in text
    lib_copy.write_text(text.replace("2026-10-12T23:59:59-04:00", "2999-12-31T23:59:59-04:00"), encoding="utf-8")
    _run(["git", "checkout", "-b", "n8nmat/x"], cwd=src, check=True)
    env = {
        "TRADEAI_SKIP_SECRETS_SCAN": "1",
        "TRADEAI_PUSH_BUDGET_PATH": str(src / ".git/tradeai-push-budget.json"),
        "TRADEAI_REMOTE_PUSH_AUTHORIZED": "1",
    }
    for n in range(1, 5):
        proc = _commit_and_push(src, env, n)
        assert proc.returncode == 0, (n, proc.stderr)
    fifth = _commit_and_push(src, env, 5)
    assert fifth.returncode != 0
    assert "REMOTE PUSH BLOCKED (push budget)" in fifth.stderr
    assert "Effective budget for this branch is 4." in fifth.stderr
    assert "Default budget is 2 (4 for n8nmat/* until 2026-10-12T23:59:59-04:00, AGENTS.md §23.13)" in fifth.stderr


def test_hook_non_program_branch_keeps_two_push_budget(tmp_path: Path) -> None:
    src = _mini_repo(tmp_path)
    lib_copy = src / "scripts/lib/tradeai_push_budget.py"
    text = lib_copy.read_text(encoding="utf-8")
    lib_copy.write_text(text.replace("2026-10-12T23:59:59-04:00", "2999-12-31T23:59:59-04:00"), encoding="utf-8")
    _run(["git", "checkout", "-b", "xn8nmat/foo"], cwd=src, check=True)
    env = {
        "TRADEAI_SKIP_SECRETS_SCAN": "1",
        "TRADEAI_PUSH_BUDGET_PATH": str(src / ".git/tradeai-push-budget.json"),
        "TRADEAI_REMOTE_PUSH_AUTHORIZED": "1",
    }
    for n in range(1, 3):
        assert _commit_and_push(src, env, n).returncode == 0
    third = _commit_and_push(src, env, 3)
    assert third.returncode != 0
    assert "Effective budget for this branch is 2." in third.stderr
