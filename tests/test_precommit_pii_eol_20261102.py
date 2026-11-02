"""The pre-commit gate that catches PII and line-ending churn before CI does.

2026-11-01: PR #2465's first CI run failed on integrity rails after CRLF→LF churn, and the same PR
merged with `secret-scan` red. Both defects were visible in the staged diff before any push. This
gate makes the local commit the place they are caught.

The hook itself (`.githooks/pre-commit`) is a held path; the tested unit is
`scripts/precommit_pii_eol.sh`, which the hook calls.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "precommit_pii_eol.sh"
PY = sys.executable


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False,
    )  # fmt: skip


def _temp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    # Copy (not link) the checkers: each resolves the repo from its own file location, so a
    # symlink would make it scan the real checkout instead of the fixture.
    (repo / "scripts").mkdir()
    for name in ("check_no_pii.py", "check_line_endings.py"):
        (repo / "scripts" / name).write_bytes((ROOT / "scripts" / name).read_bytes())
    assert _git(repo, "init", "-q", "-b", "main").returncode == 0
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "config", "user.name", "dev")
    # The checks compare the index against HEAD, which needs to exist.
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    assert _git(repo, "add", "README.md").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "base").returncode == 0
    return repo


def _stage(repo: Path, name: str, body: bytes) -> None:
    (repo / name).write_bytes(body)
    assert _git(repo, "add", name).returncode == 0


def _run_gate(repo: Path) -> tuple[int, str]:
    # An explicit empty deny file keeps the run hermetic: the checker fails closed on a missing one
    # and refuses a deny file inside the repository, and the operator's real one must never leak in.
    deny = repo.parent / "deny.txt"
    deny.write_text("", encoding="utf-8")
    env = {**os.environ, "TRADEAI_PII_DENY_FILE": str(deny)}
    proc = subprocess.run(["bash", str(SCRIPT)], cwd=repo, capture_output=True, text=True, env=env, check=False)
    return proc.returncode, proc.stdout + proc.stderr


def _synthetic_address() -> str:
    """Assembled at runtime on purpose.

    A literal address in this file is itself a PII finding — `check_no_pii` scans the added lines of
    this very PR, and no inline marker silences one. The domain is deliberately not an .example one:
    the value has to trip the rule for the test to mean anything.
    """
    return "someone" + "@" + "acme-corp" + ".com"


def test_gate_refuses_pii_on_a_staged_added_line(tmp_path):
    repo = _temp_repo(tmp_path)
    _stage(repo, "notes.md", f"contact: {_synthetic_address()}\n".encode())
    rc, out = _run_gate(repo)
    assert rc != 0
    assert "personal or identifying data" in out
    assert "fix:" in out


def test_gate_allows_a_clean_staged_change(tmp_path):
    repo = _temp_repo(tmp_path)
    _stage(repo, "notes.md", b"contact: dev@example.com\n")
    rc, out = _run_gate(repo)
    assert rc == 0, out


def test_gate_refuses_line_ending_churn(tmp_path):
    repo = _temp_repo(tmp_path)
    lines = [f"line {i}" for i in range(60)]
    _stage(repo, "table.py", ("\n".join(lines) + "\n").encode())
    assert _git(repo, "commit", "-q", "-m", "base").returncode == 0
    # Rewrite the same content with CRLF endings and stage it: no real change, all churn.
    (repo / "table.py").write_bytes(("\r\n".join(lines) + "\r\n").encode())
    assert _git(repo, "add", "table.py").returncode == 0
    rc, out = _run_gate(repo)
    assert rc != 0
    assert "line-ending churn" in out
    assert "fix:" in out


def test_gate_is_fast_on_a_typical_commit(tmp_path):
    repo = _temp_repo(tmp_path)
    _stage(repo, "notes.md", b"a small ordinary change\n")
    started = time.monotonic()
    rc, out = _run_gate(repo)
    elapsed = time.monotonic() - started
    assert rc == 0, out
    # The plan's bar is 3 s; keep headroom for a loaded machine but catch a pathological scan.
    assert elapsed < 5.0, f"gate took {elapsed:.2f}s"
