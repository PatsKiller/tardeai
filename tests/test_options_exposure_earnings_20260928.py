"""Reviewer findings 2026-09-28 (Options desk, Monday market-hours page):

1. The SPCX combined scenario reported +$8,951 at -30% -- the payoff of the two option ideas
   alone -- while the page said 400 SPCX shares were held (about -$17.6k at -30%), and it called
   a Nov-6 put and a Nov-20 spread one "at expiry" payoff. combined_exposure now reports
   options-only, shares and whole-position P/L per row, groups rows by expiration date, and lists
   shares by account.
2. earnings_blackout_check omitted debit_spread / long_put, so the alert's call spread was
   "qualified" while the long call beside it was blocked; and its one reason string said
   "inside 14d blackout" when the trigger was earnings inside the option's life.
Hermetic."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib.options_exposure import combined_exposure  # noqa: E402

SPOT = 146.47
CC1 = {"id": "cc1", "symbol": "SPCX", "strategy": "covered_call", "strike": 157.5, "premium": 5.05, "contracts": 1,
       "underlying_price": SPOT, "expiration": "2026-10-23", "account": "schwab_taxable", "economics": {"collateral": 0}}
CC2 = {"id": "cc2", "symbol": "SPCX", "strategy": "covered_call", "strike": 157.5, "premium": 5.05, "contracts": 3,
       "underlying_price": SPOT, "expiration": "2026-10-23", "account": "schwab_rollover_ira", "economics": {"collateral": 0}}
PUT = {"id": "pp", "symbol": "SPCX", "strategy": "protective_put", "strike": 140.0, "premium": 6.45, "contracts": 3,
       "underlying_price": SPOT, "expiration": "2026-11-06", "account": "schwab_rollover_ira", "economics": {"option_cost_total": 1935}}
SPR = {"id": "sp", "symbol": "SPCX", "strategy": "credit_spread", "short_strike": 135.0, "long_strike": 130.0, "strike": 135.0,
       "premium": 1.45, "net_credit": 1.45, "contracts": 1, "underlying_price": SPOT, "expiration": "2026-11-20",
       "account": "schwab_taxable", "economics": {"collateral": 500}}
SHARES = {"SPCX": 400.0}
BY_ACCT = {"SPCX": {"schwab_taxable": 100.0, "schwab_rollover_ira": 300.0}}


def test_whole_position_includes_the_shares_and_a_covered_position_loses_in_a_crash():
    c = combined_exposure([CC1, CC2], shares_by_symbol=SHARES, shares_by_symbol_account=BY_ACCT)["SPCX"]
    assert c["schema"] == "OptionsCombinedExposure@v2" and c["shares_held"] == 400.0
    assert c["shares_by_account"] == {"schwab_taxable": 100.0, "schwab_rollover_ira": 300.0}
    assert c["expirations"] == ["2026-10-23"] and c["scenarios"]  # single expiry -> flat rows present
    down30 = next(r for r in c["scenarios"] if r["move_pct"] == -30)
    px = round(SPOT * 0.7, 2)
    assert down30["options_only_pl"] == round(5.05 * 100 * 4, 2)        # four short calls keep their premium
    assert down30["shares_pl"] == round(400 * (SPOT * 0.7 - SPOT), 2)   # the shares lose ~$17.6k
    assert down30["whole_position_pl"] == round(down30["options_only_pl"] + down30["shares_pl"], 2)
    assert down30["whole_position_pl"] < 0 and down30["price"] == px
    assert "no basis or fees" in c["scenario_basis"]


def test_different_expirations_get_their_own_tables_and_no_single_payoff():
    c = combined_exposure([PUT, SPR], shares_by_symbol=SHARES, shares_by_symbol_account=BY_ACCT)["SPCX"]
    assert c["expirations"] == ["2026-11-06", "2026-11-20"]
    assert c["scenarios"] == []                                  # no single "at expiry" row set
    assert [g["expiration"] for g in c["scenarios_by_expiry"]] == ["2026-11-06", "2026-11-20"]
    assert c["scenarios_by_expiry"][0]["ideas"] == ["pp"] and c["scenarios_by_expiry"][1]["ideas"] == ["sp"]
    nov6 = next(r for r in c["scenarios_by_expiry"][0]["rows"] if r["move_pct"] == -30)
    px = SPOT * 0.7
    assert nov6["options_only_pl"] == round((max(140 - px, 0) - 6.45) * 100 * 3, 2)   # the puts pay
    assert nov6["whole_position_pl"] == round(nov6["options_only_pl"] + 400 * (px - SPOT), 2)
    assert nov6["whole_position_pl"] < 0                        # 300 insured of 400 shares: still a net loss
    assert "different dates" in c["note"] and "no single at-expiry payoff" in c["note"]
    assert {i["account"] for i in c["ideas"]} == {"schwab_taxable", "schwab_rollover_ira"}


def test_unknown_share_count_withholds_whole_position_never_zero():
    c = combined_exposure([CC1, CC2])["SPCX"]
    row = c["scenarios"][0]
    assert row["shares_pl"] is None and row["whole_position_pl"] is None and row["options_only_pl"] is not None
    assert "withheld" in c["scenario_basis"] and c["shares_by_account"] == {}


def _ent(monkeypatch, earnings_in_days: int):
    import options_desk_enterprise as ent
    earn = (date.today() + timedelta(days=earnings_in_days)).isoformat()
    monkeypatch.setattr(ent, "earnings_calendar", lambda syms: {s: earn for s in syms})
    return ent


def test_debit_spread_and_long_put_now_block_when_earnings_fall_inside_the_life(monkeypatch):
    ent = _ent(monkeypatch, 31)
    for strat in ("debit_spread", "long_put", "long_call", "leaps_call"):
        r = ent.earnings_blackout_check("AXTI", dte=110, strategy=strat)
        assert r["in_blackout"] is True, strat
        assert r["trigger"] == "expires_after_earnings"
        assert "inside this option's life" in r["reason"] and "blackout" not in r["reason"], r["reason"]
    assert ent.earnings_blackout_check("AXTI", dte=110, strategy="protective_put")["in_blackout"] is False  # hedges never block


def test_blackout_window_keeps_its_own_wording_and_clear_cases_stay_clear(monkeypatch):
    ent = _ent(monkeypatch, 5)
    r = ent.earnings_blackout_check("AAL", dte=30, strategy="cash_secured_put")
    assert r["in_blackout"] is True and r["trigger"] == "blackout_window" and "pre-earnings blackout" in r["reason"]
    ent2 = _ent(monkeypatch, 40)
    clear = ent2.earnings_blackout_check("AAL", dte=18, strategy="cash_secured_put")   # expires before the event, outside window
    assert clear["in_blackout"] is False and clear["trigger"] is None and clear["reason"] == ""
