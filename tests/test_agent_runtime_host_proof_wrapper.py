"""Hermetic tests for the exact-ref host-proof wrapper.

Runs the real (fixed) ``host_proof_from_ref.sh`` against a throwaway git repo whose
``lab_evolve_from_ref.sh`` is a stub. Proves:
  * the wrapper executes through the LAB-evolve boundary with no ``readonly variable``;
  * exact-run cleanup rolls back and removes ONLY the exact fresh writer/reader credential
    files on every path (evolve failure, validation rejection, success);
  * symlink / out-of-directory / non-0600 / missing credential paths are handled safely
    and unrelated files are never removed;
  * no password, pgpass path, or DSN is disclosed.

No real LAB, no PostgreSQL, no network, no port 5432/5433 (the LAB socket is pointed at a
nonexistent path so the rollback psql fails closed without contacting any cluster).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "agent_runtime" / "host_proof_from_ref.sh"
STAMP = "20260101T000000Z"
_FAKE = "127.0.0.1:5433:trade_ai_agentic_lab:agentic_runtime_lab_rw:FAKEPWDDONOTUSE\n"
_REQUIRED_TESTS = (
    "test_real_roundtrip_review_score_and_completion",
    "test_real_append_only_trigger_blocks_update",
    "test_real_idempotency_conflict_and_rollback",
    "test_real_export_replay_and_tamper",
    "test_real_tool_call_lifecycle_durably_reconstructed",
    "test_real_two_connection_concurrency_no_fork",
    "test_real_kb_persistence",
)

if shutil.which("git") is None:
    pytest.skip("git unavailable", allow_module_level=True)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _init_stub_repo(repo: Path, marker: Path) -> str:
    (repo / "scripts" / "agent_runtime").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "migrations").mkdir()
    (repo / "config").mkdir()
    (repo / "migrations" / ".keep").write_text("")
    (repo / "config" / ".keep").write_text("")
    # Stub LAB evolve: record LAB_ACK, optionally write STUB_MANIFEST into the wrapper's
    # private cleanup manifest, then exit STUB_EVOLVE_RC.
    evolve = repo / "scripts" / "agent_runtime" / "lab_evolve_from_ref.sh"
    evolve.write_text(
        '#!/usr/bin/env bash\n'
        f'printf "%s" "${{LAB_ACK:-UNSET}}" > "{marker}"\n'
        'if [[ -n "${AGENTIC_CLEANUP_MANIFEST:-}" && -n "${STUB_MANIFEST:-}" ]]; then\n'
        '  printf "%s" "$STUB_MANIFEST" > "$AGENTIC_CLEANUP_MANIFEST"\n'
        'fi\n'
        'exit "${STUB_EVOLVE_RC:-0}"\n'
    )
    evolve.chmod(0o755)
    # Stub real-LAB suite: the exact required names, trivially passing, so a valid-manifest
    # run can reach a full success (gate PASS) hermetically without a real database.
    body = "".join(f"def {name}():\n    assert True\n\n\n" for name in _REQUIRED_TESTS)
    (repo / "tests" / "test_agent_runtime_real_postgres.py").write_text(body)
    # $HOST_REPO/.venv/bin/python is the wrapper's PY. Symlink the whole real venv so it
    # carries pytest (a bare bin/python symlink loses the venv's site-packages).
    (repo / ".venv").symlink_to(Path(sys.prefix))
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", "stub")
    return _git(repo, "rev-parse", "HEAD")


def _dirs(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    return evidence, secrets


def _make_run_files(evidence, secrets, *, writer_mode=0o600):
    rb = evidence / f"agentic-runtime-rollback-{STAMP}.sql"
    rb.write_text("SELECT 1;\n")
    rb.chmod(0o600)
    wr = secrets / f"agentic-runtime-lab-rw-{STAMP}.pgpass"
    wr.write_text(_FAKE)
    wr.chmod(writer_mode)
    rd = secrets / f"trade-ai-shadow-ro-{STAMP}.pgpass"
    rd.write_text(_FAKE)
    rd.chmod(0o600)
    return rb, wr, rd


def _run(tmp_path, evidence, secrets, manifest, *, evolve_rc=0):
    repo = tmp_path / "repo"
    marker = tmp_path / "ack.txt"
    sha = _init_stub_repo(repo, marker)
    env = {
        "PATH": "/usr/bin:/bin", "REPO": str(repo), "AGENTIC_SOURCE_REF": sha,
        "AGENTIC_EVIDENCE_DIR": str(evidence), "AGENTIC_SECRETS_DIR": str(secrets),
        "AGENTIC_LAB_SOCK": str(tmp_path / "nosock"),  # nonexistent -> psql fails closed
        "STUB_EVOLVE_RC": str(evolve_rc),
    }
    if manifest is not None:
        env["STUB_MANIFEST"] = manifest
    proc = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=180)
    return proc, proc.stdout + proc.stderr, marker


def _no_secret(out):
    assert "FAKEPWDDONOTUSE" not in out
    assert "readonly variable" not in out
    assert f"agentic-runtime-lab-rw-{STAMP}.pgpass" not in out  # pgpass path never printed


# --------------------------------------------------------------------------- #
def test_wrapper_passes_through_lab_evolve_and_manifest_success(tmp_path):
    evidence, secrets = _dirs(tmp_path)
    rb, wr, rd = _make_run_files(evidence, secrets)
    proc, out, marker = _run(tmp_path, evidence, secrets, f"{rb}\n{wr}\n{rd}\n")
    assert "readonly variable" not in out
    assert marker.read_text() == "DISPOSABLE_LAB_NO_PRODUCTION_DATA"
    assert "source_commit|" in out and "production_port_5432_contact|NONE" in out
    assert "final_status|PASS_AGENT_RUNTIME_PERSISTENCE_PROOF" in out  # full hermetic success
    assert not wr.exists() and not rd.exists()  # success still cleans credentials
    _no_secret(out)


def test_cleanup_on_evolve_failure_after_manifest(tmp_path):
    evidence, secrets = _dirs(tmp_path)
    rb, wr, rd = _make_run_files(evidence, secrets)
    proc, out, _ = _run(tmp_path, evidence, secrets, f"{rb}\n{wr}\n{rd}\n", evolve_rc=1)
    assert proc.returncode != 0
    assert "LAB evolve did not reach PASS_DB_PROOF" in out
    assert "rollback_or_teardown|" in out          # rollback executed on evolve failure
    assert not wr.exists() and not rd.exists()      # exact fresh credentials removed
    _no_secret(out)


def test_cleanup_on_validation_rejection_non_0600(tmp_path):
    evidence, secrets = _dirs(tmp_path)
    rb, wr, rd = _make_run_files(evidence, secrets, writer_mode=0o644)
    proc, out, _ = _run(tmp_path, evidence, secrets, f"{rb}\n{wr}\n{rd}\n")
    assert proc.returncode != 0
    assert "manifest failed validation" in out
    assert not wr.exists() and not rd.exists()      # rejection still removes exact fresh creds
    _no_secret(out)


def test_symlink_credential_never_used_or_removed(tmp_path):
    evidence, secrets = _dirs(tmp_path)
    rb, wr, rd = _make_run_files(evidence, secrets)
    wr.unlink()
    target = tmp_path / "elsewhere.pgpass"
    target.write_text(_FAKE)
    target.chmod(0o600)
    wr.symlink_to(target)
    proc, out, _ = _run(tmp_path, evidence, secrets, f"{rb}\n{wr}\n{rd}\n")
    assert proc.returncode != 0
    assert "manifest failed validation" in out
    assert wr.is_symlink()      # symlink neither executed nor removed
    assert target.exists()      # its target untouched
    _no_secret(out)


def test_out_of_directory_credential_never_removed(tmp_path):
    evidence, secrets = _dirs(tmp_path)
    rb, _, rd = _make_run_files(evidence, secrets)
    stray = tmp_path / f"agentic-runtime-lab-rw-{STAMP}.pgpass"  # correct name, wrong directory
    stray.write_text(_FAKE)
    stray.chmod(0o600)
    proc, out, _ = _run(tmp_path, evidence, secrets, f"{rb}\n{stray}\n{rd}\n")
    assert proc.returncode != 0
    assert "manifest failed validation" in out
    assert stray.exists()       # out-of-directory path never removed
    _no_secret(out)


def test_missing_manifest_rejected(tmp_path):
    evidence, secrets = _dirs(tmp_path)
    _make_run_files(evidence, secrets)
    proc, out, _ = _run(tmp_path, evidence, secrets, None)  # stub writes nothing
    assert proc.returncode != 0
    assert "manifest failed validation" in out


def test_unrelated_files_are_preserved(tmp_path):
    evidence, secrets = _dirs(tmp_path)
    rb, wr, rd = _make_run_files(evidence, secrets)
    other_cred = secrets / "agentic-runtime-lab-rw-OTHERSTAMP.pgpass"
    other_cred.write_text("x")
    other_cred.chmod(0o600)
    kept_evidence = evidence / "agentic-runtime-hostproof-pytest-KEEP.txt"
    kept_evidence.write_text("sanitized evidence")
    proc, out, _ = _run(tmp_path, evidence, secrets, f"{rb}\n{wr}\n{rd}\n")
    assert not wr.exists() and not rd.exists()   # this run's fresh creds removed
    assert other_cred.exists()                    # unrelated credential untouched
    assert kept_evidence.exists()                 # sanitized evidence preserved
    assert rb.exists()                            # the rollback evidence file itself is preserved
    _no_secret(out)
