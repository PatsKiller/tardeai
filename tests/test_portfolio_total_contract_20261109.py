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
    assert pt["position_count"] == 4, "SCHD, V, SPCX and the $99 TINY lot — held, priced; not the two cash rows"
    assert pt["position_scope"] == POSITION_SCOPE == "holdings.held"
    assert pt["position_scope_definition"]
    assert "quantity" in pt["position_scope_definition"] and "priced" in pt["position_scope_definition"]
    assert pt["position_summary"] == "4 positions · 1 under $100"


def test_every_other_population_is_named_beside_it():
    counts = build_portfolio_total(document(ROWS, ROW_SUM))["position_counts"]
    assert counts["scopes"] == {
        "holdings.held": 4,
        "holdings.non_cash_over_100": 3,
        "holdings.held_under_100": 1,
        "holdings.unpriced": 0,
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
    assert pt["position_count"] == 4, "an extra scope never moves the primary count"


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
    assert pt["value"] == ROW_SUM and pt["position_count"] == 4


def test_load_portfolio_total_on_a_missing_store_alerts_and_publishes_none(tmp_path: Path):
    pt = load_portfolio_total(tmp_path)
    assert pt["value"] is None and pt["agree"] is False
    assert [f["code"] for f in pt["findings"]] == ["HOLDINGS_EMPTY", "HOLDINGS_UNREADABLE"]


def test_load_portfolio_total_on_an_unparseable_store_alerts(tmp_path: Path):
    (tmp_path / "holdings.json").write_text("{not json", encoding="utf-8")  # nosemgrep: tq-py-nonatomic-store-write -- a tmp_path fixture, deliberately unparseable, not a store
    pt = load_portfolio_total(tmp_path)
    assert pt["value"] is None
    assert [f["code"] for f in pt["findings"]][-1] == "HOLDINGS_UNREADABLE"


# ── F1 / F3 (cc-opus-1 takeover): one read per page, and a count that does not flicker ────────────────────────
#
# F1: the Home accounts card summed to $7,330 less than its own All-accounts row, because the per-account
# values came from a 07:41 performance snapshot and the All row from the live store. The contract now
# publishes the per-account values from the same rows as the total, so one payload can draw the whole card.
# F3: the headline count was "non-cash over $100"; a $97 dust lot ticking to $101 moved it (12 ↔ 13).

def _acct_rows() -> list[dict]:
    return [
        row("SPCX", 800_000.0, "schwab_rollover_ira"),
        row("CASH", 300_000.0, "schwab_rollover_ira", is_cash=True),
        row("V", 211.58, "schwab_roth"),
        row("SPAXX", 56_935.42, "schwab_roth"),
        row("RTX", 97.14, "schwab_taxable"),
        row("SRNE", 0.30, "schwab_taxable"),
        row("543354104", 0.0, "schwab_taxable"),       # unpriced CUSIP lot, quantity held
        row("T", 5_000.0, "schwab_taxable"),
    ]


def test_account_values_come_from_the_same_rows_and_sum_to_the_total():
    rows = _acct_rows()
    total = round(sum(r["market_value"] for r in rows), 2)
    pt = build_portfolio_total(document(rows, total))
    by = pt["by_account"]
    assert set(by) == {"schwab_rollover_ira", "schwab_roth", "schwab_taxable"}
    assert by["schwab_rollover_ira"]["value"] == 1_100_000.0
    assert by["schwab_roth"]["cash"] == 56_935.42
    assert round(sum(a["value"] for a in by.values()), 2) == pytest.approx(pt["value"], abs=pt["tolerance_usd"])
    assert pt["by_account_sum"] == pytest.approx(pt["value"], abs=1.0)


def test_an_unusable_row_makes_only_its_account_unknown():
    rows = _acct_rows() + [{"account": "schwab_roth", "symbol": "BAD", "market_value": "abc", "shares": 1}]
    by = build_portfolio_total(document(rows, 1_162_244.44))["by_account"]
    assert by["schwab_roth"]["value"] is None
    assert by["schwab_rollover_ira"]["value"] == 1_100_000.0


def test_the_headline_count_does_not_move_when_a_dust_lot_crosses_100():
    before = build_portfolio_total(document(_acct_rows(), None))
    moved = [dict(r, market_value=101.02) if r["symbol"] == "RTX" else r for r in _acct_rows()]
    after = build_portfolio_total(document(moved, None))
    assert before["position_count"] == after["position_count"] == 5, "SPCX, V, RTX, SRNE, T"
    s0, s1 = before["position_counts"]["scopes"], after["position_counts"]["scopes"]
    assert (s0["holdings.non_cash_over_100"], s1["holdings.non_cash_over_100"]) == (3, 4), \
        "the $100 scope still moves — it is published by name, never as the headline"


def test_unpriced_lots_are_excluded_from_the_count_and_named():
    pt = build_portfolio_total(document(_acct_rows(), None))
    scopes = pt["position_counts"]["scopes"]
    assert pt["position_scope"] == "holdings.held"
    assert scopes["holdings.unpriced"] == 1
    assert scopes["holdings.held_under_100"] == 2, "RTX and SRNE; V at $211.58 is over the line"
    assert "quantity" in pt["position_scope_definition"]
    assert pt["position_summary"] == "5 positions · 2 under $100 · 1 unpriced lot excluded"


# ── part 2: the publisher. /api/v2/overview's financial facts come from cio_truth.overview_payload, so the
#    contract is built there, from the same repriced rows as portfolio_value and today_by_account (one read). ─

def test_the_overview_payload_publishes_the_contract_from_its_own_rows():
    from datetime import datetime, timezone

    from scripts.lib import cio_truth as truth

    now = datetime(2026, 1, 12, 15, 0, tzinfo=timezone.utc)
    h = {"last_repriced": "2026-01-12 10:00:00 ET", "generated_at": "2026-01-12 10:00:00 ET",
         "reprice_source": "finviz_live",
         "portfolio_totals": {"total_value": 9_999.0, "total_cash": 300.0},  # a stale stored field
         "holdings": [row("ZZAA", 600.0, "schwab_rollover_ira", shares=10, price=60),
                      row("ZZBB", 97.0, "schwab_roth", shares=1, price=97),
                      row("000000ZZ9", 0.0, "schwab_taxable", shares=300, price=0),
                      row("CASH", 300.0, "schwab_taxable", is_cash=True)]}
    p = truth.portfolio_for(h, now=now)
    doc = {"portfolio": p, "approvals": {"total": 0}, "paper": {},
           "regime": {"label": None, "vix": None, "vix_as_of": None}}
    out = truth.overview_payload({}, document=doc, now=now)
    pt = out["portfolio_total"]
    assert pt["value"] == out["portfolio_value"] == 997.0, "the contract total is the header, to the cent"
    assert pt["by_account_sum"] == out["portfolio_value"]
    assert set(pt["by_account"]) == set(out["today_by_account"]), "one account key space"
    assert pt["by_account"]["schwab_roth_ira"]["value"] == 97.0
    assert pt["position_count"] == 2 and pt["position_summary"] == "2 positions · 1 under $100 · 1 unpriced lot excluded"
    stored = [a for a in pt["alternatives"] if a["name"] == "stored_total"]
    assert stored and stored[0]["value"] == 9_999.0 and stored[0]["delta"] == round(997.0 - 9_999.0, 2)
