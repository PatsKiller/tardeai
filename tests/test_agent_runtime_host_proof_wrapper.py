"""Hermetic test for the exact-ref host-proof wrapper's LAB-evolve invocation boundary.

Runs the real (fixed) ``host_proof_from_ref.sh`` against a throwaway git repo whose
``lab_evolve_from_ref.sh`` is a stub that records the ``LAB_ACK`` it received. This
proves the wrapper executes *through* the LAB-evolve invocation with no
``readonly variable`` failure (the regression it fixes), without evolving a real LAB,
touching PostgreSQL, or running the real proof. No network, no port 5432, no 5433.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "agent_runtime" / "host_proof_from_ref.sh"

if shutil.which("git") is None:
    pytest.skip("git unavailable", allow_module_level=True)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _init_stub_repo(repo: Path, marker: Path) -> str:
    """A minimal repo staged by the wrapper: stub evolve child + the four archived dirs."""
    (repo / "scripts" / "agent_runtime").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "migrations").mkdir()
    (repo / "config").mkdir()
    (repo / "migrations" / ".keep").write_text("")
    (repo / "config" / ".keep").write_text("")
    # Stub LAB evolve: record the LAB_ACK it was handed, then succeed. If the wrapper
    # tried to assign a readonly LAB_ACK it would abort BEFORE reaching this child.
    evolve = repo / "scripts" / "agent_runtime" / "lab_evolve_from_ref.sh"
    evolve.write_text(f'#!/usr/bin/env bash\nprintf "%s" "${{LAB_ACK:-UNSET}}" > "{marker}"\nexit 0\n')
    evolve.chmod(0o755)
    (repo / "tests" / "test_agent_runtime_real_postgres.py").write_text("def test_stub():\n    assert True\n")
    # a .venv/bin/python the wrapper will use as PY
    venvbin = repo / ".venv" / "bin"
    venvbin.mkdir(parents=True)
    (venvbin / "python").symlink_to(sys.executable)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", "stub")
    return _git(repo, "rev-parse", "HEAD")


def test_wrapper_passes_through_lab_evolve_without_readonly_failure(tmp_path):
    repo = tmp_path / "repo"
    marker = tmp_path / "lab_ack_seen.txt"
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    sha = _init_stub_repo(repo, marker)

    proc = subprocess.run(
        ["bash", str(WRAPPER)],
        env={
            "PATH": "/usr/bin:/bin",
            "REPO": str(repo),
            "AGENTIC_SOURCE_REF": sha,
            "AGENTIC_EVIDENCE_DIR": str(evidence),
        },
        capture_output=True, text=True, timeout=120,
    )
    combined = proc.stdout + proc.stderr

    # 1) the regression must be gone
    assert "readonly variable" not in combined, combined
    # 2) the wrapper executed THROUGH the LAB-evolve invocation boundary — the stub child
    #    ran and received the correct LAB_ACK via the command-prefix env assignment.
    assert marker.exists(), f"stub evolve child did not run; output:\n{combined}"
    assert marker.read_text() == "DISPOSABLE_LAB_NO_PRODUCTION_DATA", marker.read_text()
    # 3) it got at least as far as the source markers printed just before evolve
    assert f"source_commit|{sha}" in combined
    assert "production_port_5432_contact|NONE" in combined
