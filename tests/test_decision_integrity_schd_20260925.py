"""SCHD decision-integrity regression fixtures (2026-09-25 10:48 ET).

Exact values from the incident: desk $33.12 (alpaca print 10:30:06 ET),
operator's article $33.68 (a Sep 18–22 print), plan zone $33.85–$34.10, stop
$33.55, target $35.30, RSI 36.69, IRA 0.2508 sh + taxable 0.5436 sh, taxable
sell 2026-09-08 406 sh @ $34.695 (a GAIN), claimed "wash blocked until Oct 8".
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import decision_integrity as di  # noqa: E402

NOW = datetime(2026, 9, 25, 14, 48, 39, tzinfo=timezone.utc)          # 10:48:39 ET
QUOTE_AS_OF = "2026-09-25T10:30:06.982443-04:00"
PLAN_CREATED = "2026-09-15T18:51:22.940989-04:00"
POSITIONS = [{"account": "schwab_rollover_ira", "qty": 0.2508}, {"account": "schwab_taxable", "qty": 0.5436}]
TAXABLE_TXS = [
    {"trade_date": "2026-02-25", "action": "Buy", "quantity": 100, "price": 31.4097, "amount": -3140.97, "fees": 0},
    {"trade_date": "2026-02-26", "action": "Buy", "quantity": 300, "price": 31.48, "amount": -9444.00, "fees": 0},
    {"trade_date": "2026-06-29", "action": "Buy", "quantity": 6.544, "price": 31.2688, "amount": -204.61, "fees": 0},
    {"trade_date": "2026-09-08", "action": "Sell", "quantity": 406, "price": 34.695, "amount": 14085.80, "fees": 0.37},
]


def _schd(**over):
    ev = dict(symbol="SCHD", price=33.12, price_as_of=QUOTE_AS_OF, price_source="data_broker.market_quotes:alpaca",
              entry_low=33.85, entry_high=34.10, stop=33.55, target=35.30, plan_id=19648, plan_created_at=PLAN_CREATED,
              rsi=36.69, positions=list(POSITIONS), confirmations_complete=False,
              confirmation_gaps=["ma_bounce", "rr", "wash"])
    ev.update(over)
    return di.Evidence(**ev)


# ── the incident, replayed ─────────────────────────────────────────────────

def test_schd_price_below_stop_invalidates_and_suppresses_mechanics():
    r = di.validate(_schd(), now=NOW)
    assert r["state"] == "INVALIDATED_BY_PRICE_OR_STOP"
    assert r["actionable_mechanics"] is False
    assert "PRICE_AT_OR_BELOW_STOP" in r["reason_codes"]
    assert r["plan"]["shown_as"] == "historical"
    # every account named, not just the IRA residual
    assert {a["account"] for a in r["held"]["accounts"]} == {"schwab_rollover_ira", "schwab_taxable"}
    assert r["held"]["dust_only"] is True
    assert r["alert_state"] == "ALERT_NOT_ARMED"
    # exact quote age, not "0h"
    assert r["quote"]["age_label"] == "19m old" and r["quote"]["freshness"] == "CURRENT"
    assert r["order_semantics"]["buy_limit_in_zone"] == "MARKETABLE_IMMEDIATE_FILL"
    assert any("new validated setup" in n for n in r["next_observation"])


def test_operator_article_price_conflicts_and_is_disclosed_not_replaced():
    r = di.validate(_schd(operator_quoted_price=33.68), now=NOW)
    assert "QUOTE_CONFLICT" in r["reason_codes"]
    assert r["quote"]["operator_quoted_price"] == 33.68
    assert round(r["quote"]["operator_vs_desk_pct"], 2) == 1.69
    # the desk price is still the one acted on (never the article's); still invalidated
    assert r["state"] == "INVALIDATED_BY_PRICE_OR_STOP"


def test_out_of_order_quote_update_reads_stale_not_current():
    late = datetime(2026, 9, 25, 16, 30, tzinfo=timezone.utc)    # 12:30 ET, print from 10:30
    r = di.validate(_schd(price=33.60, stop=33.55), now=late)
    assert "QUOTE_STALE" in r["reason_codes"]
    assert r["state"] == "STALE_OR_CONFLICTING_QUOTE"
    assert r["quote"]["age_label"] == "2.0h old"


def test_market_closed_freshness_holds_friday_print_over_weekend():
    friday_close = "2026-09-25T15:59:00-04:00"
    saturday = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)
    r = di.validate(_schd(price=33.60, price_as_of=friday_close), now=saturday)
    assert "QUOTE_STALE" not in r["reason_codes"]
    assert r["quote"]["freshness"] == "LAST_SESSION_HELD" and r["quote"]["now_session"] == "closed"
    # ...but a week-old print is stale even on a weekend
    old = di.validate(_schd(price=33.60, price_as_of="2026-09-18T15:59:00-04:00"), now=saturday)
    assert "QUOTE_STALE" in old["reason_codes"]


def test_rapid_reclaim_above_stop_is_not_valid_current_without_fresh_plan_conditions():
    # price pops back above the stop but stays below the zone: conditional, not actionable
    r = di.validate(_schd(price=33.70, positions=[], confirmations_complete=None, confirmation_gaps=[]), now=NOW)
    assert r["state"] == "WAIT_FOR_CONFIRMATION"
    assert r["actionable_mechanics"] is False and r["plan"]["shown_as"] == "conditional"
    assert r["order_semantics"]["buy_limit_in_zone"] == "MARKETABLE_IMMEDIATE_FILL"


def test_valid_current_only_inside_zone_fresh_flat_confirmed():
    r = di.validate(_schd(price=33.90, positions=[], confirmations_complete=True, confirmation_gaps=[]), now=NOW)
    assert r["state"] == "VALID_CURRENT" and r["actionable_mechanics"] is True
    assert r["plan"]["shown_as"] == "current"


def test_buy_limit_above_market_is_marketable_not_a_wait_instruction():
    sem = di.order_semantics(price=33.12, entry_low=33.85, entry_high=34.10)
    assert sem["buy_limit_in_zone"] == "MARKETABLE_IMMEDIATE_FILL"
    assert "conditional alert" in sem["advisory"]
    assert di.order_semantics(price=34.50, entry_low=33.85, entry_high=34.10)["buy_limit_in_zone"] == "RESTING_BELOW_MARKET"


def test_held_vs_add_distinction_dust_and_real_position():
    dust = di.validate(_schd(price=33.90, confirmations_complete=True, confirmation_gaps=[]), now=NOW)
    assert dust["state"] == "HELD_POLICY_BLOCK" and dust["held"]["dust_only"] is True
    real = di.validate(_schd(price=33.90, confirmations_complete=True, confirmation_gaps=[],
                             positions=[{"account": "schwab_rollover_ira", "qty": 912.2508}]), now=NOW)
    assert real["state"] == "HELD_POLICY_BLOCK" and real["held"]["dust_only"] is False
    assert "add-to-position policy applies" in real["reasons"][0]["detail"]


def test_stale_or_undated_plan_is_history():
    undated = di.validate(_schd(price=33.90, positions=[], plan_created_at=None,
                                confirmations_complete=True, confirmation_gaps=[]), now=NOW)
    assert undated["state"] == "STALE_PLAN" and "PLAN_UNDATED" in undated["reason_codes"]
    old = di.validate(_schd(price=33.90, positions=[], plan_created_at="2026-09-01T17:52:44-04:00",
                            confirmations_complete=True, confirmation_gaps=[]), now=NOW)
    assert old["state"] == "STALE_PLAN" and "PLAN_OLD" in old["reason_codes"]


def test_missing_evidence_when_no_price_or_plan():
    assert di.validate(_schd(price=None), now=NOW)["state"] == "MISSING_EVIDENCE"
    assert di.validate(_schd(entry_low=None, entry_high=None), now=NOW)["state"] == "MISSING_EVIDENCE"


# ── tax evidence ───────────────────────────────────────────────────────────

def test_schd_taxable_sell_was_a_gain_so_house_hold_not_wash_sale():
    g = di.fifo_realized_gain(TAXABLE_TXS, sell_date="2026-09-08")
    assert g["evidence"] == "FIFO_FROM_TRADE_TRANSACTIONS"
    assert g["realized_gain"] > 1200 and g["unmatched_quantity"] == 0
    w = di.classify_wash(last_taxable_sell_date="2026-09-08", realized_gain=g["realized_gain"],
                         evidence=g["evidence"], today=NOW.date())
    assert w["kind"] == "HOUSE_HOLD_NO_LOSS" and w["hold_until"] == "2026-10-08"
    assert w["legal_conclusion"] == "NOT_A_WASH_SALE"
    r = di.validate(_schd(price=33.90, positions=[], confirmations_complete=True, confirmation_gaps=[], wash=w), now=NOW)
    assert r["state"] == "HOUSE_WASH_HOLD"
    assert r["reasons"][0]["code"] == "HOUSE_WASH_HOLD" and "no wash-sale rule" in r["reasons"][0]["detail"]


def test_loss_sale_with_cross_account_ira_acquisition_is_wash_sale_risk():
    txs = [{"trade_date": "2026-08-01", "action": "Buy", "quantity": 100, "price": 36.0},
           {"trade_date": "2026-09-08", "action": "Sell", "quantity": 100, "price": 34.695}]
    g = di.fifo_realized_gain(txs, sell_date="2026-09-08")
    assert g["realized_gain"] < 0
    w = di.classify_wash(last_taxable_sell_date="2026-09-08", realized_gain=g["realized_gain"], evidence=g["evidence"],
                         acquisitions_within_30d=[{"trade_date": "2026-09-25", "account": "schwab_rollover_ira", "quantity": 912}],
                         today=NOW.date())
    assert w["kind"] == "WASH_SALE_RISK_LOSS" and w["legal_conclusion"] == "WASH_SALE_RISK"
    assert "IRA included" in w["label"] and "1 acquisition" in w["label"]


def test_missing_lot_data_yields_unverified_not_a_legal_claim():
    g = di.fifo_realized_gain([{"trade_date": "2026-09-08", "action": "Sell", "quantity": 406, "price": 34.695}],
                              sell_date="2026-09-08")
    assert g["evidence"] == "INSUFFICIENT_LOTS" and g["realized_gain"] is None
    w = di.classify_wash(last_taxable_sell_date="2026-09-08", realized_gain=None, evidence=g["evidence"], today=NOW.date())
    assert w["kind"] == "UNVERIFIED" and w["legal_conclusion"] is None
    r = di.validate(_schd(price=33.90, positions=[], confirmations_complete=True, confirmation_gaps=[], wash=w), now=NOW)
    assert r["state"] == "TAX_STATUS_UNVERIFIED"


def test_no_recent_taxable_sell_is_none():
    assert di.classify_wash(last_taxable_sell_date=None, realized_gain=None)["kind"] == "NONE"
    assert di.classify_wash(last_taxable_sell_date="2026-07-01", realized_gain=10.0, today=NOW.date())["kind"] == "NONE"


# ── alerts ─────────────────────────────────────────────────────────────────

def test_alert_not_armed_vs_armed_with_delivery_receipt():
    none = di.validate(_schd(), now=NOW)
    assert none["alert_state"] == "ALERT_NOT_ARMED"
    armed = di.validate(_schd(alert={"armed": True, "alert_id": 77, "condition": "price_cross_above 33.85"}), now=NOW)
    assert armed["alert_state"] == "ARMED_NO_DELIVERY_RECEIPT"
    delivered = di.validate(_schd(alert={"armed": True, "alert_id": 77, "delivery_receipt": "tg:9001"}), now=NOW)
    assert delivered["alert_state"] == "ARMED_DELIVERY_RECEIPTED"


# ── suppression + downstream agreement ─────────────────────────────────────

def test_suppress_mechanics_removes_sizing_and_rr_keeps_history():
    adv = {"action": "Monitor / No Action", "reentry_range_low": 33.85, "reentry_range_high": 34.10, "stop_loss": 33.55,
           "target": 35.3, "risk_per_share_low": 0.55, "risk_per_share_high": 0.3, "reward_low": 1.2, "reward_high": 1.45,
           "rr": None, "sizing": {"shares": 3711, "allocation": 126081.23, "note": "Capped at 10% allocation"}}
    r = di.validate(_schd(), now=NOW)
    out = di.suppress_mechanics(adv, r)
    assert out["sizing"]["shares"] is None and out["sizing"]["allocation"] is None
    assert out["reward_low"] is None and out["risk_per_share_low"] is None
    assert out["historical_plan"]["stop_loss"] == 33.55 and out["historical_plan"]["shown_as"] == "historical"
    assert out["historical_plan"]["invalidated_by"] == ["PRICE_AT_OR_BELOW_STOP"]
    assert out["decision_integrity"]["state"] == "INVALIDATED_BY_PRICE_OR_STOP"
    ok = di.validate(_schd(price=33.90, positions=[], confirmations_complete=True, confirmation_gaps=[]), now=NOW)
    assert di.suppress_mechanics(adv, ok)["sizing"]["shares"] == 3711


def test_telegram_card_and_summary_agree_with_validator():
    from scripts.lib import cio_telegram_converse as ctc
    row = {"symbol": "SCHD", "price": 33.12, "price_as_of": QUOTE_AS_OF, "price_source": "data_broker.market_quotes:alpaca",
           "price_age_h": 0.31, "entry_low": 33.85, "entry_high": 34.10, "stop": 33.55, "target": 35.30, "rr": None,
           "plan_as_of": PLAN_CREATED, "rsi": 36.69, "rsi_status": "NEUTRAL", "sma_20": 34.08, "sma_50": 33.78,
           "resistance": {"state": "TESTING", "level": 33.04}, "held": True, "wash_blocked": True, "wash_until": "2026-10-08",
           "positions": POSITIONS,
           "gates": [{"id": "fresh", "pass": True, "value": "19m"}, {"id": "zone", "pass": False, "value": "-2.2% vs zone"}],
           "why": ["Price is -2.2% from the entry zone (near threshold 3%)."],
           "advisory": {"action": "Monitor / No Action", "date": "2026-09-25", "confirmations_complete": False,
                        "confirmation_gaps": ["ma_bounce", "rr", "wash"]}}
    text = ctc.format_reentry_symbol_reply(row, holding={"shares": 0.2508, "account": "schwab_rollover_ira"},
                                           computed_at="2026-09-25T14:45:00Z", operator_price=33.68, now=NOW)
    assert "(19m old)" in text
    assert "buy-limit in zone" not in text
    assert "HISTORICAL plan — not current" in text
    assert "INVALIDATED_BY_PRICE_OR_STOP" in text
    assert "You quoted $33.68" in text
    assert "schwab_taxable" in text and "schwab_rollover_ira" in text
    assert "Watch alert: none armed" in text
    assert "institutional packet" not in text          # no BUY_READY/ENTRY_NEAR mechanics
    assert "R:R" not in text
    assert "No orders/stops from chat" in text


def test_downstream_channels_agree_on_no_action():
    r = di.validate(_schd(), now=NOW)
    lines = di.render_operator_summary(r)
    assert lines[0].startswith("Decision integrity: *INVALIDATED_BY_PRICE_OR_STOP*")
    assert any("Historical plan (not current)" in ln for ln in lines)
    assert lines[-1].startswith("Watch alert: none armed")
    adv = di.suppress_mechanics({"action": "Monitor / No Action", "sizing": {"shares": 3711}}, r)
    assert adv["action"] == "Monitor / No Action" and adv["sizing"]["shares"] is None
    # machine-readable states are the ones the contract enumerates
    assert set(di.STATES) >= {r["state"]} and r["schema"] == "DecisionIntegrity@v1"


def test_validator_carries_no_behavior_fields():
    from scripts.lib.cio_instrument_record import BEHAVIOR_FIELDS
    r = di.validate(_schd(), now=NOW)
    flat = json.dumps(r)
    assert r["mbi_behavior"] == 0 and r["authority"] == "READ_ONLY_ADVISORY"
    for k in ("size_usd", "order", "place_order", "shares_to_buy"):
        assert f'"{k}"' not in flat
    assert not (set(r) & set(BEHAVIOR_FIELDS))
