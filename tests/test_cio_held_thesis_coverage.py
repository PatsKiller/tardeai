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
            }
        return {
            "symbol": symbol,
            "thesis_state": "RESEARCH_REQUIRED",
            "has_current_symbol_thesis": False,
            "portfolio_role": None,
            "symbol_thesis_version": None,
            "research_gaps": ["Create living symbol thesis"],
            "needs_coverage": True,
        }

    monkeypatch.setattr(m, "coverage_row_for_symbol", fake_row)
    rep = m.build_held_coverage_report(root=tmp_path)
    assert rep["held_count"] == 3
    assert rep["current_count"] == 1
    assert abs(rep["held_current_pct"] - 33.33) < 0.1
    assert "SCHD" in rep["needs_coverage"]
    assert "JEPI" not in rep["needs_coverage"]
    assert rep["sla_met"] is False
    path = m.write_coverage_report(rep, root=tmp_path)
    assert path.is_file()
    data = json.loads(path.read_text())
    assert data["schema"] == "HeldBookThesisCoverage@v1"


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
