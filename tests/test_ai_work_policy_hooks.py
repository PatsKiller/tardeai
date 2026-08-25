"""AI work-policy hook: unauthorized push is blocked; policy file is canonical."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRE_PUSH = ROOT / ".githooks" / "pre-push"
POLICY = ROOT / "AI_WORK_POLICY.md"


def test_policy_file_exists_and_is_mandatory() -> None:
    text = POLICY.read_text(encoding="utf-8")
    assert "Status: MANDATORY" in text
    assert "git push" in text
    assert "TRADEAI_REMOTE_PUSH_AUTHORIZED" in text
    assert "MEMORY_BEHAVIOR_INFLUENCE=0" in text


def test_adapters_point_at_canonical_policy() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    copilot = (ROOT / ".github/copilot-instructions.md").read_text(encoding="utf-8")
    cursor = (ROOT / ".cursor/rules/00-tradeai-work-policy.mdc").read_text(encoding="utf-8")
    for blob in (agents, claude, copilot, cursor):
        assert "AI_WORK_POLICY.md" in blob
        assert "git commit" in blob


def test_pre_push_blocks_without_authorization() -> None:
    assert PRE_PUSH.is_file()
    env = os.environ.copy()
    env.pop("TRADEAI_REMOTE_PUSH_AUTHORIZED", None)
    proc = subprocess.run(
        ["bash", str(PRE_PUSH)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "REMOTE PUSH BLOCKED" in proc.stderr


def test_pre_push_rejects_zero_flag() -> None:
    env = os.environ.copy()
    env["TRADEAI_REMOTE_PUSH_AUTHORIZED"] = "0"
    proc = subprocess.run(
        ["bash", str(PRE_PUSH)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1


def test_install_script_is_executable_source() -> None:
    script = ROOT / "scripts/install_ai_work_policy.sh"
    text = script.read_text(encoding="utf-8")
    assert "core.hooksPath" in text
    assert "TRADEAI_REMOTE_PUSH_AUTHORIZED" in (ROOT / ".githooks/pre-push").read_text(encoding="utf-8")
    assert "check_no_secrets.py" in (ROOT / ".githooks/pre-commit").read_text(encoding="utf-8")
