"""FQ-142 / D32 SPEC §5 — the advisory protective put / collar suggestions.

Advisory only: nothing here may place, size, stop or cancel an order, and nothing may write a
CIO behavior field. The last two tests prove that in the source (an AST import sweep and the
existing ``BehaviorWriteRefused`` rail), not by asking the module nicely.

    .venv/bin/python -m pytest tests/test_protective_put_advisory.py -q
"""
from __future__ import annotations

import ast
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import protective_put_advisory as adv  # noqa: E402

CFG = dict(adv.DEFAULTS)
NOW = date(2026, 11, 5)


def position(**over):
    row = {"symbol": "SPCX", "account": "ACCT_A", "quantity": 100, "price": 200.0,
           "market_value": 20_000.0, "asset_class": "stock"}
    row.update(over)
    return row


def chain(*, exp="2026-11-20", dte=15, spot=200.0, put=(1.90, 2.10), call=(3.00, 3.20),
          put_strike=180.0, call_strike=230.0):
    strikes = []
    if put:
        strikes.append({"side": "put", "strike": put_strike, "bid": put[0], "ask": put[1], "multiplier": 100})
    if call:
        strikes.append({"side": "call", "strike": call_strike, "bid": call[0], "ask": call[1], "multiplier": 100})
    return {"underlying_price": spot, "expirations": [{"exp": exp, "dte": dte, "strikes": strikes}]}


# ── the gates ───────────────────────────────────────────────────────────────

def test_a_position_at_the_threshold_is_suggested_and_below_is_not():
    event = {"event_date": "2026-11-12", "days_to_event": 7}
    just_below, reason = adv.suggest_for_position(position(market_value=19_999.0), book_value=1_000_000.0,
                                                  event=event, cfg=CFG, now=NOW)
    assert just_below is None and reason == "below_size_threshold"

    at_threshold, reason = adv.suggest_for_position(position(market_value=20_000.0), book_value=1_000_000.0,
                                                    event=event, cfg=CFG, now=NOW)
    assert reason is None and at_threshold["pct_of_book"] == 2.0

    above, _ = adv.suggest_for_position(position(market_value=25_000.0), book_value=1_000_000.0,
                                        event=event, cfg=CFG, now=NOW)
    assert above["pct_of_book"] == 2.5


@pytest.mark.parametrize("row, reason", [
    ({"symbol": "CASH", "account": "A", "market_value": 50_000.0, "asset_class": "cash"}, "not_a_single_stock"),
    ({"symbol": "SPCX 261120P00180000", "account": "A", "market_value": 50_000.0}, "not_a_single_stock"),
    ({"symbol": "SPCX", "account": "A", "market_value": 50_000.0, "asset_class": "option"}, "not_a_single_stock"),
])
def test_cash_and_option_rows_are_never_covered(row, reason):
    got, why = adv.suggest_for_position(row, book_value=1_000_000.0,
                                        event={"days_to_event": 5}, cfg=CFG, now=NOW)
    assert got is None and why == reason


def test_no_event_or_outside_the_window_is_not_a_suggestion():
    row = position()
    assert adv.suggest_for_position(row, book_value=1_000_000.0, event=None, cfg=CFG, now=NOW)[1] == "no_event"
    assert adv.suggest_for_position(row, book_value=1_000_000.0, event={"days_to_event": 11},
                                    cfg=CFG, now=NOW)[1] == "outside_event_window"
    assert adv.suggest_for_position(row, book_value=1_000_000.0, event={"days_to_event": -3},
                                    cfg=CFG, now=NOW)[1] == "outside_event_window"


def test_the_window_is_inclusive_at_both_ends():
    for days in (10, 0, -2):
        got, why = adv.suggest_for_position(position(), book_value=1_000_000.0,
                                            event={"days_to_event": days}, cfg=CFG, now=NOW)
        assert why is None and got is not None, days


def test_days_are_derived_from_a_date_when_the_caller_gives_only_the_date():
    got, why = adv.suggest_for_position(position(), book_value=1_000_000.0,
                                        event={"event_date": "2026-11-12"}, cfg=CFG, now=NOW)
    assert why is None and got["event"]["days_to_event"] == 7


