"""LQ-20261107-1611 (was LQ-1391): one portfolio total and one position count across Home header / Book /
All accounts.

Measured on the live page 2026-11-08/09: the header said $1,244,915.17 (the data-broker projection, Finviz
re-marks, Friday regular-session close on a weekend), the Book and the All-accounts row said $1,248,686.32
(the store's own `portfolio_totals.total_value`, broker marks at the 23:00 sync), and the Book additionally
re-summed its own rows. Two integers stood for "positions": 12 (non-cash over $100) and 34 (every row,
cash included).

`scripts/lib/portfolio_total_contract.py` decides the one number. These tests pin the decision, the
degradations, and the refusal to publish a zero:

* the store's `portfolio_totals.total_value` is published when it agrees with the row sum;
* when it does not, the row sum is published, the basis says so, and the finding alerts — a header must
  always equal the rows it shows;
* an unreadable/absent store publishes `value: None` with a finding, never $0;
* the count is one named scope with a printed definition, and every other population is named beside it;
* every other number the page could show is an `alternative` with its delta and why — never the total.

Synthetic documents only; no live store, database or network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.portfolio_total_contract import (
    CONTRACT_VERSION,
    POSITION_SCOPE,
    build_portfolio_total,
    is_cash_row,
    load_portfolio_total,
    position_scopes,
    rows_total,
)

ROOT = Path(__file__).resolve().parents[1]


def row(symbol: str, mv: float, account: str = "schwab_taxable", **kw) -> dict:
    return {"account": account, "symbol": symbol, "market_value": mv, "shares": 1, **kw}


def document(rows: list[dict], total: float | None = None, *, cash: float = 9_000.0,
             broker_total: float | None = None, as_of: str = "2026-11-09T12:15:00+00:00") -> dict:
    totals: dict = {"as_of": as_of, "total_cash": cash}
    if total is not None:
        totals["total_value"] = total
    if broker_total is not None:
        totals["broker_market_value_total"] = broker_total
    return {"document_source": "positions_current", "holdings": rows, "portfolio_totals": totals}


ROWS = [
    row("SCHD", 40_000.0),
    row("V", 30_000.0),
    row("SPCX", 82_662.0),
    row("TINY", 99.0),                      # below the $100 line: not a position
    row("CASH", 500_000.0, is_cash=True),
    row("SPAXX", 400_000.0),                # cash by symbol, no flag
]
ROW_SUM = round(sum(r["market_value"] for r in ROWS), 2)  # 552,761.00


# ── one total ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_store_total_is_published_when_it_equals_the_rows():
    doc = document(ROWS, ROW_SUM)
    pt = build_portfolio_total(doc)
    assert pt["contract_version"] == CONTRACT_VERSION
    assert pt["value"] == ROW_SUM
    assert pt["basis"] == "portfolio_totals.total_value"
    assert "portfolio_totals.total_value" in pt["basis_label"]
    assert pt["agree"] is True
    assert pt["findings"] == []
    assert pt["as_of"] == "2026-11-09T12:15:00+00:00"


def test_a_store_field_that_disagrees_with_its_rows_never_ships_as_the_total():
    """The Friday defect in miniature: a total on a different basis than the rows beneath it."""
    doc = document(ROWS, ROW_SUM - 3_771.15)
    pt = build_portfolio_total(doc)
    assert pt["value"] == ROW_SUM, "the published total must equal the rows the page shows"
    assert pt["basis"] == "holdings[].market_value"
    assert pt["basis_label"].startswith("sum of the holdings rows shown")
    assert pt["agree"] is False
    drift = [f for f in pt["findings"] if f["code"] == "TOTAL_FIELD_DRIFT"]
    assert drift and drift[0]["alert"] is True
    assert drift[0]["evidence"]["delta"] == pytest.approx(-3_771.15, abs=0.01)


def test_one_dollar_within_tolerance_is_not_drift():
    pt = build_portfolio_total(document(ROWS, ROW_SUM + 0.5))
    assert pt["value"] == ROW_SUM + 0.5 and pt["basis"] == "portfolio_totals.total_value" and pt["agree"]


def test_an_absent_total_field_falls_back_to_the_row_sum_and_alerts():
    pt = build_portfolio_total(document(ROWS, None))
    assert pt["value"] == ROW_SUM
    assert pt["basis"] == "holdings[].market_value"
    assert [f["code"] for f in pt["findings"]] == ["TOTAL_FIELD_MISSING"]
    assert pt["findings"][0]["alert"] is True


def test_an_empty_store_publishes_none_never_zero():
    pt = build_portfolio_total(document([], 0.0))
    assert pt["value"] is None and pt["basis"] is None
    assert [f["code"] for f in pt["findings"]] == ["HOLDINGS_EMPTY"]
    assert pt["agree"] is False


def test_a_malformed_document_never_raises():
    for doc in (None, {}, {"holdings": "nope"}, {"holdings": [None, 3], "portfolio_totals": 7}):
        pt = build_portfolio_total(doc)  # type: ignore[arg-type] -- the malformed shapes are the point of this test
        assert pt["value"] is None


def test_one_unusable_row_makes_the_row_sum_unknown_not_wrong():
    rows = [row("SCHD", 40_000.0), {"account": "a", "symbol": "BAD", "market_value": "abc"}]
    assert rows_total(rows) is None
    pt = build_portfolio_total(document(rows, 40_000.0))
    assert pt["value"] == 40_000.0 and pt["basis"] == "portfolio_totals.total_value"
    assert pt["row_sum"] is None and pt["row_sum_unusable"] is True
    assert pt["findings"] == [], "the store field stands; the receipt records that it could not be confirmed"


# ── one position count ────────────────────────────────────────────────────────────────────────────────────────

def test_the_position_count_is_one_named_scope_with_its_definition():
    pt = build_portfolio_total(document(ROWS, ROW_SUM))
    assert pt["position_count"] == 3, "SCHD, V, SPCX — not TINY (<$100), not the two cash rows"
    assert pt["position_scope"] == POSITION_SCOPE == "holdings.non_cash_over_100"
    assert pt["position_scope_definition"]
    assert "above $100" in pt["position_scope_definition"]


def test_every_other_population_is_named_beside_it():
    counts = build_portfolio_total(document(ROWS, ROW_SUM))["position_counts"]
    assert counts["scopes"] == {
        "holdings.non_cash_over_100": 3,
        "holdings.all_rows": 6,
        "holdings.non_cash": 4,
        "holdings.cash": 2,
    }
    assert counts["primary_scope"] == POSITION_SCOPE
    for scope in counts["scopes"]:
        assert counts["definitions"][scope], f"{scope} is published without a definition"


def test_a_split_row_is_one_position():
    rows = [row("SCHD", 20_000.0), row("SCHD", 21_000.0)]
    assert position_scopes(rows)["holdings.non_cash_over_100"] == 1


def test_cash_is_recognised_by_flag_or_symbol():
    assert is_cash_row({"symbol": "CASH"}) and is_cash_row({"symbol": "spaxx"})
    assert is_cash_row({"symbol": "X", "is_cash": True})
    assert not is_cash_row({"symbol": "SCHD"})


def test_an_extra_scope_from_another_store_is_carried_and_defined():
    pt = build_portfolio_total(document(ROWS, ROW_SUM), extra_scopes={"risk.risk_included": 5})
    assert pt["position_counts"]["scopes"]["risk.risk_included"] == 5
    assert pt["position_counts"]["definitions"]["risk.risk_included"] == "scope risk.risk_included"
    assert pt["position_count"] == 3, "an extra scope never moves the primary count"


# ── every alternative is named, none is the total ─────────────────────────────────────────────────────────────

def test_the_broker_marks_are_an_alternative_with_their_delta():
    pt = build_portfolio_total(document(ROWS, ROW_SUM, broker_total=ROW_SUM - 35.96))
    alt = next(a for a in pt["alternatives"] if a["name"] == "broker_marks")
    assert alt["value"] == ROW_SUM - 35.96
    assert alt["delta"] == pytest.approx(35.96, abs=0.01)
    assert "repricer" in alt["why"]
    assert pt["value"] == ROW_SUM, "the broker total is evidence, never the published total"


def test_the_projection_is_an_alternative_and_its_disagreement_does_not_fail_the_total():
    """The Friday number: header 1,244,915 vs book 1,248,686. The book is published; the header's number
    is the alternative, and the mismatch is a non-alerting observation (it re-renders on the next pass)."""
    doc = document(ROWS, ROW_SUM)
    pt = build_portfolio_total(doc, snapshot_totals={"total_value": ROW_SUM - 3_771.15})
    assert pt["value"] == ROW_SUM
    alt = next(a for a in pt["alternatives"] if a["name"] == "broker_projection")
    assert alt["delta"] == pytest.approx(3_771.15, abs=0.01)
    assert "cio_truth" in alt["why"]
    proj = [f for f in pt["findings"] if f["code"] == "PROJECTION_DISAGREES"]
    assert proj and proj[0]["alert"] is False
    assert pt["agree"] is True, "only a total-vs-rows disagreement fails the contract"


def test_cash_is_published_with_its_own_basis():
    pt = build_portfolio_total(document(ROWS, ROW_SUM, cash=951_096.24))
    assert pt["cash"] == {"value": 951_096.24, "basis": "portfolio_totals.total_cash"}


# ── the loader: a missing store is a finding, not a crash and not a zero ───────────────────────────────────────

def test_load_portfolio_total_reads_the_store(tmp_path: Path):
    (tmp_path / "holdings.json").write_text(json.dumps(document(ROWS, ROW_SUM)), encoding="utf-8")  # nosemgrep: tq-py-nonatomic-store-write -- a tmp_path fixture, not a store; nothing outside this test reads it
    pt = load_portfolio_total(tmp_path)
    assert pt["value"] == ROW_SUM and pt["position_count"] == 3


def test_load_portfolio_total_on_a_missing_store_alerts_and_publishes_none(tmp_path: Path):
    pt = load_portfolio_total(tmp_path)
    assert pt["value"] is None and pt["agree"] is False
    assert [f["code"] for f in pt["findings"]] == ["HOLDINGS_EMPTY", "HOLDINGS_UNREADABLE"]


def test_load_portfolio_total_on_an_unparseable_store_alerts(tmp_path: Path):
    (tmp_path / "holdings.json").write_text("{not json", encoding="utf-8")  # nosemgrep: tq-py-nonatomic-store-write -- a tmp_path fixture, deliberately unparseable, not a store
    pt = load_portfolio_total(tmp_path)
    assert pt["value"] is None
    assert [f["code"] for f in pt["findings"]][-1] == "HOLDINGS_UNREADABLE"
