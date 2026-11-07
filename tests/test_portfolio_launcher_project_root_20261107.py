"""ANCHOR: PORTFOLIO_LAUNCHER_PROJECT_ROOT_20261107 — a cadence ran a different tree than it was launched from.

QUALITY ROUND 2 items 2-4 (2026-11-07): the daily, weekly and monthly portfolio cadences all
graded DEGRADED because their report step exits 1. The daily step log
(``logs/pipelines/portfolio-maintenance/daily/portfolio_daily_20261106_123000.log``) ends in

    File "<dev-checkout>/scripts/portfolio_analyzer.py",
        line 72, in _get_sector
          if "ETF" in asset_type.upper():
    AttributeError: 'NoneType' object has no attribute 'upper'

That path is the **dev checkout**, but the controller launches
``portfolio-server/CURRENT/scripts/pipelines/run_portfolio_maintenance_pipeline.sh``, whose own
``PROJ`` and ``WorkingDirectory`` are the served release — and the release already carried the fix
(``c072bb634``, FU-007). The launchers it dispatches hard-coded the dev checkout, so a cadence
executed code from a tree the release train never updated: a shipped fix could not reach the lane
that needed it, and the lane's ``CURRENT`` receipt described a run of a different tree.

These tests pin the property at the launcher, behaviourally: a launcher copied into a throwaway
release tree runs *its own* tree, writes its log there, and still honours a ``PROJECT_ROOT``
override. Hermetic: the copied launchers are run against stub ``python``/``python3`` executables;
no orchestrator, no report, no network, no Telegram, no DB.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHERS = ("run_portfolio.sh", "run_portfolio_weekly.sh", "run_portfolio_monthly.sh")
ABSOLUTE_DEFAULT = re.compile(r'^PROJECT_ROOT="/(?!/)', re.M)   # a literal filesystem default


def _stub_python(path: Path) -> None:
    path.write_text(
        "#!/bin/bash\n"
        'echo "$PWD :: $*" >> "$RECORD"\n'
        "exit 0\n"
    )
    path.chmod(0o755)


def _default_expr(name: str) -> str:
    """The launcher's PROJECT_ROOT default, as written."""
    source = (ROOT / "linux_launchers" / name).read_text()
    match = re.search(r'^PROJECT_ROOT="\$\{PROJECT_ROOT:-([^}]*)\}"', source, re.M)
    return match.group(1) if match else ""


def _is_self_resolving(name: str) -> bool:
    """True only when the default follows the launcher's own tree.

    The behavioural tests EXECUTE the launcher. While a default is absolute, executing it runs the
    real checkout — and, on this host, the real portfolio pipeline against live state. That is not
    something a test may do to prove a bug exists, so when the default is absolute the behavioural
    tests skip and the static assertions below are the ones that fail (they are what caught the
    defect). This test file must never be able to reach a real tree.
    """
    expr = _default_expr(name)
    return "BASH_SOURCE" in expr and "/home/" not in expr


def _release_tree(tmp_path: Path) -> tuple[Path, Path]:
    """A release-shaped tree holding a copy of the real launchers and stub interpreters."""
    release = tmp_path / "release"
    (release / "linux_launchers").mkdir(parents=True)
    (release / ".venv" / "bin").mkdir(parents=True)
    (release / "logs").mkdir()
    (release / "scripts").mkdir()

    stub = tmp_path / "stubbin"
    stub.mkdir()
    _stub_python(stub / "python")
    _stub_python(stub / "python3")
    # A `tee` that actually drains its stdin (an immediate-exit stub SIGPIPEs the launcher).
    (stub / "tee").write_text('#!/bin/bash\ncat > "$1"\n')
    (stub / "tee").chmod(0o755)

    (release / ".venv" / "bin" / "activate").write_text(f'export PATH="{stub}:{os.environ["PATH"]}"\n')
    for name in LAUNCHERS:
        shutil.copy(ROOT / "linux_launchers" / name, release / "linux_launchers" / name)
    return release, tmp_path / "calls.txt"


def _run(launcher: Path, *, record: Path, project_root: str | None = None,
         home: Path) -> subprocess.CompletedProcess:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "RECORD": str(record),
        "TMPDIR": str(home),
    }
    if project_root is not None:
        env["PROJECT_ROOT"] = project_root
    home.mkdir(exist_ok=True)
    return subprocess.run(["bash", str(launcher)], capture_output=True, text=True,
                          env=env, timeout=120, cwd=str(launcher.parent))


# ── the launcher runs its own tree ──────────────────────────────────────────


@pytest.mark.parametrize("name", LAUNCHERS)
def test_a_launcher_runs_the_tree_it_ships_in(name, tmp_path):
    if not _is_self_resolving(name):
        pytest.skip(f"{name} still has an absolute default; the static tests below report it")
    release, record = _release_tree(tmp_path)
    launcher = release / "linux_launchers" / name

    result = _run(launcher, record=record, home=tmp_path / "home")
    assert result.returncode == 0, result.stderr

    calls = [line.split(" :: ")[0] for line in record.read_text().splitlines() if line.strip()]
    assert calls, "the launcher never executed its python steps"
    assert set(calls) == {str(release)}, f"{name} ran outside its own tree: {sorted(set(calls))}"


@pytest.mark.parametrize("name", LAUNCHERS)
def test_the_run_log_lands_in_the_launching_tree(name, tmp_path):
    if not _is_self_resolving(name):
        pytest.skip(f"{name} still has an absolute default; the static tests below report it")
    release, record = _release_tree(tmp_path)
    _run(release / "linux_launchers" / name, record=record, home=tmp_path / "home")
    assert list((release / "logs").glob("run_portfolio*")), "no log written into the release tree"


@pytest.mark.parametrize("name", LAUNCHERS)
def test_an_explicit_project_root_still_wins(name, tmp_path):
    """The override is what tests and drills use; the fix must not remove it."""
    if not _is_self_resolving(name):
        pytest.skip(f"{name} still has an absolute default; the static tests below report it")
    release, record = _release_tree(tmp_path)
    other = tmp_path / "other-tree"
    (other / "logs").mkdir(parents=True)
    (other / ".venv" / "bin").mkdir(parents=True)
    (other / ".venv" / "bin" / "activate").write_text(
        f'export PATH="{tmp_path / "stubbin"}:{os.environ["PATH"]}"\n')

    result = _run(release / "linux_launchers" / name, record=record,
                  project_root=str(other), home=tmp_path / "home")
    assert result.returncode == 0, result.stderr
    calls = [line.split(" :: ")[0] for line in record.read_text().splitlines() if line.strip()]
    assert set(calls) == {str(other)}


# ── the defect cannot come back silently ────────────────────────────────────


@pytest.mark.parametrize("name", LAUNCHERS)
def test_no_launcher_hard_codes_a_checkout(name):
    """A literal path default is the defect: it pins the cadence to a tree the release never updates."""
    source = (ROOT / "linux_launchers" / name).read_text()
    default = re.search(r'^PROJECT_ROOT="\$\{PROJECT_ROOT:-([^}]*)\}"', source, re.M)
    assert default, f"{name}: PROJECT_ROOT is not an overridable default"
    assert not default.group(1).startswith("/"), \
        f"{name}: absolute default {default.group(1)!r}"
    assert "BASH_SOURCE" in default.group(1), f"{name}: default does not follow the launcher's tree"


def test_no_launcher_assigns_an_absolute_project_root():
    hits = [n for n in LAUNCHERS
            if ABSOLUTE_DEFAULT.search((ROOT / "linux_launchers" / n).read_text())]
    assert hits == [], f"a launcher still pins a literal checkout: {hits}"
