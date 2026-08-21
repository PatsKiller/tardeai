"""Held-book thesis coverage SLA + revision ledger stub."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_coverage_report_structure(tmp_path, monkeypatch):
    from scripts.lib import cio_held_thesis_coverage as m

    # Fake held list
    monkeypatch.setattr(m, "list_held_tickers", lambda root=None: ["JEPI", "SCHD", "ZZZZ"])

    def fake_row(symbol, root=None):
        if symbol == "JEPI":
            return {
                "symbol": "JEPI",
                "thesis_state": "CURRENT",
                "has_current_symbol_thesis": True,
                "portfolio_role": "INCOME",
                "symbol_thesis_version": "symbol_JEPI@v1",
                "research_gaps": [],
                "needs_coverage": False,
                "fresh": True,
                "thesis_age_days": 2.0,
                "sla_days": 14,
                "coverage_class": "held_income",
            }
        return {
            "symbol": symbol,
            "thesis_state": "RESEARCH_REQUIRED",
            "has_current_symbol_thesis": False,
            "portfolio_role": None,
            "symbol_thesis_version": None,
            "research_gaps": ["Create living symbol thesis"],
            "needs_coverage": True,
            "fresh": False,
            "thesis_age_days": None,
            "sla_days": 30,
            "coverage_class": "held_growth_core",
        }

    monkeypatch.setattr(m, "coverage_row_for_symbol", fake_row)
    rep = m.build_held_coverage_report(root=tmp_path)
    assert rep["held_count"] == 3
    assert rep["current_count"] == 1
    assert abs(rep["held_current_pct"] - 33.33) < 0.1
    assert "coverage_pct" in rep and "fresh_pct" in rep
    assert abs(rep["coverage_pct"] - 33.33) < 0.1
    assert abs(rep["fresh_pct"] - 33.33) < 0.1
    assert rep["coverage_pct"] == rep["held_current_pct"]
    assert "SCHD" in rep["needs_coverage"]
    assert "JEPI" not in rep["needs_coverage"]
    assert rep["sla_target_pct"] == 100.0
    assert rep["sla_met"] is False
    path = m.write_coverage_report(rep, root=tmp_path)
    assert path.is_file()
    data = json.loads(path.read_text())
    assert data["schema"] == "HeldBookThesisCoverage@v1"
    assert data["sla_target_pct"] == 100.0
    assert "coverage_pct" in data and "fresh_pct" in data


def test_held_sla_is_100_not_80():
    from pathlib import Path
    from scripts.lib.cio_held_thesis_coverage import SLA_TARGET_PCT

    assert SLA_TARGET_PCT == 100.0
    src = (Path(__file__).resolve().parents[1] / "scripts/lib/cio_held_thesis_coverage.py").read_text()
    assert "80.0" not in src
    assert "sla_target_pct" in src
    assert "100.0" in src


def test_held_excludes_cash_and_actionable_is_separate(tmp_path, monkeypatch):
    import scripts.lib.symbol_universe as su
    monkeypatch.setattr(su, "_former_from_db", lambda root: {})
    monkeypatch.setattr(su, "_watchlist_from_db", lambda root: {})
    from scripts.lib.cio_held_thesis_coverage import (
        build_held_coverage_report,
        list_held_tickers,
        write_coverage_report,
    )
    from scripts.lib.symbol_thesis_coverage import build_actionable_coverage_report

    holdings = tmp_path / "data" / "portfolios" / "state"
    holdings.mkdir(parents=True)
    (holdings / "holdings.json").write_text(json.dumps({
        "holdings": [
            {"symbol": "JEPI", "is_cash": False, "market_value": 100},
            {"symbol": "SCHD", "is_cash": False, "market_value": 100},
            {"symbol": "CASH", "is_cash": True, "asset_type": "cash", "market_value": 9},
            {"symbol": "12507E201", "is_cash": False, "market_value": 0},
        ]
    }))
    runtime = tmp_path / "data" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "reentry_decision_desk_latest.json").write_text(json.dumps({
        "rows": [
            {"symbol": "AVAV", "held": False, "intel": {"state": "READY TO REVIEW"}},
            {"symbol": "AXTI", "held": False, "intel": {"state": "READY TO REVIEW"}},
            {"symbol": "DHX", "held": False, "intel": {"state": "NEAR ENTRY"}},
            {"symbol": "MOGU", "held": False, "intel": {"state": "NEAR ENTRY"}},
            {"symbol": "JEPI", "held": True, "intel": {"state": "CURRENTLY HELD"}},
        ]
    }))
    (tmp_path / "data" / "cio").mkdir(parents=True)

    held = list_held_tickers(root=tmp_path)
    assert "CASH" not in held
    assert "12507E201" not in held
    assert held == ["JEPI", "SCHD"]

    held_rep = build_held_coverage_report(root=tmp_path)
    assert held_rep["held_count"] == 2
    assert held_rep["held_equity_ticker_n"] == 2
    assert "AVAV" not in [r["symbol"] for r in held_rep["rows"]]
    assert "CASH" not in [r["symbol"] for r in held_rep["rows"]]
    assert held_rep["sla_target_pct"] == 100.0
    assert "coverage_pct" in held_rep and "fresh_pct" in held_rep

    act = build_actionable_coverage_report(root=tmp_path)
    assert "held_count" not in act
    assert act["reentry_actionable_n"] == 4
    assert set(act["reentry_ready"]) == {"AVAV", "AXTI"}
    assert set(act["reentry_near"]) == {"DHX", "MOGU"}
    assert "JEPI" not in act["reentry_ready"]
    assert "JEPI" not in act["reentry_near"]
    assert "coverage_pct" in act and "fresh_pct" in act

    write_coverage_report(held_rep, root=tmp_path)
    sibling = tmp_path / "data" / "cio" / "actionable_thesis_coverage_latest.json"
    assert sibling.is_file()
    saved = json.loads(sibling.read_text())
    assert saved["reentry_actionable_n"] == 4
    assert "held_count" not in saved


def test_append_revision_ledger(tmp_path):
    from scripts.lib.cio_held_thesis_coverage import append_thesis_revision, revision_ledger_path

    row = append_thesis_revision(
        symbol="JEPI",
        reason="catalyst_medium_plus",
        catalyst_id="cat_1",
        severity="medium",
        impact="test",
        root=tmp_path,
        dry_notify=True,
    )
    assert row["notify"]["dry"] is True
    assert row["authority"] == "READ_ONLY_ADVISORY"
    p = revision_ledger_path(tmp_path)
    assert p.is_file()
    lines = p.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["symbol"] == "JEPI"


def test_is_ticker():
    from scripts.lib.cio_held_thesis_coverage import _is_ticker

    assert _is_ticker("JEPI")
    assert _is_ticker("BRK.B")
    assert not _is_ticker("CASH")
    assert not _is_ticker("912810TM0")  # CUSIP-like
