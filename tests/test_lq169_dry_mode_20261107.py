"""LQ-20261107-169 — write-free --dry-run for five n8n lanes.

Each test proves the dry path does not write: it either snapshots the tree, records every SQL
statement, or asserts the apply-only function is never reached.
"""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import sec_filings_feed as sff  # noqa: E402


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


# --- sec-filings-feed ---------------------------------------------------------------------------

@pytest.fixture
def fake_sec(monkeypatch):
    from financial_senses import sec_companyfacts_reader as sec

    def fetcher(url):
        return {"0": {"ticker": "AAPL", "cik_str": 320193}}

    def get_submissions(cik, _fetcher):
        return {"filings": {"recent": {"form": [], "filingDate": [], "accessionNumber": [], "items": []}}}

    monkeypatch.setattr(sec, "_default_fetcher", fetcher)
    monkeypatch.setattr(sec, "get_submissions", get_submissions)


def test_sec_dry_run_is_a_real_plan_and_writes_nothing(tmp_path, fake_sec, capsys):
    before = _tree(tmp_path)
    rc = sff.main(["--dry-run", "--root", str(tmp_path), "--symbols", "AAPL"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" not in out  # the old offline stub is gone
    assert '"mode": "dry_run"' in out
    assert _tree(tmp_path) == before


def test_sec_dry_run_wins_over_apply_and_writes_nothing(tmp_path, fake_sec, capsys):
    before = _tree(tmp_path)
    rc = sff.main(["--dry-run", "--apply", "--root", str(tmp_path), "--symbols", "AAPL"])
    assert rc == 0
    assert '"mode": "dry_run"' in capsys.readouterr().out
    assert _tree(tmp_path) == before


def test_sec_dry_run_does_not_rewrite_stale_ticker_cache(tmp_path):
    cache = tmp_path / "data" / "runtime" / "sec_company_tickers.json"
    cache.parent.mkdir(parents=True)
    original = {"0": {"ticker": "OLD", "cik_str": 1}}
    cache.write_text(json.dumps(original), encoding="utf-8")
    os.utime(cache, (0, 0))  # ancient mtime -> stale -> refetched, but a dry run must not persist it
    fresh = lambda url: {"0": {"ticker": "AAPL", "cik_str": 320193}}  # noqa: E731
    mapping = sff.load_ticker_map(tmp_path, fresh, persist=False)
    assert mapping == {"AAPL": "0000320193"}
    assert json.loads(cache.read_text(encoding="utf-8")) == original


def test_sec_apply_still_persists_ticker_cache(tmp_path):
    cache = tmp_path / "data" / "runtime" / "sec_company_tickers.json"
    sff.load_ticker_map(tmp_path, lambda url: {"0": {"ticker": "AAPL", "cik_str": 320193}}, persist=True)
    assert cache.exists()


# --- proposal-backtest-engine -------------------------------------------------------------------

def test_proposal_backtest_cli_dry_run_reaches_real_main(monkeypatch):
    import proposal_backtest_engine as pbe

    seen = []

    def _record(argv=None):
        seen.append(list(argv))
        return 0

    monkeypatch.setattr(pbe, "main", _record)
    rc = pbe.cli(["--dry-run", "--all-pending", "--apply"])
    assert rc == 0
    assert seen == [["--dry-run", "--all-pending", "--apply"]], "cli() must hand --dry-run to main, not stub it"


# --- build-catalyst-graph -----------------------------------------------------------------------

def test_catalyst_graph_dry_run_wins_over_apply_and_writes_nothing(tmp_path, monkeypatch, capsys):
    import build_catalyst_graph as bcg

    monkeypatch.setattr(bcg, "load_registry", lambda: {})
    monkeypatch.setattr(bcg, "fetch_catalysts", lambda limit: [])
    monkeypatch.setattr(bcg, "build_graph", lambda c, r: {"node_count": 0, "trace_count": 0,
                                                          "bound_by_type": {}, "skipped": {}})
    monkeypatch.setattr(bcg, "projection_path", lambda: tmp_path / "proj" / "graph.json")
    monkeypatch.setattr(bcg, "_state_root", lambda: tmp_path / "state")
    before = _tree(tmp_path)
    rc = bcg.main(["--dry-run", "--apply"])
    assert rc == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert _tree(tmp_path) == before


# --- reclassify-momentum-proposals --------------------------------------------------------------

def _fake_db(monkeypatch, rows):
    calls: list[str] = []
    mod = types.ModuleType("db_adapter")

    def _execute(sql, params=None, fetch=None):
        calls.append(sql.strip())
        return rows if sql.lstrip().upper().startswith("SELECT") else None

    mod._execute = _execute
    monkeypatch.setitem(sys.modules, "db_adapter", mod)
    return calls


_GAP_ROW = {"id": 1, "symbol": "XYZ", "strategy_id": "fib_retracement_bounce", "rvol": 10.0,
            "gap_pct": 8.0, "float_m": 200.0, "catalyst": "earnings beat"}


def test_reclassify_dry_run_selects_and_never_updates(monkeypatch, capsys):
    import reclassify_momentum_proposals as rmp

    calls = _fake_db(monkeypatch, [dict(_GAP_ROW)])
    rmp.main(["--dry-run", "--apply"])
    out = capsys.readouterr().out
    assert calls and all(c.upper().startswith("SELECT") for c in calls), calls
    assert "XYZ" in out and "swing_breakout" in out  # the real plan is printed


def test_reclassify_control_apply_does_update(monkeypatch):
    """Control: proves the fake DB would record an UPDATE, so the dry-run assertion above is not vacuous."""
    import reclassify_momentum_proposals as rmp

    calls = _fake_db(monkeypatch, [dict(_GAP_ROW)])
    rmp.main(["--apply"])
    assert any(c.upper().startswith("UPDATE") for c in calls)


# --- sweep-commitment-outcomes ------------------------------------------------------------------

def test_commitment_sweep_dry_run_wins_over_apply_and_never_runs(tmp_path, monkeypatch):
    import sweep_commitment_outcomes as sco

    def _boom(args):
        raise AssertionError("dry run must not reach the sweep body")

    monkeypatch.setattr(sco, "_run", _boom)
    before = _tree(tmp_path)
    rc = sco.main(["--dry-run", "--apply", "--state-root", str(tmp_path)])
    assert rc == 0
    assert _tree(tmp_path) == before
