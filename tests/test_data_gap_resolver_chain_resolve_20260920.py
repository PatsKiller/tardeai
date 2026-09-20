"""data_gap_resolver must walk gap_resolver.resolve for catalyst-shaped gaps."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load():
    key = "_tested_data_gap_resolver_chain_20260920"
    if key in sys.modules:
        del sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        key, ROOT / "scripts" / "data_gap_resolver.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


class _Cur:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, rows):
        self._cur = _Cur(rows)

    def cursor(self):
        return self._cur


def test_chain_resolve_maps_catalyst_gaps_and_stamps_requester():
    R = _load()
    rows = [
        (11, "NOC", "missing_catalyst", "near-term catalyst?"),
        (12, "BAH", "stale_news", None),
    ]
    conn = _Conn(rows)
    seen = []

    class FakeRes:
        outcome = "partial"
        vector = "governed_search"

    def fake_resolve(gap, ctx=None):
        seen.append(gap)
        return FakeRes()

    fake_mod = mock.Mock()
    fake_mod.Context = mock.Mock(return_value=mock.Mock())
    fake_mod.DataGap = lambda **kw: mock.Mock(**kw)
    fake_mod.resolve = fake_resolve

    with mock.patch.dict(
        sys.modules,
        {
            "scripts.lib.gap_resolver": fake_mod,
            "lib.gap_resolver": fake_mod,
        },
    ):
        # Force re-import path inside chain_resolve to see our fake
        n = R.chain_resolve_open_gaps(conn, dry_run=False, limit=5)

    assert n == 2
    assert len(seen) == 2
    assert seen[0].requester == "data_gap_resolver"
    assert seen[0].domain == "catalyst_news"
    assert seen[0].subject == "NOC"
    assert seen[1].subject == "BAH"


def test_chain_resolve_dry_run_does_not_call_resolve():
    R = _load()
    conn = _Conn([(1, "NOC", "missing_catalyst", "q")])
    called = []

    fake_mod = mock.Mock()
    fake_mod.Context = mock.Mock()
    fake_mod.DataGap = mock.Mock()
    fake_mod.resolve = lambda *a, **k: called.append(1)

    with mock.patch.dict(
        sys.modules,
        {"scripts.lib.gap_resolver": fake_mod, "lib.gap_resolver": fake_mod},
    ):
        n = R.chain_resolve_open_gaps(conn, dry_run=True, limit=5)
    assert n == 1
    assert called == []
