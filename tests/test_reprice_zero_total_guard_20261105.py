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
4. the refusal is an exception, so every caller — `__main__` (AND the module executed as a real script, which is the
   only check that can see load order), the SnapTrade sync, the reprice-only launcher and the orchestrator — is driven
   and shown to write nothing on a refused pass;
5. the writer: see the module note — the repricer keeps its raw write only because the totals are refused *before* the
   write; a document-level sanity pass belongs to `protected_holdings_write`, which the aggregate publisher in the same
   module already uses.

Hermetic: every provider entry point is stubbed, the state dir is a temporary directory, and no real portfolio value is
read or asserted on.

ANCHOR: REPRICE_ZERO_TOTAL_GUARD_20261105
"""
from __future__ import annotations

import io
import json
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
    """Run the pass; a refusal raises RepriceRefused (cc-deepseek-8's F1/F2: no sentinel in the payload)."""
    _stub_providers(monkeypatch)
    with contextlib.redirect_stdout(io.StringIO()):
        return R.reprice_portfolio(doc, _state_dir(tmp_path))


def _refused(monkeypatch, tmp_path, doc):
    """Run the pass expecting a refusal; return the exception. Also asserts the input document was not mutated."""
    before = json.loads(json.dumps(doc))
    _stub_providers(monkeypatch)
    with contextlib.redirect_stdout(io.StringIO()):
        with pytest.raises(R.RepriceRefused) as caught:
            R.reprice_portfolio(doc, _state_dir(tmp_path))
    assert doc == before, "a refused pass must not mutate the caller's document"
    assert "_reprice_refused" not in doc, "a refusal must never leave a marker in the payload"
    return caught.value


HOLDING_UNPRICED = [{"account": "acct_a", "symbol": "ABC", "shares": 10, "cost_basis": 900.0}]
HOLDING_ZERO = [{"account": "acct_a", "symbol": "ABC", "shares": 0, "market_value": 0.0, "cost_basis": 0.0}]


def test_an_empty_document_is_refused_not_zeroed(monkeypatch, tmp_path):
    """The rebuilt/partial document: no holdings at all, a real total on file."""
    doc = _portfolio([], {}, prev_total=1_000_000.0)
    _refused(monkeypatch, tmp_path, doc)
    assert doc["portfolio_totals"]["total_value"] == 1_000_000.0, "the prior total must stand"


def test_a_holding_without_a_market_value_is_refused(monkeypatch, tmp_path):
    """One unpriced row collapses its account total to 0 through the `or 0` sums."""
    doc = _portfolio(HOLDING_UNPRICED, {"acct_a": {"total_value": 1_000_000.0, "day_change": 1.0}},
                     prev_total=1_000_000.0)
    _refused(monkeypatch, tmp_path, doc)
    assert doc["portfolio_totals"]["total_value"] == 1_000_000.0


def test_absent_account_summaries_is_unknown_not_zero(monkeypatch, tmp_path):
    exc = _refused(monkeypatch, tmp_path, _portfolio(HOLDING_UNPRICED, None, prev_total=1_000_000.0))
    assert "summar" in exc.reason.lower(), exc.reason


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


def test_the_coverage_refusal_does_not_depend_on_a_schwab_account(monkeypatch, tmp_path):
    """Scope item 3: the only live-coverage refusal used to be gated on `sym_groups["schwab"]`, so an all-alpaca or
    all-moomoo book had no coverage guard at all. The guard must measure every held tradeable equity."""
    holdings = [{"account": "alpaca_taxable_live", "symbol": "ABC", "shares": 10,
                 "market_value": 1000.0, "price": 100.0, "day_change": 5.0, "cost_basis": 900.0}]
    exc = _refused(monkeypatch, tmp_path,
                   _portfolio(holdings, {"alpaca_taxable_live": {"total_value": 1000.0, "day_change": 5.0}},
                              prev_total=1000.0))
    assert "coverage" in exc.reason.lower(), exc.reason


def test_the_drift_guard_is_what_refuses_a_priced_but_zero_total(monkeypatch, tmp_path):
    """The drift guard's own behavioural case, with every other refusal out of the way: the account summary is
    present and numeric, the holding is *priced* (market_value 0.0, not None), and the recomputed total is 0 while
    the document says the book was worth something. Only the guard can refuse this, so reverting `gt <= 0` to the old
    `gt > 0` makes this test red (mutation-checked)."""
    holdings = [{"account": "acct_a", "symbol": "ABC", "shares": 0, "market_value": 0.0, "price": 0.0,
                 "day_change": 0.0, "cost_basis": 900.0}]
    doc = _portfolio(holdings, {"acct_a": {"total_value": 1_000_000.0, "day_change": 1.0}},
                     prev_total=1_000_000.0)
    exc = _refused(monkeypatch, tmp_path, doc)
    assert "collapsed" in exc.reason.lower(), exc.reason
    assert doc["portfolio_totals"]["total_value"] == 1_000_000.0


def test_a_healthy_pass_never_carries_a_marker(monkeypatch, tmp_path):
    """cc8 F2: the marker must not exist at all any more — a persisted marker once stalled every later run."""
    out = _run(monkeypatch, tmp_path,
               _portfolio([{"account": "acct_a", "symbol": "ABC", "shares": 0, "market_value": 1000.0,
                            "price": 100.0, "day_change": 5.0, "cost_basis": 900.0}],
                          {"acct_a": {"total_value": 1000.0, "day_change": 5.0}}, prev_total=None))
    assert "_reprice_refused" not in out


def test_a_document_carrying_an_old_marker_is_healed(monkeypatch, tmp_path):
    """cc8's second-order question: a document poisoned by the OLD build must recover, not stay stuck."""
    doc = _portfolio([{"account": "acct_a", "symbol": "ABC", "shares": 0, "market_value": 1000.0,
                       "price": 100.0, "day_change": 5.0, "cost_basis": 900.0}],
                     {"acct_a": {"total_value": 1000.0, "day_change": 5.0}}, prev_total=1000.0)
    doc["_reprice_refused"] = "account fidelity_trust: every holding row is unpriced (written by the old build)"
    out = _run(monkeypatch, tmp_path, doc)
    assert "_reprice_refused" not in out, "the healed document must go back to disk without the marker"
    assert (out.get("portfolio_totals") or {}).get("total_value") == 1000.0


def test_a_real_liquidation_is_accepted_after_a_positive_total(monkeypatch, tmp_path):
    """cc8 F3: a book that genuinely went to zero must not be refused forever by the guard's own non-rewrite."""
    doc = _portfolio([], {"acct_a": {"total_value": 0.0, "day_change": 0.0}}, prev_total=30_000.0)
    out = _run(monkeypatch, tmp_path, doc)
    assert (out.get("portfolio_totals") or {}).get("total_value") == 0


# ── the call sites (cc-deepseek-8's F1: the refusal was honoured by __main__ only) ────────────────────────────────

def test_snaptrade_sync_does_not_write_a_refused_document(monkeypatch, tmp_path):
    """Driven at the real call site: snaptrade_sync._reprice_and_write must not touch the file when the reprice refuses."""
    import scripts.snaptrade_sync as S

    target = tmp_path / "holdings.json"
    document = {"holdings": [{"account": "acct_a", "symbol": "ABC", "shares": 0, "market_value": 1000.0}],
                "account_summaries": {"acct_a": {"total_value": 1000.0, "day_change": 0.0}},
                "portfolio_totals": {"total_value": 1000.0, "day_change": 0.0}}
    target.write_text(json.dumps(document))
    before = target.read_bytes()

    def refuse(document, state_dir):
        raise R.RepriceRefused("account acct_a: every holding row is unpriced")

    # the helper imports the BARE module (scripts/ is on sys.path), not scripts.portfolio_repricer
    stub = types.ModuleType("portfolio_repricer")
    stub.reprice_portfolio = refuse
    monkeypatch.setitem(sys.modules, "portfolio_repricer", stub)
    with pytest.raises(R.RepriceRefused):
        S._reprice_and_write(target, tmp_path / "state")
    assert target.read_bytes() == before, "a refused reprice must leave the document byte-identical"


def test_the_reprice_only_launcher_writes_nothing_on_a_refusal(monkeypatch, tmp_path):
    """Driven through the launcher's own Python body, extracted from the .sh and executed with stubs."""
    import re as _re
    import types as _types

    script = (ROOT / "linux_launchers" / "run_reprice_only.sh").read_text(encoding="utf-8")
    body = _re.search(r"<<'PY'\n(.*?)\nPY\n", script, _re.S).group(1)

    root = tmp_path / "root"
    (root / "data" / "portfolios" / "state").mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    target = root / "data" / "portfolios" / "state" / "holdings.json"
    target.write_text(json.dumps({"holdings": [], "account_summaries": {}, "portfolio_totals": {}}))
    before = target.read_bytes()

    saves = []
    loader = _types.ModuleType("portfolio_loader")
    loader.load_all_portfolios = lambda r: {"holdings": [], "account_summaries": {}, "portfolio_totals": {}}
    loader.save_state = lambda portfolio, r: saves.append(r) or (_ for _ in ()).throw(AssertionError("no save"))
    repricer = _types.ModuleType("portfolio_repricer")

    def refuse(document, state_dir):
        raise R.RepriceRefused("no account summaries: the portfolio total is unknown, not zero")

    repricer.reprice_portfolio = refuse
    repricer.RepriceRefused = R.RepriceRefused   # the heredoc imports the class now (cc8 F6)
    monkeypatch.setitem(sys.modules, "portfolio_loader", loader)
    monkeypatch.setitem(sys.modules, "portfolio_repricer", repricer)

    with contextlib.redirect_stdout(io.StringIO()):
        with pytest.raises(SystemExit) as exit_info:
            exec(compile(body, "run_reprice_only.sh", "exec"), {"__name__": "__main__", "__builtins__": __builtins__})
    assert exit_info.value.code == 3, "the launcher must stop with exit 3, not save"
    assert saves == [], "the launcher must not call save_state after a refusal"
    assert target.read_bytes() == before


def test_the_orchestrator_writes_nothing_on_a_refusal(monkeypatch, tmp_path):
    """The fourth caller (cc-deepseek-8 F7 / cc-deepseek-9 P2): run_portfolio_pipeline's step 1 refuses.

    Driven through the real function with only its imports stubbed, because the guarantee is about what the
    pipeline does *after* the reprice — steps 2-10 and :279 save_state must never run on a refused book.
    """
    import types as _types
    import scripts.portfolio_orchestrator as O

    root = tmp_path / "root"
    (root / "data" / "portfolios" / "state").mkdir(parents=True)
    writes = []

    loader = _types.ModuleType("portfolio_loader")
    loader.load_all_portfolios = lambda r: {"holdings": [], "account_summaries": {}, "portfolio_totals": {}}
    loader.save_state = lambda portfolio, r: writes.append(("save_state", r))

    repricer = _types.ModuleType("portfolio_repricer")
    repricer.RepriceRefused = R.RepriceRefused

    def refuse(document, state_dir):
        raise R.RepriceRefused("no account summaries: the portfolio total is unknown, not zero")

    repricer.reprice_portfolio = refuse

    reports = _types.ModuleType("lib.portfolio_reports_root")
    reports.portfolio_reports_root = lambda: tmp_path / "reports"
    lib = _types.ModuleType("lib"); lib.portfolio_reports_root = reports
    morning = _types.ModuleType("morning_command_digest")
    morning.bundle_enabled = lambda run_type: False
    for _n in ("append_section", "send_morning_command_bundle", "fetch_hermes_movers"):
        setattr(morning, _n, lambda *a, **k: None)

    for name, mod in (("portfolio_loader", loader), ("portfolio_repricer", repricer),
                      ("lib", lib), ("lib.portfolio_reports_root", reports),
                      ("morning_command_digest", morning)):
        monkeypatch.setitem(sys.modules, name, mod)

    with contextlib.redirect_stdout(io.StringIO()):
        with pytest.raises(R.RepriceRefused):
            O.run_portfolio_pipeline(root, run_label="test", generate_report=False)

    assert writes == [], "a refused reprice must stop the pipeline before save_state"
    assert not (tmp_path / "reports").exists() or not any((tmp_path / "reports").iterdir()), \
        "a refused reprice must not publish a report"


def test_the_cli_entry_point_reaches_its_guarantee_path_as_a_real_script(tmp_path):
    """The module's own `__main__` block, executed by a real interpreter in a throwaway tree.

    This exists because the import-based tests cannot see module LOAD ORDER: `main(state_dirs)` sits inside the
    `if __name__ == "__main__"` block, so if `def main` were ever placed below that block the suite would stay
    green while `python scripts/portfolio_repricer.py` died with NameError — which is exactly the shape of the
    break this refactor risked. Nothing here touches a live path: the tree is copied into tmp_path, HOME points
    into tmp_path, and the book has no account summaries, so the pass refuses before any quote is fetched.
    """
    import shutil
    import subprocess

    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    (root / "data" / "portfolios" / "state").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "portfolio_repricer.py", root / "scripts" / "portfolio_repricer.py")
    # `lib` is the module's own helper package (resolved from the script's directory); link the real one
    # read-only rather than copying 29 MB, so the subprocess imports exactly the helpers the CLI imports.
    (root / "scripts" / "lib").symlink_to(ROOT / "scripts" / "lib", target_is_directory=True)
    target = root / "data" / "portfolios" / "state" / "holdings.json"
    target.write_text(json.dumps({"holdings": [], "portfolio_totals": {"total_value": 0.0, "day_change": 0.0}}))
    before = target.read_bytes()

    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home"), "PYTHONPATH": ""}
    proc = subprocess.run([sys.executable, str(root / "scripts" / "portfolio_repricer.py")],
                          cwd=str(root), env=env, capture_output=True, text=True, timeout=120)

    assert proc.returncode == 3, f"expected the refusal exit; got {proc.returncode}: {proc.stderr[-600:]}"
    assert "NameError" not in proc.stderr
    assert target.read_bytes() == before, "a refused CLI pass must leave holdings.json byte-identical"
