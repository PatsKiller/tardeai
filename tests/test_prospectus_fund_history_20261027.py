"""Prospectus fund block and my-history reconciliation (operator review of a fund prospectus, 2026-10-27).

Synthetic tickers (ZZ*), accounts and amounts only (public repo); no DB, no network.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import etf_profile, my_history  # noqa: E402
from scripts.lib.prospectus.inputs import Bundle  # noqa: E402

NOW = datetime(2026, 10, 27, 2, tzinfo=timezone.utc)


def test_fifo_matches_accounts_by_canonical_key(monkeypatch):
    # the journal names the account with its _ira suffix; the position store uses the short alias
    monkeypatch.setattr(my_history, "_acct_key", lambda raw: str(raw or "").replace("_ira", ""))
    fifo = my_history.fifo_open_lots([{"trade_date": "2026-10-26", "action": "Buy", "quantity": 40, "price": 35.0,
                                        "account": "fixture_roth_ira"}])
    assert sum(l[0] for l in fifo[my_history._acct_key("fixture_roth")]["lots"]) == 40


def test_trip_counts_as_stopped_out_when_a_broker_stop_fill_is_dated_on_its_exit():
    from test_prospectus_my_history_20261026 import FakeHistoryReader  # noqa: PLC0415
    b = Bundle(symbol="ZZMH", scope="holding", name="ZZMH")
    reader = FakeHistoryReader()
    exit_day = reader.trips("ZZMH")[1]["close_date"]   # the losing trip, sold at 55.0
    reader.trips = lambda sym, _t=reader.trips("ZZMH"): [dict(t, journal=None, journaled=False) for t in _t]
    reader.stop_fills = lambda sym: [{"account": "fixture_brokerage", "stop_price": 55.0, "status": "filled",
                                      "captured_at": "2026-10-26T20:00:00"}]
    block = my_history.build(reader, b, holding={"shares": 40}, now=NOW)
    trip = next(t for t in block["trips"] if t["exit_date"] == exit_day)
    assert trip["stopped_out"] is True
    rate = next(s for s in block["lessons"]["stats"] if s["id"] == "stop_rate")
    assert rate["value"] > 0


def test_distribution_growth_annualized():
    hist = [{"ex_date": f"{y}-{m:02d}-15", "amount": a} for y, a in ((2023, 0.20), (2024, 0.22), (2025, 0.24), (2026, 0.26))
            for m in (3, 6, 9, 12) if date(y, m, 15) <= date(2026, 9, 30)]
    g = etf_profile.distribution_growth(hist)
    assert g and g["years"] == 2 and g["pct"] > 0
    assert etf_profile.distribution_growth(hist[-3:]) is None


class _Src:
    def __init__(self):
        self.calls = 0

    def holdings(self):
        self.calls += 1
        return {"ZZF": {}, "ZZA": {}, "ZZG": {}}

    def lookthrough(self, sym):
        return {"fund": {"top_holdings": [{"ticker": "ZZB", "pct": 5.0}]}} if sym == "ZZG" else {}


def test_book_overlap_direct_and_via_other_funds():
    rows = [{"name": "ZZA", "weight_pct": 6.0}, {"name": "ZZB", "weight_pct": 4.0}, {"name": "ZZC", "weight_pct": 10.0}]
    src = _Src()
    ov = etf_profile.book_overlap(src, "ZZF", rows)
    assert ov["overlap_weight_pct"] == 50.0
    assert {(h["name"], h["direct"], tuple(h["via_funds"])) for h in ov["names"]} == {("ZZA", True, ()), ("ZZB", False, ("ZZG",))}
    etf_profile.book_overlap(src, "ZZF", rows)
    assert src.calls == 1  # one holdings read per sources object
