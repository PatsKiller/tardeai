"""Attestation HEAD/base resolution — CI checkout without origin/main."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.lib.sop_attestation_base import (
    AttestationBaseError,
    resolve_attestation_base_sha,
    resolve_attestation_head_sha,
)


def _run(cmd: list[str], *, cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=str(cwd), text=True).strip()


def _init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init"], cwd=path)
    _run(["git", "config", "user.email", "ci@example.test"], cwd=path)
    _run(["git", "config", "user.name", "CI"], cwd=path)
    (path / "README").write_text("a\n", encoding="utf-8")
    _run(["git", "add", "README"], cwd=path)
    _run(["git", "commit", "-m", "init"], cwd=path)
    return path


def test_explicit_base_sha_works_without_origin_main(tmp_path: Path):
    """Shallow/CI-like repo: no origin/main, but explicit base succeeds."""
    repo = _init(tmp_path / "repo")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "README").write_text("b\n", encoding="utf-8")
    _run(["git", "add", "README"], cwd=repo)
    _run(["git", "commit", "-m", "tip"], cwd=repo)
    tip = _git(repo, "rev-parse", "HEAD")
    # Ensure origin/main is absent
    rc = subprocess.run(
        ["git", "rev-parse", "--verify", "origin/main^{commit}"],
        cwd=str(repo),
        capture_output=True,
    ).returncode
    assert rc != 0

    head = resolve_attestation_head_sha(cwd=repo)
    assert head == tip.lower()
    mb = resolve_attestation_base_sha(cwd=repo, explicit=base, head_sha=head)
    assert mb == base.lower()


def test_missing_required_base_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _init(tmp_path / "repo")
    monkeypatch.delenv("SOP_ATTESTATION_BASE_SHA", raising=False)
    monkeypatch.delenv("GITHUB_BASE_SHA", raising=False)
    with pytest.raises(AttestationBaseError, match="BASE_SHA_UNAVAILABLE"):
        resolve_attestation_base_sha(cwd=repo, explicit=None)


def test_invalid_explicit_base_fails_closed(tmp_path: Path):
    repo = _init(tmp_path / "repo")
    with pytest.raises(AttestationBaseError, match="BASE_SHA_INVALID"):
        resolve_attestation_base_sha(cwd=repo, explicit="0" * 40)


def test_workflow_checks_out_pr_head_not_merge_sha():
    """agent-governance.yml must pin checkout to pull_request.head.sha."""
    text = Path(".github/workflows/agent-governance.yml").read_text(encoding="utf-8")
    assert "pull_request.head.sha" in text
    assert "fetch-depth: 0" in text
    assert "SOP_ATTESTATION_BASE_SHA" in text
    assert "emit_sop_runtime_attestation.py" in text
    assert "--base-sha" in text


def test_both_workflows_pin_ruff_0162():
    ag = Path(".github/workflows/agent-governance.yml").read_text(encoding="utf-8")
    cio = Path(".github/workflows/cio-production-hardening-ci.yml").read_text(encoding="utf-8")
    assert 'pip install "ruff==0.16.2"' in ag
    assert 'pip install "ruff==0.16.2"' in cio
    assert "PINNED_RUFF_VERSION" in ag
    assert "PINNED_RUFF_VERSION" in cio
    # Must not soft-fail the pin
    assert 'ruff==0.16.2" || true' not in ag
    assert 'ruff==0.16.2" || true' not in cio


def test_missing_ruff_still_fail_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from scripts import agent_changed_file_quality as q

    py = tmp_path / "x.py"
    py.write_text("x=1\n", encoding="utf-8")
    monkeypatch.setattr(q, "resolve_ruff_bin", lambda: None)

    def fake_run(cmd, *, env=None):  # noqa: ANN001
        if cmd and cmd[0] == "git":
            return 0
        if "check_no_secrets" in " ".join(str(c) for c in cmd):
            return 0
        return 0

    monkeypatch.setattr(q, "_run", fake_run)
    assert q.main(["--paths", str(py)]) == 2
