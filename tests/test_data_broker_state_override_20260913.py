"""The data_broker snapshot path must be redirectable without module patching.

CL-64-remainder. The p26 suite left state/data_broker/portfolio_snapshot.json
inside the repository. On a fresh CI clone that CREATES the tree, and
test_whole_site_truth then correctly reports a state root that exists only
because a test put it there.

Containing it by monkeypatching the module constant does not work and must not
be attempted: the package is importable as both `lib.data_broker.x` and
`scripts.lib.data_broker.x`, which are distinct module objects with distinct
copies of every constant. Patching one is a silent no-op against the other, and
patching both trips test_scripts_lib_bootstrap, which enforces a single spelling.

So the path is resolved per call from an environment variable, which is
process-global and has no module identity at all.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.data_broker import portfolio_snapshot as ps


def test_default_is_unchanged_when_unset(monkeypatch):
    monkeypatch.delenv(ps.STATE_DIR_ENV, raising=False)
    assert ps._snapshot_dir() == ps.SNAPSHOT_DIR
    assert ps._snapshot_path() == ps.SNAPSHOT_PATH


def test_env_redirects_the_path(monkeypatch, tmp_path):
    monkeypatch.setenv(ps.STATE_DIR_ENV, str(tmp_path))
    assert ps._snapshot_dir() == tmp_path
    assert ps._snapshot_path() == tmp_path / "portfolio_snapshot.json"


def test_blank_env_falls_back_to_the_default(monkeypatch):
    """An empty or whitespace value is not a path; it must not redirect to ''."""
    for blank in ("", "   "):
        monkeypatch.setenv(ps.STATE_DIR_ENV, blank)
        assert ps._snapshot_dir() == ps.SNAPSHOT_DIR


def test_resolution_is_per_call_not_per_import(monkeypatch, tmp_path):
    """The defect was a path frozen at import. Changing the env mid-process
    must move the writer."""
    monkeypatch.setenv(ps.STATE_DIR_ENV, str(tmp_path / "a"))
    first = ps._snapshot_path()
    monkeypatch.setenv(ps.STATE_DIR_ENV, str(tmp_path / "b"))
    assert ps._snapshot_path() != first


def test_write_goes_to_the_redirected_path(monkeypatch, tmp_path):
    """NEGATIVE CONTROL: before the fix this landed in the repo tree."""
    monkeypatch.setenv(ps.STATE_DIR_ENV, str(tmp_path))
    written = Path(ps.write_portfolio_snapshot({"schema": "test", "items": []}))
    assert written.parent == tmp_path
    assert written.exists()
    assert ps.SNAPSHOT_DIR not in written.parents, "must not touch the repo tree"


def test_read_follows_the_same_redirect(monkeypatch, tmp_path):
    monkeypatch.setenv(ps.STATE_DIR_ENV, str(tmp_path))
    payload = {"schema": "test", "marker": "redirected"}
    (tmp_path / "portfolio_snapshot.json").write_text(json.dumps(payload), encoding="utf-8")
    assert ps.read_portfolio_snapshot() == payload


def test_read_returns_none_when_the_redirected_path_is_empty(monkeypatch, tmp_path):
    monkeypatch.setenv(ps.STATE_DIR_ENV, str(tmp_path / "nothing-here"))
    assert ps.read_portfolio_snapshot() is None