# ── floor and cost ──────────────────────────────────────────────────────────

def test_the_floor_targets_the_broker_stop_when_the_position_carries_one():
    got, _ = adv.suggest_for_position(position(stop_price=175.0), book_value=1_000_000.0,
                                      event={"days_to_event": 5}, cfg=CFG, now=NOW)
    assert got["floor_basis"] == "broker_stop" and got["floor_price"] == 175.0


def test_without_a_stop_the_floor_is_the_configured_distance_below_spot():
    got, _ = adv.suggest_for_position(position(), book_value=1_000_000.0,
                                      event={"days_to_event": 5}, cfg=CFG, now=NOW)
    assert got["floor_basis"] == "spot_minus_10.0pct" and got["floor_price"] == 180.0


def test_a_quoted_chain_gives_a_real_premium_and_a_real_strike():
    got, _ = adv.suggest_for_position(position(), book_value=1_000_000.0,
                                      event={"days_to_event": 7}, chain=chain(), cfg=CFG, now=NOW)
    assert got["cost_is_estimate"] is False
    assert got["cost_usd"] == 210.0          # 2.10 ask × 100 × 1 contract
    assert got["floor_price"] == 180.0 and got["floor_strike_source"] == "chain"
    assert got["expiry"] == "2026-11-20"
    assert "cost_basis" not in got


def test_without_a_chain_the_cost_is_a_labeled_estimate_never_a_quoted_premium():
    got, _ = adv.suggest_for_position(position(), book_value=1_000_000.0,
                                      event={"days_to_event": 7}, cfg=CFG, now=NOW)
    assert got["cost_is_estimate"] is True
    assert got["cost_usd"] == 500.0          # 2.5% of $20,000
    assert "ESTIMATE" in got["cost_basis"]


def test_a_collar_is_offered_only_when_a_call_is_quotable_and_its_net_can_be_a_credit():
    got, _ = adv.suggest_for_position(position(), book_value=1_000_000.0,
                                      event={"days_to_event": 7}, chain=chain(), cfg=CFG, now=NOW)
    assert got["collar"]["cap_price"] == 230.0
    assert got["collar"]["call_credit_usd"] == 300.0 and got["collar"]["net_cost_usd"] == -90.0
    assert got["collar"]["net_is_credit"] is True

    no_call, _ = adv.suggest_for_position(position(), book_value=1_000_000.0,
                                          event={"days_to_event": 7}, chain=chain(call=None), cfg=CFG, now=NOW)
    assert "collar" not in no_call


@pytest.mark.parametrize("qty", [-300, -1, 0])
def test_a_short_or_flat_position_is_never_covered(qty):
    """cc-deepseek-3 second review (2026-11-05): `position_value` erases the sign, so -300 shares produced a
    "protective put" — a hedge that ADDS the exposure it claims to remove. The side is a gate, not a detail."""
    got, why = adv.suggest_for_position(position(quantity=qty, market_value=30_000.0), book_value=1_000_000.0,
                                        event={"days_to_event": 5}, chain=chain(), cfg=CFG, now=NOW)
    assert got is None and why == "not_a_long_position"


def test_cost_and_floor_are_per_held_share_not_per_covered_contract():
    """cc-deepseek-3's exact case: 40 shares of a $2,500 name (10% of a $1,000,000 book) and a put ask of $20.50.

    One contract covers 100 shares for a 40-share position (`cover: over`), so dividing by contracts*100 showed
    $20.50 a share for a hedge that costs $51.25 of each held share, and a floor $30.75 too high.
    """
    row = position(quantity=40, price=2_500.0, market_value=100_000.0)
    got, why = adv.suggest_for_position(row, book_value=1_000_000.0, event={"days_to_event": 5},
                                        chain=chain(spot=2_500.0, put=(20.0, 20.5), put_strike=2_250.0, call=None),
                                        cfg=CFG, now=NOW)
    assert why is None
    assert got["contracts"] == 1 and got["cover"] == "over"
    assert got["cost_usd"] == 2_050.0
    assert got["cost_per_share"] == 51.25             # 2,050 across the 40 HELD shares
    assert got["cost_per_covered_share"] == 20.5      # the quoted premium, named for what it is
    assert got["floor_after_cost"] == 2_198.75        # 2,250 − 51.25, not 2,229.50


