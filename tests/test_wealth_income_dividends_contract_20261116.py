"""/api/v2/dividends Income contract (portfolio audit 2026-11-16, F2/F3). Synthetic fixtures only.

F2: Income is one GET by contract, so the account names must travel with the legs: ``account_labels`` plus
``account_label_source`` (registry name vs a label only derived from the key). Never an account number.
F3: the calendar places months by observed ex-date months, not by frequency. A payer with no observed month is
``unplaced``; the twelve months sum to total − unplaced, up to one cent of rounding per placed month.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import api_v2  # noqa: E402

REGISTRY = {"aliases": {"syn_roth": "syn_roth_ira"}, "names": {"syn_roth_ira": {"name": "Synthetic Roth"}}}


def _calendar(months_by_symbol: dict, annual_by_symbol: dict) -> dict:
    payers, cal = [], {m: [] for m in range(1, 13)}
    unplaced = []
    for sym, annual in annual_by_symbol.items():
        months = months_by_symbol.get(sym) or []
        payers.append({"symbol": sym, "annual_income": annual, "monthly_amort": round(annual / 12, 2),
                       "frequency": "quarterly" if len(months) == 4 else None, "months": months, "qualified": None})
        if not months:
            unplaced.append({"symbol": sym, "annual_income": annual, "reason": "no observed or served ex-date month"})
            continue
        for m in months:
            cal[m].append(round(annual / len(months), 2))
    total = round(sum(annual_by_symbol.values()), 2)
    return {
        "has_data": True, "payers": payers, "total_annual": total,
        "monthly_summary": [{"month": m, "month_name": f"M{m}", "total": round(sum(v), 2)} for m, v in cal.items()],
        "monthly_summary_basis": "observed ex-date months", "monthly_average_basis": "total annual / 12",
        "unplaced": unplaced, "unplaced_annual": round(sum(u["annual_income"] for u in unplaced), 2),
        "monthly_average": round(total / 12, 2),
    }


@pytest.fixture()
def served(tmp_path, monkeypatch):
    def run(calendar: dict, holdings: list) -> dict:
        (tmp_path / "dividend_calendar.json").write_text(json.dumps(calendar))
        (tmp_path / "holdings.json").write_text(json.dumps({"holdings": holdings}))
        monkeypatch.setattr(api_v2, "STATE_DIR", tmp_path)
        monkeypatch.setattr(api_v2._acct_disp, "_load", lambda *a, **k: REGISTRY)
        return api_v2.dividends()
    return run


HOLDINGS = [
    {"symbol": "QZA", "account": "syn_roth", "market_value": 300.0, "quantity": 3},
    {"symbol": "QZA", "account": "syn_brokerage", "market_value": 100.0, "quantity": 1},
    {"symbol": "QZB", "account": "acct_12345", "market_value": 50.0, "quantity": 1},
]


def test_account_labels_and_source_travel_with_the_legs(served):
    out = served(_calendar({"QZA": [3, 6, 9, 12]}, {"QZA": 40.0, "QZB": 10.0, "QZC": 7.0}), HOLDINGS)
    keys = {r.get("account") for r in out["payers"]}
    assert None in keys  # QZC has no holding leg: unassigned, never a guessed account
    assert out["account_labels"] == {
        "acct_12345": "Unlabelled account", "syn_brokerage": "Syn Brokerage", "syn_roth": "Synthetic Roth"}
    assert out["account_label_source"] == {
        "acct_12345": "unlabelled", "syn_brokerage": "derived", "syn_roth": "registry"}
    assert "_unassigned" not in out["account_labels"]
    assert not any(ch.isdigit() for v in out["account_labels"].values() for ch in v)


def test_unplaced_and_bases_pass_through_and_months_reconcile(served):
    cal = _calendar({"QZA": [3, 6, 9, 12], "QZB": [1, 4, 7, 10]}, {"QZA": 40.01, "QZB": 10.0, "QZC": 7.0})
    out = served(cal, HOLDINGS)
    assert out["unplaced_annual"] == 7.0
    assert [u["symbol"] for u in out["unplaced"]] == ["QZC"]
    assert out["monthly_summary_basis"] == "observed ex-date months"
    assert out["monthly_average_basis"] == "total annual / 12"
    placed = round(sum(m["total"] for m in out["monthly_summary"]), 2)
    placed_months = sum(len(p["months"]) for p in out["payers_portfolio"] if p["months"])
    # 40.01 / 4 = 10.0025 -> 10.00 per month: the months under-sum by 0.01, within one cent per placed month.
    assert abs(placed - (out["total_annual"] - out["unplaced_annual"])) <= 0.01 * placed_months + 1e-9
    assert placed != round(out["total_annual"] - out["unplaced_annual"], 2)  # the rounding gap is real, not hidden
    # Every expanded leg keeps the payer's observed months, so the page can split placed vs unplaced per leg.
    assert all("months" in r for r in out["payers"])
    # Legs sum back to the portfolio annual total up to one cent of per-leg rounding per leg.
    legs = round(sum(r["annual_income"] for r in out["payers"]), 2)
    assert abs(legs - out["total_annual"]) <= 0.01 * len(out["payers"])


def test_an_older_calendar_serves_none_not_a_guess(served):
    cal = _calendar({"QZA": [3, 6, 9, 12]}, {"QZA": 40.0})
    for k in ("unplaced", "unplaced_annual", "monthly_summary_basis", "monthly_average_basis"):
        cal.pop(k)
    out = served(cal, HOLDINGS)
    assert out["unplaced"] is None and out["unplaced_annual"] is None
    assert out["monthly_summary_basis"] is None and out["monthly_average_basis"] is None
