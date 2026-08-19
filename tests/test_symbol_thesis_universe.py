"""Unit tests for symbol universe + thesis coverage (no live DB required for core)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_symbol_thesis_id():
    from scripts.lib.symbol_thesis_coverage import symbol_thesis_id
    assert symbol_thesis_id("SCHG") == "symbol_schg"
    assert symbol_thesis_id("12507E201").startswith("symbol_s_")


def test_portfolio_role_operator_schg(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    # write local override file
    cfg = ROOT / "config" / "operator_portfolio_roles.json"
    assert cfg.exists()
    from scripts.lib.portfolio_role import resolve_portfolio_role
    r = resolve_portfolio_role("SCHG", root=ROOT)
    assert r["portfolio_role"] == "GROWTH"
    assert r["confidence"] == "HIGH"
    assert "operator" in r["source"]


def test_coverage_missing_vs_current(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.cio_theses import CIOThesisStore
    from scripts.lib.symbol_thesis_coverage import classify_symbol, symbol_thesis_id
    from scripts.lib.symbol_thesis_publish import publish_symbol_thesis

    store = CIOThesisStore(
        event_path=tmp_path / "theses.jsonl",
        projection_path=tmp_path / "proj.json",
    )
    uni = {
        "memberships": ["HELD", "WATCHLIST"],
        "held": True,
        "reentry": {"intel_state": "CURRENTLY HELD"},
        "opportunity": None,
        "former": None,
    }
    row = classify_symbol("SCHG", universe_rec=uni, store=store, root=ROOT)
    assert row["coverage_state"] == "RESEARCH_REQUIRED"
    assert row["has_current_symbol_thesis"] is False
    assert row["portfolio_role"]["portfolio_role"] == "GROWTH"

    publish_symbol_thesis(
        "SCHG",
        summary=(
            "SCHG is the book's primary large-cap growth sleeve. "
            "We own it for growth exposure; invalidation if growth leadership breaks."
        ),
        stance="hold",
        portfolio_role="GROWTH",
        universe_memberships=["HELD"],
        why_owned_or_watched="Growth exposure sleeve",
        store=store,
        notify=False,
    )
    row2 = classify_symbol("SCHG", universe_rec=uni, store=store, root=ROOT)
    assert row2["has_current_symbol_thesis"] is True
    assert row2["coverage_state"] == "CURRENT"
    assert row2["thesis_id"] == symbol_thesis_id("SCHG")


def test_research_gap_triggers_include_reentry(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    from scripts.lib.cio_theses import CIOThesisStore
    from scripts.lib.symbol_thesis_coverage import classify_symbol, research_gap_triggers

    store = CIOThesisStore(
        event_path=tmp_path / "theses.jsonl",
        projection_path=tmp_path / "proj.json",
    )
    uni = {
        "memberships": ["FORMER_HOLDING", "REENTRY", "OPPORTUNITY"],
        "held": False,
        "reentry": {"intel_state": "NEAR ENTRY"},
        "opportunity": {"rank": 6},
        "former": {"category": "position"},
    }
    row = classify_symbol("CSCO", universe_rec=uni, store=store, root=ROOT)
    report = {"rows": [row]}
    gaps = research_gap_triggers(report)
    assert gaps
    assert "missing_thesis" in gaps[0]["triggers"] or "reentry_without_thesis" in gaps[0]["triggers"]


def test_universe_reconcile_from_fixture(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    # minimal fixture tree
    (tmp_path / "data/portfolios/state").mkdir(parents=True)
    (tmp_path / "data/runtime").mkdir(parents=True)
    (tmp_path / "data/cio").mkdir(parents=True)
    holdings = {
        "holdings": [
            {"symbol": "SCHG", "quantity": 100, "account": "schwab_taxable"},
            {"symbol": "SPAXX", "quantity": 1},
        ]
    }
    (tmp_path / "data/portfolios/state/holdings.json").write_text(json.dumps(holdings))
    reentry = {
        "rows": [
            {"symbol": "SCHG", "held": True, "intel": {"state": "CURRENTLY HELD"}, "advisory": {"action": "Monitor"}},
            {"symbol": "CSCO", "held": False, "intel": {"state": "NEAR ENTRY"}, "advisory": {"action": "Prepare"}},
        ]
    }
    (tmp_path / "data/runtime/reentry_decision_desk_latest.json").write_text(json.dumps(reentry))
    brief = {
        "opportunity_book": {
            "top": [{"rank": 1, "symbol": "CSCO", "source": "reentry", "label": "CSCO"}]
        }
    }
    (tmp_path / "data/cio/cio_investment_brief.json").write_text(json.dumps(brief))

    from scripts.lib.symbol_universe import reconcile_universe
    u = reconcile_universe(tmp_path)
    assert u["counts"]["HELD"] == 1
    assert "SCHG" in u["symbols"]
    assert "HELD" in u["symbols"]["SCHG"]["memberships"]
    assert "REENTRY" in u["symbols"]["CSCO"]["memberships"]
    assert "OPPORTUNITY" in u["symbols"]["CSCO"]["memberships"]
    assert "SPAXX" not in u["symbols"]
