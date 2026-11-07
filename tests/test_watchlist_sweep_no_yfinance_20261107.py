"""LQ-20261107-171: the watchlist sweep's price fallback is Finviz, never yfinance (operator 2026-11-07)."""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import watchlist_enrichment_sweep as W  # noqa: E402


class _Cur:
    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return None            # market_quotes has no fresh row (the live case: 29 rows)


class _Conn:
    def cursor(self):
        return _Cur()

    def commit(self):
        raise AssertionError("the price fallback must not write market_quotes")

    rollback = commit


def _boom_yfinance(monkeypatch):
    mod = types.ModuleType("yfinance")

    def _no(name):
        raise AssertionError(f"yfinance.{name} reached")
    mod.__getattr__ = _no
    monkeypatch.setitem(sys.modules, "yfinance", mod)


def _patch_finviz(monkeypatch, rows):
    from scripts.lib import portfolio_positions as pp
    import lib.portfolio_positions as pp2
    for m in (pp, pp2):
        monkeypatch.setattr(m, "finviz_cache", lambda path=None, _r=rows: _r)


def test_fallback_uses_fresh_finviz_and_never_yfinance(monkeypatch):
    _boom_yfinance(monkeypatch)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    _patch_finviz(monkeypatch, {"NEWIPO": {"price": 12.34, "as_of": now, "source": "finviz"}})
    assert W._price(_Conn(), "NEWIPO", allow_fetch=True) == (12.34, None)


def test_no_finviz_row_is_unknown_not_a_yfinance_call(monkeypatch):
    _boom_yfinance(monkeypatch)
    _patch_finviz(monkeypatch, {})
    assert W._price(_Conn(), "NOPE", allow_fetch=True) == (None, None)


def test_stale_finviz_row_is_unknown(monkeypatch):
    _boom_yfinance(monkeypatch)
    _patch_finviz(monkeypatch, {"OLD": {"price": 9.0, "as_of": "2026-01-01T00:00:00+00:00", "source": "finviz"}})
    assert W._price(_Conn(), "OLD", allow_fetch=False) == (None, None)


def test_module_has_no_yfinance_reference_in_code():
    code = [ln for ln in (ROOT / "scripts" / "watchlist_enrichment_sweep.py").read_text(encoding="utf-8").splitlines()
            if "yfinance" in ln and not ln.lstrip().startswith(("#", '"""'))]
    assert not [ln for ln in code if "import" in ln or "yf." in ln]
