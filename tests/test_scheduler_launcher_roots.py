"""CURRENT units must not jump to dev code in their governance child launchers.

Execute the actual launcher prelude in an isolated release tree; stop before env
loading, locks and reports. No production scheduler, credential or lane is invoked.
"""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "name", ["run_scheduled_system_facts.sh", "run_scheduled_a1a_check.sh", "run_scheduled_maturity_control_board.sh"]
)
def test_governance_child_uses_its_release_not_dev_tree_or_cwd(tmp_path, name):
    release = tmp_path / "release"
    launcher = release / "scripts" / name
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes((ROOT / "scripts" / name).read_bytes())
    # The boundary precedes secret loading and every process side effect.
    prelude = launcher.read_text().split("set -a;", 1)[0]
    launcher.write_text(prelude + 'printf "%s" "$PROJ"\n')
    elsewhere = tmp_path / "unrelated-cwd"
    elsewhere.mkdir()
    run = subprocess.run(["bash", str(launcher)], cwd=elsewhere, capture_output=True, text=True, check=True)
    assert run.stdout == str(release)


PORTFOLIO_CHILDREN = [
    "run_pg_backup.sh",
    "run_portfolio.sh",
    "run_portfolio_weekly.sh",
    "run_portfolio_monthly.sh",
    "run_lookthrough.sh",
    "run_price_cache.sh",
]


def _root_prelude(source):
    # Truncate the actual launcher before env/credential loading, locks, writes,
    # model calls, backups or notifications. Only root resolution is executed.
    lines = source.splitlines(keepends=True)
    stop = next(i for i, line in enumerate(lines) if line.startswith("PROJECT_ROOT="))
    return "".join(lines[: stop + 1])


@pytest.mark.parametrize("name", PORTFOLIO_CHILDREN)
@pytest.mark.parametrize("through_current", [False, True])
def test_portfolio_child_keeps_controller_release_root(tmp_path, name, through_current):
    release = tmp_path / "versioned-release"
    child = release / "linux_launchers" / name
    child.parent.mkdir(parents=True)
    child.write_text(_root_prelude((ROOT / "linux_launchers" / name).read_text()) + 'printf "%s" "$PROJECT_ROOT"\n')
    current = tmp_path / "CURRENT"
    current.symlink_to(release, target_is_directory=True)
    root = current if through_current else release
    controller = release / "scripts/pipelines/run_portfolio_maintenance_pipeline.sh"
    controller.parent.mkdir(parents=True)
    src = (ROOT / "scripts/pipelines/run_portfolio_maintenance_pipeline.sh").read_text()
    prelude = src.split("# shellcheck source=/dev/null", 1)[0]
    controller.write_text(prelude + f'bash "$PROJ/linux_launchers/{name}"\n')
    elsewhere = tmp_path / "unrelated-cwd"
    elsewhere.mkdir()
    run = subprocess.run(
        ["bash", str(root / controller.relative_to(release))],
        cwd=elsewhere,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "empty-home")},
        capture_output=True,
        text=True,
        check=True,
    )
    assert Path(run.stdout).resolve() == release


@pytest.mark.parametrize("name", ["run_portfolio_weekly.sh", "run_portfolio_monthly.sh", "run_lookthrough.sh"])
def test_portfolio_child_preserves_explicit_root_override(tmp_path, name):
    child = tmp_path / "release/linux_launchers" / name
    child.parent.mkdir(parents=True)
    child.write_text(_root_prelude((ROOT / "linux_launchers" / name).read_text()) + 'printf "%s" "$PROJECT_ROOT"\n')
    explicit = tmp_path / "explicit-fixture-root"
    explicit.mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "empty-home")}
    args = ["bash", str(child)]
    if name == "run_lookthrough.sh":
        args.append(str(explicit))
    else:
        env["PROJECT_ROOT"] = str(explicit)
    run = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True, check=True)
    assert Path(run.stdout).resolve() == explicit


@pytest.mark.parametrize("name", PORTFOLIO_CHILDREN)
@pytest.mark.parametrize("local_venv", [False, True])
def test_portfolio_child_selects_runtime_without_using_dev_code(tmp_path, name, local_venv):
    release = tmp_path / "release"
    shared = tmp_path / "shared-runtime"
    chosen = release / ".venv" if local_venv else shared
    (chosen / "bin").mkdir(parents=True)
    (chosen / "bin/activate").write_text(f'export FIXTURE_RUNTIME="{chosen}"\nexport PATH="{chosen}/bin:$PATH"\n')
    for binary in ["python", "python3"]:
        probe = chosen / "bin" / binary
        probe.write_text('#!/bin/bash\nprintf "%s\\n" "$PWD" "$0"\n')
        probe.chmod(0o755)
    child = release / "linux_launchers" / name
    child.parent.mkdir(parents=True)
    src = (ROOT / "linux_launchers" / name).read_text()
    if name == "run_pg_backup.sh":
        # Execute only root + interpreter selection, before env/credential reads,
        # lock, pg_dump, backup pruning or receipt writes.
        if "# Shared interpreter" in src:
            selection = src[src.index("# Shared interpreter") : src.index("ENFORCER=")]
        else:
            selection = next(line for line in src.splitlines() if line.startswith("PY=")) + "\n"
        prelude = _root_prelude(src) + selection + 'cd "$PROJECT_ROOT"\n"$PY" fixture_probe.py\n'
    else:
        # Preserve the actual activation statement, before any report or model work.
        if 'if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]' in src:
            selection = src[src.index('if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]') :]
            selection = selection[: selection.index("\nfi") + len("\nfi")]
        else:
            assert "source .venv/bin/activate" in src
            selection = "source .venv/bin/activate"
        prelude = _root_prelude(src) + 'cd "$PROJECT_ROOT"\n' + selection + "\npython3 fixture_probe.py\n"
    child.write_text(prelude)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "empty-home"), "TRADEAI_VENV": str(shared)}
    run = subprocess.run(["bash", str(child)], cwd=tmp_path, env=env, capture_output=True, text=True, check=True)
    lines = run.stdout.splitlines()
    assert Path(lines[0]).resolve() == release
    assert Path(lines[1]).resolve().parent.parent == chosen
