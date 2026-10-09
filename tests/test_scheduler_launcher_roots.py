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
