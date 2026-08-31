"""WAVE B4+B5 — per-block as_of + provenance at display.

B4: OP.cash / home.cash carry their own evidence clock. Block age = oldest
contributing cash balance, never product/home composition time. Dollar amounts
must not change.

B5: Constant portfolio_implication is not rendered as situation guidance.
Briefs that no model produced must not assert model provenance. writer = author.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.cio_command_center import (
    _stamp_cash_letter_provenance,
    build_office_home,
)
from scripts.lib.cio_operator_product import (
    _cash_block_as_of,
    _holdings_sections,
    _temperament_display,
    build_operator_product,
)
from scripts.lib.cio_operator_renderers import (
    PROVENANCE_FOOTER,
    cash_lines,
    command_center_view,
    eod_text,
    morning_text,
)


# Five cash rows spanning 23 days — same shape as the live 2026-08-30 book.
_CASH_ROWS = [
    {"symbol": "CASH", "is_cash": True, "market_value": 500.0,
     "account": "moomoo_taxable_live", "as_of": "2026-08-03",
     "updated_at": "2026-08-14T21:25:43+00:00"},
    {"symbol": "CASH", "is_cash": True, "market_value": 5000.0,
     "account": "alpaca_taxable_live", "as_of": "2026-08-04",
     "updated_at": "2026-08-14T21:25:43+00:00"},
    {"symbol": "CASH", "is_cash": True, "market_value": 37894.31,
     "account": "schwab_taxable", "as_of": "2026-08-26",
     "updated_at": "2026-08-26T14:22:17+00:00"},
    {"symbol": "CASH", "is_cash": True, "market_value": 1472.71,
     "account": "schwab_roth", "as_of": "2026-08-26",
     "updated_at": "2026-08-26T14:22:17+00:00"},
    {"symbol": "CASH", "is_cash": True, "market_value": 585917.80,
     "account": "schwab_rollover_ira", "as_of": "2026-08-26",
     "updated_at": "2026-08-26T14:22:18+00:00"},
]
_EQUITY = {"symbol": "NVDA", "is_cash": False, "market_value": 10_000.0}
_DOC = {
    "as_of": "2026-08-30",
    "generated_at": "2026-08-30 20:30:16 ET",
    "holdings": _CASH_ROWS + [_EQUITY],
}
_EXPECTED_CASH_USD = round(sum(r["market_value"] for r in _CASH_ROWS), 2)


def _write_holdings(root: Path, doc: dict) -> None:
    path = root / "data" / "portfolios" / "state" / "holdings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _write_minimal_brief(root: Path, *, as_of: str = "2026-08-31T03:00:00+00:00") -> None:
    """Minimal cio.product.current so build_operator_product is AVAILABLE."""
    from scripts.lib.canonical_store_registry import resolve_store
    loc = resolve_store("cio.product.current", root=root)
    path = Path(loc["primary_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "CIOInvestmentProduct@v1",
        "available": True,
        "as_of": as_of,
        "product_id": "test_brief",
        "decision_id": "test_brief",
        "final_position": "HOLD",
        "summary": {"headline": "[T] Nothing requires action today."},
        "recommendations": [],
        "temperament": {
            "title": "RISK OFF — SELECTIVE RISK",
            "regime": "risk off",
            "regime_as_of": "2026-08-28",
            "cash": _EXPECTED_CASH_USD,
            "cash_pct": 49.0,
            "portfolio_implication": (
                "Preserve quality growth exposure, keep cash for dislocations, "
                "and do not force lower-quality replacements. Re-entries need "
                "candidate-specific governed verdicts — desk zone marks are not authorization."
            ),
            "portfolio_implication_class": "T",
            "narrative": "Temperament RISK OFF.",
        },
        "reentry_book": {"count": 0, "counts": {}, "surface": "A",
                         "scope": "former holdings vs exit trigger"},
    }), encoding="utf-8")


# ── B4 — cash block age ─────────────────────────────────────────────────────

def test_cash_block_as_of_is_the_oldest_contributing_balance():
    ev = _cash_block_as_of(_CASH_ROWS, _DOC)
    assert ev["as_of"] == "2026-08-03"
    assert ev["oldest_row_as_of"] == "2026-08-03"
    assert ev["newest_row_as_of"] == "2026-08-26"
    assert ev["mixed_ages"] is True
    assert ev["unstamped"] is False
    # Never the document / composition stamp.
    assert ev["as_of"] != _DOC["as_of"]


def test_holdings_sections_stamps_cash_without_changing_dollars(tmp_path: Path):
    _write_holdings(tmp_path, _DOC)
    sections = _holdings_sections(tmp_path)
    cash = sections["cash"]
    assert cash["cash_usd"] == _EXPECTED_CASH_USD
    assert cash["cash_n"] == 5
    assert cash["as_of"] == "2026-08-03"
    assert cash["cash_as_of"]["as_of"] == "2026-08-03"
    assert cash["class"] == "D"
    assert cash["provenance_class"] == "D"
    # Portfolio keeps its own doc stamp; cash does not inherit it.
    assert sections["portfolio"]["as_of"] == "2026-08-30"
    assert cash["as_of"] != sections["portfolio"]["as_of"]


def test_operator_product_cash_has_own_as_of_not_composition(tmp_path: Path):
    _write_holdings(tmp_path, _DOC)
    _write_minimal_brief(tmp_path, as_of="2026-08-31T12:00:00+00:00")
    product = build_operator_product(root=tmp_path, persist=False)
    assert product.get("available") is True
    cash = product["cash"]
    assert cash["cash_usd"] == _EXPECTED_CASH_USD  # dollars unchanged
    assert cash["as_of"] == "2026-08-03"
    assert product["as_of"] == "2026-08-31T12:00:00+00:00"
    assert cash["as_of"] != product["as_of"]
    assert product["block_as_of"]["cash"] == "2026-08-03"
    assert product["block_as_of"]["product_composition"] == product["as_of"]


def test_morning_and_eod_print_cash_age_and_honest_footer(tmp_path: Path):
    _write_holdings(tmp_path, _DOC)
    _write_minimal_brief(tmp_path)
    product = build_operator_product(root=tmp_path, persist=False)
    morning = morning_text(product)
    eod = eod_text(product)
    assert "as_of 2026-08-03" in morning
    assert "as_of 2026-08-03" in eod
    assert "no model produced this brief" in morning
    assert "no model produced this brief" in eod
    assert PROVENANCE_FOOTER.split("·")[0].strip() in morning
    # Footers must not claim a model authored the brief.
    assert "DeepSeek" not in morning
    assert "[M]" not in morning
    assert "model-assisted" not in morning.lower()


def test_cash_lines_never_pick_composition_time_as_age():
    product = {
        "as_of": "2026-08-31T12:00:00+00:00",
        "cash": {
            "cash_usd": 100.0,
            "as_of": "2026-08-03",
            "cash_as_of": {"as_of": "2026-08-03"},
        },
        "temperament": {"cash": 100.0, "cash_pct": 10.0},
    }
    lines = cash_lines(product)
    joined = "\n".join(lines)
    assert "2026-08-03" in joined
    assert "2026-08-31" not in joined


# ── B5 — provenance / guidance / writer=author ───────────────────────────────

def test_constant_portfolio_implication_is_not_guidance():
    temp = _temperament_display(
        {
            "portfolio_implication": "Preserve quality growth exposure…",
            "portfolio_implication_class": "T",
            "cash": 100.0,
        },
        {"as_of": "2026-08-03", "cash_as_of": {"as_of": "2026-08-03"}},
    )
    assert temp["portfolio_implication"] is None
    assert temp["portfolio_implication_is_guidance"] is False
    assert temp["standing_policy_template"].startswith("Preserve")
    assert temp["cash_as_of"]["as_of"] == "2026-08-03"


def test_command_center_view_redacts_implication_and_denies_model(tmp_path: Path):
    _write_holdings(tmp_path, _DOC)
    _write_minimal_brief(tmp_path)
    product = build_operator_product(root=tmp_path, persist=False)
    view = command_center_view(product)
    temp = view["temperament"]
    assert temp.get("portfolio_implication") in (None, "")
    assert temp.get("portfolio_implication_is_guidance") is False
    assert temp.get("standing_policy_template")
    assert view["model_produced"] is False
    assert view["provenance_footer"]["model_produced"] is False
    assert view["cash"]["as_of"] == "2026-08-03"
    assert view["cash"]["cash_usd"] == _EXPECTED_CASH_USD


def test_home_cash_inherits_op_stamp_and_home_denies_model(tmp_path: Path):
    _write_holdings(tmp_path, _DOC)
    _write_minimal_brief(tmp_path)
    product = build_operator_product(root=tmp_path, persist=False)
    home = build_office_home(
        capital_plan={
            "cash_total_usd": _EXPECTED_CASH_USD,
            "cash_as_of": product["cash"]["cash_as_of"],
        },
        operator_product=product,
    )
    assert home["cash"]["as_of"] == "2026-08-03"
    assert home["cash"]["cash_usd"] == _EXPECTED_CASH_USD
    assert home["model_produced"] is False
    assert home["provenance_footer"]["model_produced"] is False
    assert home["provenance_footer"]["writer_means"] == "author"
    assert home["temperament"].get("portfolio_implication") in (None, "")
    assert home["block_as_of"]["cash"] == "2026-08-03"
    # Composition clocks move; cash age must not follow them.
    assert home["as_of"] != home["cash"]["as_of"]


def test_cash_letter_as_of_uses_evidence_not_composition_and_writer_is_author():
    letter = {
        "schema": "CashSleeveLetter@v1",
        "cash_usd": _EXPECTED_CASH_USD,
        "what": "Cash sleeve standing.",
        "writer": "migration:deterministic",
        "as_of": "2026-08-31T03:35:57+00:00",
        "from_record": True,
    }
    stamped = _stamp_cash_letter_provenance(
        letter,
        capital_plan={"cash_as_of": {"as_of": "2026-08-03", "oldest_row_as_of": "2026-08-03"}},
    )
    assert stamped["cash_usd"] == _EXPECTED_CASH_USD  # dollars untouched
    assert stamped["as_of"] == "2026-08-03"
    assert stamped["composition_as_of"] == "2026-08-31T03:35:57+00:00"
    assert stamped["as_of_source"] == "cash_evidence_oldest_balance"
    assert stamped["author"] == "migration:deterministic"
    assert stamped["writer"] == stamped["author"]
    assert stamped["model_produced"] is False


def test_labelling_fix_does_not_change_dollar_amounts(tmp_path: Path):
    """Rails: if a total is wrong, report it — do not 'fix' by changing numbers."""
    _write_holdings(tmp_path, _DOC)
    _write_minimal_brief(tmp_path)
    product = build_operator_product(root=tmp_path, persist=False)
    assert product["cash"]["cash_usd"] == _EXPECTED_CASH_USD
    # Temperament cash (totals writer) is a different quantity; we still must
    # not rewrite the position-row sum.
    assert product["cash"]["cash_n"] == 5
