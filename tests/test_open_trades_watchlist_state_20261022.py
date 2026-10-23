"""Open Trades watchlist_state (operator fix 2026-10-22) — scripts/open_trades_intelligence.py.

ANCHOR: OPEN_TRADES_WATCHLIST_STATE_20261022

Root cause: build_intelligence() looked up watchlist / directive membership with `_db_query(...)`, a name
the module never defined. The NameError was swallowed by a bare `except Exception: pass`, so every held
position reported watchlist_state "none" — indistinguishable from "looked up, not on the list".

Fix pinned here: membership is read through the Watch data broker (watch_domains.membership_watchlist for
watchlist_items, watch_intelligence.active_ticker_directives(strict=True) for watch_directives), and a failed
lookup reports "unavailable" and logs it. Hermetic: fakes only, no DB, broker or data/ file.
"""
from __future__ import annotations

import ast
import builtins
import importlib
import logging
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from tests.test_open_trades_accuracy_20261022 import _build, _holding, _iso, _row  # noqa: E402


def _patch_membership(monkeypatch, *, watchlist=(), directives=(), fail=False):
    import lib.data_broker.watch_domains as wd
    import lib.data_broker.watch_intelligence as wi

    def fake_membership(symbols):
        if fail:
            raise RuntimeError("db down")
        return {s for s in symbols if s in set(watchlist)}

    def fake_directives(*, strict=False):
        assert strict is True, "Open Trades must ask for the strict (raising) directive read"
        if fail:
            raise RuntimeError("db down")
        return [{"symbol": s} for s in directives]

    monkeypatch.setattr(wd, "membership_watchlist", fake_membership)
    monkeypatch.setattr(wi, "active_ticker_directives", fake_directives)


def _three():
    return [
        _holding("V", "schwab_roth", 100, mark=412.43, ingested=_iso(0.5), basis=40000.0),
        _holding("XLB", "schwab_rollover_ira", 10, mark=51.0, ingested=_iso(0.5), basis=500.0),
        _holding("SCHD", "schwab_rollover_ira", 10, mark=35.0, ingested=_iso(0.5), basis=300.0),
    ]


def test_watched_symbol_gets_its_state(monkeypatch):
    _patch_membership(monkeypatch, watchlist=["V"], directives=["XLB"])
    out, _ = _build(monkeypatch, _three())
    assert _row(out, "V")["watchlist_state"] == "watchlist"
    assert _row(out, "V")["directive_state"] == "none"
    assert _row(out, "XLB")["watchlist_state"] == "directive"
    assert _row(out, "XLB")["directive_state"] == "active"
    assert _row(out, "SCHD")["watchlist_state"] == "none"
    assert out["summary"]["watch_membership"] == "ok"


def test_failing_lookup_reports_unavailable_and_logs(monkeypatch, caplog):
    _patch_membership(monkeypatch, fail=True)
    with caplog.at_level(logging.WARNING, logger="open_trades_intelligence"):
        out, _ = _build(monkeypatch, _three())
    for sym in ("V", "XLB", "SCHD"):
        assert _row(out, sym)["watchlist_state"] == "unavailable"
        assert _row(out, sym)["directive_state"] == "unavailable"
    assert out["summary"]["watch_membership"] == "unavailable"
    assert any("membership lookup failed" in r.getMessage() for r in caplog.records)


def test_membership_helper_is_defined_and_importable():
    oti = importlib.import_module("open_trades_intelligence")
    assert callable(oti._watch_membership)
    from lib.data_broker.watch_domains import membership_watchlist  # noqa: F401
    from lib.data_broker.watch_intelligence import active_ticker_directives  # noqa: F401


def test_no_undefined_private_helper_is_called():
    """The bug class: a call to a module-private name the module never defines or imports."""
    src = (SCRIPTS / "open_trades_intelligence.py").read_text()
    tree = ast.parse(src)
    bound = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
            if not isinstance(node, ast.ClassDef):
                a = node.args
                for arg in a.args + a.kwonlyargs + a.posonlyargs + [x for x in (a.vararg, a.kwarg) if x]:
                    bound.add(arg.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for al in node.names:
                bound.add((al.asname or al.name).split(".")[0])
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not sorted(c for c in called if c not in bound), "undefined helper called"
    assert "_db_query" not in called


def test_membership_watchlist_reads_watchlist_items_and_raises_on_error(monkeypatch):
    import lib.data_broker.watch_domains as wd
    seen = {}

    def fake_q(sql, params=None, fetch="all"):
        seen["sql"], seen["params"] = sql, params
        return [{"s": "V"}]

    monkeypatch.setattr(wd, "_db_query", fake_q)
    assert wd.membership_watchlist(["v", "XLB", ""]) == {"V"}
    assert "FROM watchlist_items" in seen["sql"] and seen["params"] == (["V", "XLB"],)
    assert wd.membership_watchlist([]) == set()

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(wd, "_db_query", boom)
    with pytest.raises(RuntimeError):
        wd.membership_watchlist(["V"])


def test_active_ticker_directives_strict_raises_default_stays_fail_soft(monkeypatch):
    import lib.data_broker.watch_intelligence as wi

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=boom))
    assert wi.active_ticker_directives() == []
    with pytest.raises(RuntimeError):
        wi.active_ticker_directives(strict=True)
