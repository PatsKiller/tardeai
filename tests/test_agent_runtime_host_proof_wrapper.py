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
    # Stub LAB evolve: record the LAB_ACK it was handed, optionally write STUB_HANDOFF_TARGET
    # into the wrapper's private credential handoff, then succeed. If the wrapper tried to
    # assign a readonly LAB_ACK it would abort BEFORE reaching this child.
    evolve = repo / "scripts" / "agent_runtime" / "lab_evolve_from_ref.sh"
    evolve.write_text(
        '#!/usr/bin/env bash\n'
        f'printf "%s" "${{LAB_ACK:-UNSET}}" > "{marker}"\n'
        'if [[ -n "${AGENTIC_PGPASS_HANDOFF:-}" && -n "${STUB_HANDOFF_TARGET:-}" ]]; then\n'
        '  printf "%s\\n" "$STUB_HANDOFF_TARGET" > "$AGENTIC_PGPASS_HANDOFF"\n'
        'fi\n'
        'exit 0\n'
    )
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


# ---- credential handoff validation (hermetic; no real LAB / PostgreSQL) ---------------
_FAKE = "127.0.0.1:5433:trade_ai_agentic_lab:agentic_runtime_lab_rw:FAKEPWDDONOTUSE\n"


def _run(tmp_path, handoff_target):
    repo = tmp_path / "repo"
    marker = tmp_path / "ack.txt"
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    secrets = tmp_path / "secrets"
    if not secrets.exists():
        secrets.mkdir(mode=0o700)
    sha = _init_stub_repo(repo, marker)
    env = {
        "PATH": "/usr/bin:/bin", "REPO": str(repo), "AGENTIC_SOURCE_REF": sha,
        "AGENTIC_EVIDENCE_DIR": str(evidence), "AGENTIC_SECRETS_DIR": str(secrets),
    }
    if handoff_target is not None:
        env["STUB_HANDOFF_TARGET"] = str(handoff_target)
    proc = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=120)
    return proc, proc.stdout + proc.stderr


def _mk(path: Path, mode=0o600, content=_FAKE) -> Path:
    path.write_text(content)
    path.chmod(mode)
    return path


_REJECTIONS = ("outside the LAB secrets directory", "is a symlink", "not mode 0600",
               "no writer credential handoff", "not a regular file", "malformed", "does not exist")


def test_credential_handoff_accepted_and_files_cleaned_up(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    writer = _mk(secrets / "agentic-runtime-lab-rw-TS.pgpass")
    reader = _mk(secrets / "trade-ai-shadow-ro-TS.pgpass")
    proc, out = _run(tmp_path, writer)
    for bad in _REJECTIONS:
        assert bad not in out, out            # credential was ACCEPTED
    assert "FAKEPWDDONOTUSE" not in out        # no secret disclosure
    assert "readonly variable" not in out
    assert not writer.exists() and not reader.exists()  # exact fresh files deleted at teardown


def test_credential_handoff_rejects_out_of_directory(tmp_path):
    (tmp_path / "secrets").mkdir(mode=0o700)
    stray = _mk(tmp_path / "stray-agentic-runtime-lab-rw.pgpass")  # not under the secrets dir
    proc, out = _run(tmp_path, stray)
    assert proc.returncode != 0
    assert "outside the LAB secrets directory" in out
    assert "FAKEPWDDONOTUSE" not in out


def test_credential_handoff_rejects_symlink(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    real = _mk(secrets / "agentic-runtime-lab-rw-real.pgpass")
    link = secrets / "agentic-runtime-lab-rw-link.pgpass"
    link.symlink_to(real)
    proc, out = _run(tmp_path, link)
    assert proc.returncode != 0
    assert "is a symlink" in out
    assert "FAKEPWDDONOTUSE" not in out


def test_credential_handoff_rejects_non_0600(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    loose = _mk(secrets / "agentic-runtime-lab-rw-loose.pgpass", mode=0o644)
    proc, out = _run(tmp_path, loose)
    assert proc.returncode != 0
    assert "not mode 0600" in out


def test_credential_handoff_rejects_missing(tmp_path):
    (tmp_path / "secrets").mkdir(mode=0o700)
    proc, out = _run(tmp_path, None)  # stub writes nothing to the handoff
    assert proc.returncode != 0
    assert "no writer credential handoff" in out