def test_partial_coverage_divides_by_all_held_shares():
    row = position(quantity=250, price=200.0, market_value=50_000.0)
    got, why = adv.suggest_for_position(row, book_value=1_000_000.0, event={"days_to_event": 7}, chain=chain(),
                                        cfg=CFG, now=NOW)
    assert why is None
    assert got["contracts"] == 2 and got["cover"] == "partial"
    assert got["cost_usd"] == 420.0                   # 2.10 ask × 100 × 2 contracts
    assert got["cost_per_share"] == 1.68              # across all 250 held shares
    assert got["cost_per_covered_share"] == 2.1       # across the 200 covered shares
    assert got["floor_after_cost"] == 178.32          # 180 − 1.68


def test_full_coverage_keeps_the_two_per_share_figures_equal():
    got, _ = adv.suggest_for_position(position(), book_value=1_000_000.0, event={"days_to_event": 7},
                                      chain=chain(), cfg=CFG, now=NOW)
    assert got["cover"] == "full"
    assert got["cost_per_share"] == got["cost_per_covered_share"] == 2.1
    assert got["floor_after_cost"] == 177.9


# ── cc-deepseek-5 second review (2026-11-05): the strike vs the target, and the premium vs the position ──────────

def test_a_strike_far_from_the_broker_stop_is_flagged_with_target_and_distance():
    """A 150 put quoted under a 235 broker stop was reported as `floor_price 150` beside `floor_basis broker_stop`
    with nothing saying the put sits 85 points below the stop it claims to defend."""
    got, why = adv.suggest_for_position(
        position(stop_price=235.0), book_value=1_000_000.0, event={"days_to_event": 7},
        chain=chain(spot=250.0, put=(2.9, 3.0), put_strike=150.0, call=None), cfg=CFG, now=NOW)
    assert why is None
    assert got["floor_basis"] == "broker_stop"
    assert got["floor_target"] == 235.0 and got["floor_price"] == 150.0
    assert got["floor_distance"] == 85.0 and got["floor_target_relation"] == "below"
    assert got["floor_strike_far_from_target"] is True
    assert "235.00" in got["floor_warning"] and "150.00" in got["floor_warning"] and "85.00" in got["floor_warning"]
    assert "does not defend" in got["floor_warning"]


def test_a_strike_far_from_the_ten_percent_target_is_flagged_the_same_way():
    got, why = adv.suggest_for_position(
        position(price=250.0, market_value=25_000.0), book_value=1_000_000.0, event={"days_to_event": 7},
        chain=chain(spot=250.0, put=(2.9, 3.0), put_strike=150.0, call=None), cfg=CFG, now=NOW)
    assert why is None
    assert got["floor_basis"] == "spot_minus_10.0pct"
    assert got["floor_target"] == 225.0 and got["floor_price"] == 150.0
    assert got["floor_distance"] == 75.0 and got["floor_strike_far_from_target"] is True
    assert "floor_warning" in got


def test_a_nearby_strike_is_not_flagged():
    got, _ = adv.suggest_for_position(
        position(price=250.0, market_value=25_000.0), book_value=1_000_000.0, event={"days_to_event": 7},
        chain=chain(spot=250.0, put=(1.9, 2.0), put_strike=220.0, call=None), cfg=CFG, now=NOW)
    assert got["floor_target"] == 225.0 and got["floor_price"] == 220.0
    assert got["floor_distance"] == 5.0 and got["floor_target_relation"] == "below"
    assert got["floor_strike_far_from_target"] is False and "floor_warning" not in got


