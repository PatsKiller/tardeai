"""Phase 3 — decision semantics hygiene (pure, no DB/broker)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib import cio_decision_semantics as ds  # noqa: E402
from scripts.lib import cio_capital_plan as cp  # noqa: E402
from scripts.lib import cio_sector_opportunity as so  # noqa: E402


def test_infer_stance_from_advisory_trim_label():
    assert ds.infer_stance_from_text("Advisory TRIM — SCHD") == "TRIM"
    assert ds.infer_stance_from_text("Advisory RE_ENTER — ADBE") == "RE_ENTER"
    assert ds.infer_stance_from_text("Defense income — XLI") is None


def test_stance_for_symbol_reads_label_when_verdict_null():
    queue = {"items": [
        {"symbol": "SCHD", "verdict": None, "directive_label": "Advisory TRIM — SCHD",
         "source": "advisory"},
        {"symbol": "SCHD", "verdict": None, "directive_label": "Defense income — SCHD",
         "source": "defense"},
    ]}
    assert ds.stance_for_symbol("SCHD", queue) == "TRIM"
    # capital plan wiring
    assert cp.stance_for("SCHD", queue) == "TRIM"


def test_no_hold_trim_contradiction_in_decisions():
    rows = [
        {"symbol": "SCHD", "cio_stance": "HOLD", "why_now": "Advisory TRIM — SCHD",
         "current_value_usd": 100_000.0, "current_weight_pct": 10.0,
         "recommended_delta_usd": 0.0, "risk": "concentration > cap", "account": "ira"},
        {"symbol": "SCHD", "cio_stance": "HOLD", "why_now": "Advisory TRIM — SCHD",
         "current_value_usd": 20_000.0, "current_weight_pct": 2.0,
         "recommended_delta_usd": 0.0, "risk": "within single-name cap", "account": "taxable"},
        {"symbol": "V", "cio_stance": "HOLD", "why_now": "Advisory TRIM — V",
         "current_value_usd": 50_000.0, "current_weight_pct": 5.0,
         "recommended_delta_usd": 0.0, "risk": "within single-name cap", "account": "ira"},
        {"symbol": "V", "cio_stance": "HOLD", "why_now": "Advisory TRIM — V",
         "current_value_usd": 40_000.0, "current_weight_pct": 4.0,
         "recommended_delta_usd": 0.0, "risk": "within single-name cap", "account": "taxable"},
    ]
    dec = ds.sanitize_decisions_now(rows, portfolio_value=1_000_000.0, limit=8)
    by = {d["symbol"]: d for d in dec}
    assert "SCHD" in by and "V" in by
    # Aggregated — one row each
    assert by["SCHD"]["current_value_usd"] == 120_000.0
    assert by["V"]["current_value_usd"] == 90_000.0
    assert by["SCHD"]["account_count"] == 2
    # Stance is Trim, not Hold
    assert by["SCHD"]["stance"] == "Trim"
    assert by["SCHD"]["stance_code"] == "TRIM"
    assert by["V"]["stance_code"] == "TRIM"
    # No duplicate symbols
    assert len(dec) == len({d["symbol"] for d in dec})


def test_pseudo_sector_iwm_spy_rejected():
    assert ds.is_pseudo_sector("Iwm−Spy") is True
    assert ds.is_pseudo_sector("IWM-SPY") is True
    assert ds.is_pseudo_sector("Spy/Qqq") is True
    assert ds.is_pseudo_sector("Technology") is False
    assert so.canonical_sector("Iwm−Spy") == ""
    assert so.canonical_sector("IWM-SPY") == ""
    assert so.normalize_sector_row({
        "sector": "Iwm−Spy", "state": "IMPROVING", "rs20": 1, "slope": 1,
    }) is None


def test_filter_sector_opportunities_drops_pseudo_and_professionalizes():
    sectors = [
        {"sector": "Technology", "state": "LEADING", "opportunity": True,
         "recommendation": "STAGED_DEPLOYMENT", "current_exposure_pct": 7.4},
        {"sector": "Iwm−Spy", "state": "IMPROVING", "opportunity": True,
         "recommendation": "RESEARCH_FIRST"},
        {"sector": "Energy", "state": "LEADING", "opportunity": True,
         "recommendation": "RESEARCH_FIRST"},
    ]
    clean = ds.filter_sector_opportunities(sectors)
    names = [c["sector"] for c in clean]
    assert "Iwm−Spy" not in names
    assert "Technology" in names and "Energy" in names
    tech = next(c for c in clean if c["sector"] == "Technology")
    assert tech["recommendation"] == "Staged deployment"
    assert tech["recommendation_code"] == "STAGED_DEPLOYMENT"


def test_you_ticker_requires_name():
    bad = ds.symbol_identity_status("YOU")
    assert bad["ok"] is False
    assert bad["reason"] == "ambiguous_ticker_unproven"
    good = ds.symbol_identity_status("YOU", name="Clear Secure Inc")
    assert good["ok"] is True


def test_cusip_requires_name():
    bad = ds.symbol_identity_status("12507E201")
    assert bad["ok"] is False
    good = ds.symbol_identity_status("12507E201", name="Some Fund")
    assert good["ok"] is True


def test_allocation_usd_to_weight():
    alloc = {"Cash & Equivalents": 578107.5, "Equities": 704326.01, "Other": 0.0}
    assert ds.looks_like_dollar_allocation(alloc) is True
    w = ds.allocation_weights_from_usd(alloc)
    assert abs(w["Cash & Equivalents"] + w["Equities"] + w["Other"] - 100.0) < 0.05
    assert w["Cash & Equivalents"] == round(578107.5 / (578107.5 + 704326.01) * 100, 2)
    # Never 578107%
    assert w["Cash & Equivalents"] < 100.0


def test_professional_labels():
    assert ds.professional_label("STAGED_DEPLOYMENT") == "Staged deployment"
    assert ds.professional_label("RESEARCH_FIRST") == "Research first"
    assert ds.professional_stance("TRIM") == "Trim"
    assert ds.professional_stance("RE_ENTER") == "Re-enter"


def test_build_position_decisions_aggregates_and_trims():
    queue = {"items": [
        {"symbol": "V", "verdict": None, "directive_label": "Advisory TRIM — V",
         "source": "advisory"},
    ]}
    pv = 500_000.0
    positions = [
        cp.normalize_position(
            {"symbol": "V", "market_value": 40_000.0, "account": "schwab_rollover_ira"}, pv),
        cp.normalize_position(
            {"symbol": "V", "market_value": 30_000.0, "account": "schwab_taxable"}, pv),
        cp.normalize_position(
            {"symbol": "NVDA", "market_value": 60_000.0, "account": "schwab_taxable"}, pv),
    ]
    rows = cp.build_position_decisions(
        positions, queue=queue, portfolio_value=pv,
    )
    by = {r["symbol"]: r for r in rows}
    assert "V" in by
    # One aggregated V row
    assert sum(1 for r in rows if r["symbol"] == "V") == 1
    assert by["V"]["cio_stance"] == "TRIM" or by["V"].get("stance_code") == "TRIM"
    assert by["V"]["current_value_usd"] == 70_000.0
    # Trim delta ≈ -10% of 70k (aggregated)
    assert by["V"]["recommended_delta_usd"] == -7_000.0
