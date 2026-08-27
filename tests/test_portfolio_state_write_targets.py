"""Portfolio writers must target the copy the live server actually reads.

Regression: the intraday repricer resolved its state dir from
`Path(__file__).parent.parent`, so it only ever wrote the checkout it lived in.
Every deployed release symlinks `data/portfolios/state` at the persistent root,
so the served holdings.json went 25h stale (17 of 23 positions priced a day old)
while the repricer logged "holdings.json updated." every 15 minutes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.lib.persistent_state_root import portfolio_state_write_targets


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    d = tmp_path / "checkout" / "data" / "portfolios" / "state"
    d.mkdir(parents=True)
    return tmp_path / "checkout"


def _persistent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, provision: bool) -> Path:
    root = tmp_path / "persistent-state"
    if provision:
        (root / "data" / "portfolios" / "state").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(root))
    return root


def test_served_copy_comes_first(checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The persistent (served) copy must be the primary read/write target."""
    persistent = _persistent(tmp_path, monkeypatch, provision=True)
    targets = portfolio_state_write_targets(checkout)

    assert targets[0] == persistent / "data" / "portfolios" / "state"
    assert targets[1] == checkout / "data" / "portfolios" / "state"
    assert len(targets) == 2


def test_checkout_only_when_persistent_root_absent(
    checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Dev boxes and CI have no persistent root — behaviour must not change."""
    _persistent(tmp_path, monkeypatch, provision=False)
    targets = portfolio_state_write_targets(checkout)

    assert targets == [checkout / "data" / "portfolios" / "state"]


def test_symlinked_checkout_is_not_written_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A release whose state dir already symlinks the persistent root is one target.

    This is exactly the deployed layout, so double-writing the same inode here
    would be the common case, not an edge case.
    """
    persistent = _persistent(tmp_path, monkeypatch, provision=True)
    served = persistent / "data" / "portfolios" / "state"

    release = tmp_path / "release"
    (release / "data" / "portfolios").mkdir(parents=True)
    (release / "data" / "portfolios" / "state").symlink_to(served)

    targets = portfolio_state_write_targets(release)

    assert len(targets) == 1
    assert targets[0].resolve() == served.resolve()


def test_repricer_resolves_through_the_helper():
    """Guard the actual regression: no bare checkout-relative state dir."""
    src = (Path(__file__).resolve().parent.parent / "scripts" / "portfolio_repricer.py").read_text()
    main = src.split('if __name__ == "__main__":', 1)[1]

    assert "portfolio_state_write_targets" in main
    assert 'state_dir = root / "data" / "portfolios" / "state"' not in main


def test_repricer_helper_import_survives_cron_invocation():
    """Run it the way cron does and assert the helper actually loaded.

    The source-text check above is not enough: it passed while the import raised
    "No module named 'scripts'" at runtime, because `python scripts/x.py` puts
    scripts/ on sys.path[0], not the repo root. The guard swallowed it and the
    repricer silently fell back to checkout-only writes -- the exact bug this
    module exists to prevent, shipped a second time.
    """
    import subprocess

    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "scripts/portfolio_repricer.py", "--print-targets"],
        cwd=root, capture_output=True, text=True, timeout=120,
    )

    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "persistent-root helper unavailable" not in proc.stdout, (
        "helper import failed at runtime; targets fell back to checkout-only:\n"
        + proc.stdout
    )
    # --print-targets is a pure probe: it must not fetch quotes or write.
    assert "[repricer] Finviz:" not in proc.stdout
    assert proc.stdout.strip(), "probe printed no targets"
