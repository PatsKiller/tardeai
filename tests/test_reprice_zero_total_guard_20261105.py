"""The repricer never turns a total it cannot compute into a zero.

Finding (cc-deepseek-5, 2026-11-05, confirmed on `origin/main` `0b2a5b86d`): the */15 repricer writes
`data/portfolios/state/holdings.json` through a raw `Path.write_text`, and `_recalc_totals` sums account totals with
`(acct.get("total_value") or 0)`. A holding row with no `market_value` — or a document with no account summaries — makes
that sum `0`, which the existing drift guard cannot see because it only evaluates when `gt > 0`. The result is a
*plausible* zero written over a real total, which is worse than an unknown: every surface that reads the document then
believes the portfolio is worth nothing.

What this file pins (claude-lead's scope, in order):

1. a fall to zero from a positive previous total is 100% drift and must be refused;
2. "no accounts" is unknown, not zero — and a genuine zero is NOT refused (a fix that refuses everything is not a fix);
3. the live-coverage refusal no longer depends on Schwab symbols existing;
4. the refusal uses the existing mechanism (`_reprice_refused`), so `portfolio_repricer.__main__` takes its SystemExit(3)
   path and does not rewrite the document;
5. the writer: see the module note — the repricer keeps its raw write only because the totals are refused *before* the
   write; a document-level sanity pass belongs to `protected_holdings_write`, which the aggregate publisher in the same
   module already uses.

Hermetic: every provider entry point is stubbed, the state dir is a temporary directory, and no real portfolio value is
read or asserted on.
"""
from __future__ import annotations

import io
import contextlib
import sys
import types
from pathlib import Path

import pytest

from scripts import portfolio_repricer as R

ROOT = Path(__file__).resolve().parents[1]


def _stub_providers(monkeypatch):
    """Every outbound read fails or returns nothing: this file is about the totals, not the price sources."""
    monkeypatch.setattr(R, "_load_env", lambda root: None, raising=False)
    monkeypatch.setattr(R, "_fetch_finviz", lambda syms, root: {}, raising=False)
    monkeypatch.setattr(R, "_fetch_data_broker_quotes", lambda syms, root, batch_reader=None: {}, raising=False)
    monkeypatch.setattr(R, "_fetch_fidelity_from_cache", lambda syms, root: {}, raising=False)
    monkeypatch.setattr(R, "_update_quote_cache", lambda *a, **k: 0, raising=False)
    monkeypatch.setattr(R, "_sync_ticker_prices", lambda *a, **k: None, raising=False)
    # ticker_snapshot_builder is imported lazily inside reprice_portfolio; give it a no-op module.
    fake = types.ModuleType("ticker_snapshot_builder")
    fake.build_ticker_snapshot = lambda portfolio, root: "stub"
    monkeypatch.setitem(sys.modules, "ticker_snapshot_builder", fake)


def _state_dir(tmp_path: Path) -> Path:
    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    return state


def _portfolio(holdings, summaries, prev_total):
    totals = {} if prev_total is None else {"total_value": prev_total, "day_change": 1.0}
    doc = {"holdings": holdings, "portfolio_totals": totals}
    if summaries is not None:
        doc["account_summaries"] = summaries
    return doc


def _run(monkeypatch, tmp_path, doc):
    _stub_providers(monkeypatch)
    with contextlib.redirect_stdout(io.StringIO()):
        out = R.reprice_portfolio(doc, _state_dir(tmp_path))
    return out


HOLDING_UNPRICED = [{"account": "acct_a", "symbol": "ABC", "shares": 10, "cost_basis": 900.0}]
HOLDING_ZERO = [{"account": "acct_a", "symbol": "ABC", "shares": 0, "market_value": 0.0, "cost_basis": 0.0}]


def test_an_empty_document_is_refused_not_zeroed(monkeypatch, tmp_path):
    """The rebuilt/partial document: no holdings at all, a real total on file."""
    out = _run(monkeypatch, tmp_path, _portfolio([], {}, prev_total=1_000_000.0))
    assert out.get("_reprice_refused"), "an empty document must refuse, not write 0"
    assert (out.get("portfolio_totals") or {}).get("total_value") == 1_000_000.0, "the prior total must stand"


def test_a_holding_without_a_market_value_is_refused(monkeypatch, tmp_path):
    """One unpriced row collapses its account total to 0 through the `or 0` sums."""
    out = _run(monkeypatch, tmp_path,
               _portfolio(HOLDING_UNPRICED, {"acct_a": {"total_value": 1_000_000.0, "day_change": 1.0}},
                          prev_total=1_000_000.0))
    assert out.get("_reprice_refused"), "an unpriced holding must not become a zero total"
    assert (out.get("portfolio_totals") or {}).get("total_value") == 1_000_000.0


def test_absent_account_summaries_is_unknown_not_zero(monkeypatch, tmp_path):
    out = _run(monkeypatch, tmp_path, _portfolio(HOLDING_UNPRICED, None, prev_total=1_000_000.0))
    assert out.get("_reprice_refused"), "no accounts is an unknown total, not a zero"
    assert "summar" in str(out.get("_reprice_refused")).lower()


def test_a_genuine_zero_is_not_refused(monkeypatch, tmp_path):
    """A book that really is worth zero must price and write — a fix that refuses everything is not a fix."""
    out = _run(monkeypatch, tmp_path,
               _portfolio(HOLDING_ZERO, {"acct_a": {"total_value": 0.0, "day_change": 0.0}}, prev_total=None))
    assert not out.get("_reprice_refused"), f"a genuine zero was refused: {out.get('_reprice_refused')}"
    assert (out.get("portfolio_totals") or {}).get("total_value") == 0


def test_the_drift_guard_evaluates_at_zero():
    """The guard's most important case: 100% drift. Reverting `gt > 0` must make this red (mutation-checked)."""
    import inspect
    src = inspect.getsource(R._recalc_totals)
    assert "prev_total > 0 and gt > 0" not in src, (
        "the drift guard still skips the gt == 0 case, which is the whole collapse this change exists to refuse"
    )