def test_a_premium_above_the_configured_share_of_the_position_is_refused():
    """cc5's case: 40 shares, spot crashed to 100 ($4,000 of stock), a 225 put quoted at 126 → $12,600 of premium.
    The premium is a real quote; the answer to a hedge costing more than the position is a refusal, not a floor."""
    row = position(quantity=40, price=100.0, market_value=4_000.0, stop_price=235.0)
    got, why = adv.suggest_for_position(
        row, book_value=200_000.0, event={"days_to_event": 7},
        chain=chain(spot=100.0, put=(125.0, 126.0), put_strike=225.0, call=None), cfg=CFG, now=NOW)
    assert got is None and why == "cost_exceeds_position_value"


def test_a_premium_at_or_above_the_floor_withholds_the_floor_after_cost():
    """A $1 floor with a $1.20 premium leaves no protected level; the number is withheld and labelled, never shown
    as a negative or a plausible-looking floor."""
    row = position(quantity=100, price=5.0, market_value=500.0)
    got, why = adv.suggest_for_position(
        row, book_value=25_000.0, event={"days_to_event": 7},
        chain=chain(spot=5.0, put=(1.1, 1.2), put_strike=1.0, call=None), cfg=CFG, now=NOW)
    assert why is None                                    # 120/500 = 24% of the position, under the 25% gate
    assert got["cost_usd"] == 120.0 and got["cover"] == "full"
    assert got["floor_price"] == 1.0 and got["floor_after_cost"] is None
    assert got["floor_after_cost_negative"] is True and "withheld" in got["floor_after_cost_note"]


def test_cover_is_stated_honestly_for_odd_share_counts():
    partial, _ = adv.suggest_for_position(position(quantity=250, market_value=50_000.0), book_value=1_000_000.0,
                                          event={"days_to_event": 7}, cfg=CFG, now=NOW)
    assert partial["contracts"] == 2 and partial["cover"] == "partial"
    over, _ = adv.suggest_for_position(position(quantity=40, market_value=8_000.0), book_value=100_000.0,
                                       event={"days_to_event": 7}, cfg=CFG, now=NOW)
    assert over["contracts"] == 1 and over["cover"] == "over"


# ── the rails ───────────────────────────────────────────────────────────────

def test_every_suggestion_says_the_system_does_not_place_it():
    report = adv.suggest_for_book(
        [position(), position(symbol="QQQ", market_value=30_000.0)],
        book_value=1_000_000.0, events={"SPCX": {"days_to_event": 7}}, cfg=CFG, now=NOW,
    )
    assert report["advisory_only"] is True and report["placed_by_system"] is False
    assert [row["symbol"] for row in report["suggestions"]] == ["SPCX"]
    row = report["suggestions"][0]
    assert row["placed_by_system"] is False and row["advisory_only"] is True
    assert "will not place" in row["operator_action"]
    # a skipped row keeps its reason rather than vanishing
    assert {"symbol": "QQQ", "account": "ACCT_A", "skipped": "no_event"} in report["skipped"]


FORBIDDEN_MODULES = {
    "options_order_pilot", "options_pilot_arm", "brokers", "approval_service", "schwab_transport",
    "schwab_pilot_orders", "alpaca_trade_api", "alpaca", "trade_executor", "order_executor",
    "telegram_2fa", "two_factor", "options_execution_policy", "options_desk_enterprise",
    "options_paper_monitor", "db_adapter", "cio_instrument_record",
}


def test_the_module_has_no_broker_or_writer_import_path():
    source = (ROOT / "scripts" / "lib" / "options_pipeline" /
              "protective_put_advisory.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.update({alias.name, alias.name.split(".")[0]})
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.update({node.module, node.module.split(".")[0]})
    assert not modules & FORBIDDEN_MODULES, sorted(modules & FORBIDDEN_MODULES)
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for forbidden_call in ("place_order", "submit_order", "submit_to_desk_queue", "sync_approval_queue"):
        assert forbidden_call not in names


def test_the_existing_behavior_write_rail_is_still_intact():
    """MBI_BEHAVIOR = 0 is a rail in code, not a promise in prose: a behavior-shaped write still refuses."""
    from lib import cio_instrument_record as ir

    with pytest.raises(ir.BehaviorWriteRefused):
        ir.apply_cognition({}, size_usd=25_000)
    with pytest.raises(ir.BehaviorWriteRefused):
        ir.apply_cognition({}, stop=180.0)
