"""Changed-file quality gate: Ruff required when Python changes exist."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import agent_changed_file_quality as q


@pytest.fixture
def isolate_git_secrets(monkeypatch: pytest.MonkeyPatch):
    """Keep unit tests focused on the Ruff gate (not git/secrets side effects)."""
    real_run = q._run

    def filtered(cmd: list[str], *, env=None):  # noqa: ANN001
        joined = " ".join(str(c) for c in cmd)
        if "diff" in cmd and cmd[0] == "git":
            return 0
        if "check_no_secrets.py" in joined:
            return 0
        return real_run(cmd, env=env)

    monkeypatch.setattr(q, "_run", filtered)


def test_missing_ruff_with_python_changes_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolate_git_secrets):
    py = tmp_path / "sample.py"
    py.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(q, "resolve_ruff_bin", lambda: None)
    rc = q.main(["--paths", str(py)])
    assert rc == 2


def test_format_drift_fails(tmp_path: Path, isolate_git_secrets):
    ruff = q.resolve_ruff_bin()
    if ruff is None:
        pytest.skip("ruff unavailable in this environment")
    py = tmp_path / "ugly.py"
    py.write_text(
        "def f(a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r,s,t): return a+b+c+d+e+f+g+h+i+j+k+l+m+n+o+p+q+r+s+t\n",
        encoding="utf-8",
    )
    rc = q.main(["--paths", str(py), "--ruff-bin", str(ruff)])
    assert rc == 1


def test_clean_python_passes_ruff_gates(tmp_path: Path, isolate_git_secrets):
    ruff = q.resolve_ruff_bin()
    if ruff is None:
        pytest.skip("ruff unavailable in this environment")
    py = tmp_path / "clean.py"
    py.write_text('"""doc."""\n\nx = 1\n', encoding="utf-8")
    subprocess.check_call([str(ruff), "format", str(py)])
    rc = q.main(["--paths", str(py), "--ruff-bin", str(ruff)])
    assert rc == 0
