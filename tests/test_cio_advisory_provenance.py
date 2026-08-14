"""Phase 8 — advisory desk provenance on expanded rows."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_advisory_provenance import (  # noqa: E402
    ADVISORY_PROVENANCE_VERSION,
    build_expanded_row_provenance,
)


def test_version():
    assert ADVISORY_PROVENANCE_VERSION.startswith("advisory_provenance_")


def test_clean_row_facts():
    row = {
        "symbol": "AAA",
        "shares": 10.0,
        "current_price": 100.0,
        "price": 100.0,
        "market_value": 1000.0,
        "cost_basis": 800.0,
        "analyst_target": 120.0,
    }
    p = build_expanded_row_provenance(row)
    assert p["symbol"] == "AAA"
    assert p["authority"] == "READ_ONLY_ADVISORY"
    labels = [f["label"] for f in p["current_financial_facts"]]
    assert "Current price" in labels
    assert "Position value" in labels
    assert p["conflicts"] == []


def test_dual_price_conflict_surfaced():
    row = {
        "symbol": "DXCM",
        "shares": 225.0,
        "current_price": 91.26,
        "price": 90.98,
        "market_value": 20470.50,
        "cost_basis": 15985.13,
    }
    p = build_expanded_row_provenance(row)
    assert p["conflicts"]  # dual price and/or shares×px ≠ MV
    assert "order" in p
    assert p["order"][0] == "decision"


def test_trim_vs_hold_synthesis():
    row = {
        "symbol": "SCHD",
        "shares": 100.0,
        "current_price": 80.0,
        "market_value": 8000.0,
        "cost_basis": 7000.0,
        "deterministic_stance": "TRIM",
        "maria_stance": "HOLD",
        "guardian_stance": "HOLD",
    }
    p = build_expanded_row_provenance(row)
    assert p["opinion_synthesis"]
    assert "portfolio-risk" in p["opinion_synthesis"].lower() or "HOLD" in p["opinion_synthesis"]
