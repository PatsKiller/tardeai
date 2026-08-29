"""The reprice launcher must target the SERVED tree, not the source checkout.

Until 2026-08-29 `run_reprice_only.sh` did `cd $PROJECT_ROOT` and
`root = Path('.').resolve()`, so both code and data came from the v12-rebuild
checkout — which portfolio_server does not read. Two defects fell out of that
one line:

  * the served holdings.json (a symlink into persistent-state) was never
    repriced by the scheduled job; the two trees had drifted ~$1,597 in
    total_value
  * $PROJECT_ROOT/scripts/portfolio_repricer.py predates #641, so the Fidelity
    rollover was classified ACCOUNT_RECONCILIATION_RESIDUAL rather than
    CLOSED_ROLLED_TO

Both are invisible at runtime: the job exits 0 either way.
"""
import re
from pathlib import Path

import pytest

LAUNCHER = (Path(__file__).resolve().parent.parent
            / "linux_launchers" / "run_reprice_only.sh")


@pytest.fixture(scope="module")
def body():
    return LAUNCHER.read_text(encoding="utf-8", errors="replace")


def test_data_root_defaults_to_the_served_tree(body):
    m = re.search(r'DATA_ROOT="\$\{DATA_ROOT:-([^}]+)\}"', body)
    assert m, "DATA_ROOT with a default is required"
    assert "portfolio-server/CURRENT" in m.group(1), m.group(1)


def test_the_python_block_roots_at_data_root_not_cwd(body):
    """`Path('.')` resolves to PROJECT_ROOT — the original bug."""
    assert "root = Path(sys.argv[1]).resolve()" in body
    assert "root = Path('.').resolve()" not in body


def test_it_refuses_a_data_root_that_is_not_a_served_tree(body):
    """Fail loudly beats repricing the wrong tree and exiting 0."""
    assert '$DATA_ROOT/scripts' in body
    assert '$DATA_ROOT/data/portfolios/state' in body
    assert "exit 1" in body


def test_the_env_is_exported_before_the_repricer_runs(body):
    """Without .env the repricer prices 0/31 symbols and still reports success."""
    assert re.search(r'set -a; \. "\$PROJECT_ROOT/\.env"; set \+a', body)
    assert 'export TRADEAI_ROOT="$DATA_ROOT"' in body


def test_the_html_destination_stays_in_project_root(body):
    """A release dir is overlaid on promote; a report written there is lost."""
    assert "dst = project_root / 'reports' / 'portfolio_live.html'" in body
