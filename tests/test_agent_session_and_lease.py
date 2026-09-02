"""Session receipt fail-closed + atomic lease overlap tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.agent_file_lease import LeaseCoordinator, paths_overlap
from scripts.lib.agent_session_receipt import start_session

ROOT = Path(__file__).resolve().parents[1]


def test_paths_overlap_parent_child():
    assert paths_overlap("docs/a", "docs/a/b.md")
    assert paths_overlap("docs/a/b.md", "docs/a")
    assert not paths_overlap("docs/a", "docs/b")


def test_lease_overlap_refused(tmp_path: Path):
    coord = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-test")
    a = coord.acquire(session_id="s1", agent_id="grok", paths=["docs/ops/x.md"])
    with pytest.raises(RuntimeError, match="overlap"):
        coord.acquire(session_id="s2", agent_id="codex", paths=["docs/ops/x.md"])
    with pytest.raises(RuntimeError, match="overlap"):
        coord.acquire(session_id="s3", agent_id="codex", paths=["docs/ops"])
    coord.release(a.lease_id, session_id="s1")
    b = coord.acquire(session_id="s4", agent_id="codex", paths=["docs/ops/x.md"])
    assert b.lease_id != a.lease_id


def test_disjoint_leases_ok(tmp_path: Path):
    coord = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-test")
    a = coord.acquire(session_id="s1", agent_id="grok", paths=["docs/a.md"])
    b = coord.acquire(session_id="s2", agent_id="codex", paths=["docs/b.md"])
    assert a.lease_id != b.lease_id


def test_deployment_lease_exclusive(tmp_path: Path):
    coord = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-test")
    coord.acquire(session_id="s1", agent_id="grok", paths=["docs/a.md"], deployment=True)
    with pytest.raises(RuntimeError, match="deployment"):
        coord.acquire(session_id="s2", agent_id="codex", paths=["docs/b.md"], production=True)


def test_mutating_unknown_client_fails(tmp_path: Path):
    receipt = start_session(
        agent_id="no_such_client",
        repo_root=ROOT,
        claimed_paths=["docs/implementation/maturity-program/sop-1.2.0-20260902/STAGE_00_PREFLIGHT.md"],
        docs_read=["AGENTS.md"],
        mode="mutating",
        acknowledge_dirty=True,
        expected_worktree=ROOT,
        cwd=ROOT,
        coordination_root_path=tmp_path / "coord",
    )
    assert receipt["ok"] is False
    assert any("ADVISORY_OR_UNKNOWN" in e for e in receipt["errors"])


def test_read_only_unknown_ok(tmp_path: Path):
    receipt = start_session(
        agent_id="no_such_client",
        repo_root=ROOT,
        claimed_paths=[],
        mode="read_only",
        expected_worktree=ROOT,
        cwd=ROOT,
        acknowledge_dirty=True,  # identity fail-closed on dirty before receipt write
        coordination_root_path=tmp_path / "coord",
    )
    assert receipt["ok"] is True
    assert receipt["denials"]["remote_sync"] is True


def test_new_worktree_forbids_add_all_and_default_env_link():
    src = (ROOT / "scripts" / "new-worktree.sh").read_text(encoding="utf-8")
    # Must not instruct executing add-all forms.
    assert "git add -A &&" not in src
    assert "git add -A" not in src
    assert "git add ." not in src
    assert "never use add-all" in src or "add-dot" in src
    assert "TRADEAI_WORKTREE_LINK_ENV" in src
    assert "TRADEAI_WORKTREE_LINK_ENV:-0" in src
    # Default must NOT symlink .env unless opt-in flag is set
    assert 'ln -sf "$PROJECT_ROOT/.env"' in src
    assert 'TRADEAI_WORKTREE_LINK_ENV:-0}" = "1"' in src or "${TRADEAI_WORKTREE_LINK_ENV:-0}" in src


def test_lease_ttl_expires_and_allows_reacquire(tmp_path: Path):
    coord = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-test")
    a = coord.acquire(session_id="s1", agent_id="grok", paths=["docs/a.md"], ttl_s=0.05)
    import time

    time.sleep(0.08)
    # expired lease is not active — new acquire must succeed
    b = coord.acquire(session_id="s2", agent_id="codex", paths=["docs/a.md"], ttl_s=60)
    assert b.lease_id != a.lease_id


def test_lease_heartbeat_extends_ttl(tmp_path: Path):
    coord = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-test")
    a = coord.acquire(session_id="s1", agent_id="grok", paths=["docs/a.md"], ttl_s=0.2)
    import time

    time.sleep(0.05)
    a2 = coord.heartbeat(a.lease_id, ttl_s=2.0)
    time.sleep(0.25)
    # still active due to heartbeat
    with pytest.raises(RuntimeError, match="overlap"):
        coord.acquire(session_id="s2", agent_id="codex", paths=["docs/a.md"])
    assert a2.expires_at_utc > a.expires_at_utc


def test_recover_abandoned_moves_expired(tmp_path: Path):
    coord = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-test")
    a = coord.acquire(session_id="s1", agent_id="grok", paths=["docs/a.md"], ttl_s=0.05)
    import time

    time.sleep(0.08)
    recovered = coord.recover_abandoned()
    assert any(r.get("lease_id") == a.lease_id for r in recovered)
    assert not (coord.leases_dir / f"{a.lease_id}.json").exists()
    # path free again
    b = coord.acquire(session_id="s2", agent_id="codex", paths=["docs/a.md"])
    assert b.session_id == "s2"


def test_path_traversal_rejected(tmp_path: Path):
    coord = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-test")
    with pytest.raises(ValueError):
        coord.acquire(session_id="s1", agent_id="grok", paths=["../etc/passwd"])
    with pytest.raises(ValueError):
        coord.acquire(session_id="s1", agent_id="grok", paths=["/abs/path"])


def test_mutating_requires_docs_attestation(tmp_path: Path):
    receipt = start_session(
        agent_id="grok",
        repo_root=ROOT,
        claimed_paths=["docs/implementation/maturity-program/sop-1.2.0-20260902/STAGE_00_PREFLIGHT.md"],
        docs_read=[],  # missing attestation
        mode="mutating",
        acknowledge_dirty=True,
        expected_worktree=ROOT,
        cwd=ROOT,
        coordination_root_path=tmp_path / "coord",
    )
    assert receipt["ok"] is False
    assert any("DOCUMENTATION_ATTESTATION" in e for e in receipt["errors"])


def test_mutating_with_docs_and_claims_ok(tmp_path: Path):
    """Hermetic: isolated hooked worktree — no ambient operator hooksPath required.

    CI runners have no ``core.hooksPath`` until ``install_ai_work_policy.sh`` runs.
    This test builds its own hooked repository and must not depend on the
    developer's checkout configuration.
    """
    import os
    import shutil
    import subprocess

    def _run(cmd: list[str], *, cwd: Path) -> None:
        subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True)

    main = tmp_path / "main"
    main.mkdir()
    _run(["git", "init"], cwd=main)
    _run(["git", "config", "user.email", "hermetic@example.test"], cwd=main)
    _run(["git", "config", "user.name", "Hermetic"], cwd=main)
    (main / "AI_WORK_POLICY.md").write_text("# policy\n", encoding="utf-8")
    (main / "AGENTS.md").write_text("Policy-Version: 1.2.0\nStatus: PROPOSED\n", encoding="utf-8")
    (main / "docs").mkdir()
    (main / "docs" / "INDEX.md").write_text("# idx\n", encoding="utf-8")
    hooks = main / ".githooks"
    hooks.mkdir()
    for name in ("pre-commit", "pre-push"):
        shutil.copy2(ROOT / ".githooks" / name, hooks / name)
        os.chmod(hooks / name, 0o755)
    _run(["git", "add", "AI_WORK_POLICY.md", "AGENTS.md", "docs", ".githooks"], cwd=main)
    _run(["git", "commit", "-m", "seed"], cwd=main)
    wt = tmp_path / "wt"
    _run(["git", "worktree", "add", str(wt), "HEAD"], cwd=main)
    # Canonical installer — worktree-local hooksPath (does not touch global config).
    subprocess.run(
        ["bash", str(ROOT / "scripts" / "install_ai_work_policy.sh")],
        cwd=str(wt),
        check=True,
        capture_output=True,
        text=True,
    )
    hp = subprocess.check_output(["git", "config", "--get", "core.hooksPath"], cwd=str(wt), text=True).strip()
    assert hp == ".githooks"

    receipt = start_session(
        agent_id="grok",
        repo_root=wt,
        claimed_paths=["docs/INDEX.md"],
        docs_read=["AGENTS.md", "AI_WORK_POLICY.md", "docs/INDEX.md"],
        docs_searched=["agent registry", "session receipt", "lease"],
        mode="mutating",
        acknowledge_dirty=True,
        expected_worktree=wt,
        cwd=wt,
        coordination_root_path=tmp_path / "coord",
        task_scope="sop-1.2.0-local",
    )
    assert receipt["ok"] is True, receipt.get("errors")
    assert receipt.get("lease")
    assert receipt["denials"]["remote_sync"] is True
    assert receipt["documentation_read"]
    assert receipt["hook_installation"]["core.hooksPath"] == ".githooks"
