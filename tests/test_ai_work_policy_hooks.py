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
    return subprocess.run(
        cmd, cwd=cwd, env=merged, capture_output=True, text=True, check=check
    )


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
    """The rule is 'do not restate the policy'. Length was only ever a proxy.

    The proxy broke on 2026-08-30: CLAUDE.md grew into the operating-technique
    file the policy assumes, hit the length cap at 11,999 bytes against 2,679,
    and blocked every push — while duplicating nothing. Measured at the time,
    zero of its 58 blocks were >75% similar to any of the policy's 70, and the
    longest verbatim run between the two files was 19 characters: the string
    "AI_WORK_POLICY.md" itself, i.e. the pointer the test wants to see.

    So assert the property, not the proxy. This is strictly stronger: nothing
    previously checked duplication at all, so a 2,600-byte adapter that was
    pure copy-paste passed. The compactness cap is kept for the two adapters
    that are still thin pointers by design.
    """
    policy = POLICY.read_text(encoding="utf-8")
    policy_len = len(policy)
    adapters = {
        "AGENTS.md": ROOT / "AGENTS.md",
        "CLAUDE.md": ROOT / "CLAUDE.md",
        "copilot": ROOT / ".github/copilot-instructions.md",
        "cursor": ROOT / ".cursor/rules/00-tradeai-work-policy.mdc",
    }
    # These two carry their own material by design: AGENTS.md the runtime
    # reference, CLAUDE.md the operating technique the policy assumes.
    CARRIES_OWN_MATERIAL = {"AGENTS.md", "CLAUDE.md"}
    for name, path in adapters.items():
        blob = path.read_text(encoding="utf-8")
        assert "AI_WORK_POLICY.md" in blob, name
        assert "git commit" in blob, name
        # The actual rule, applied to every adapter including the long ones.
        run = _longest_shared_run(policy, blob)
        assert run < 400, (
            f"{name} restates {run} verbatim characters of AI_WORK_POLICY.md; "
            "adapters point at the policy, they do not copy it")
        if name not in CARRIES_OWN_MATERIAL:
            assert len(blob) < policy_len / 5, name


def test_pre_push_blocks_without_authorization() -> None:
    env = os.environ.copy()
    env.pop("TRADEAI_REMOTE_PUSH_AUTHORIZED", None)
    env["TRADEAI_SKIP_SECRETS_SCAN"] = "1"
    proc = _run(["bash", str(PRE_PUSH)], cwd=ROOT, env=env)
    assert proc.returncode == 1
    assert "REMOTE PUSH BLOCKED" in proc.stderr


def test_pre_push_rejects_zero_flag() -> None:
    env = os.environ.copy()
    env["TRADEAI_REMOTE_PUSH_AUTHORIZED"] = "0"
    env["TRADEAI_SKIP_SECRETS_SCAN"] = "1"
    proc = _run(["bash", str(PRE_PUSH)], cwd=ROOT, env=env)
    assert proc.returncode == 1


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
