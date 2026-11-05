"""Exercise the real advisory consumer; no broker, database or provider calls."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "scripts.lib._fq116_cio_truth", ROOT / "scripts/lib/cio_truth.py")
truth = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = truth
SPEC.loader.exec_module(truth)
NOW = datetime(2026, 11, 4, 15, tzinfo=timezone.utc)


def row(clock, status="WORKING"):
    return {"account": "SyntheticAccountAlpha", "symbol": "SYNTH",
            "order_id": "synthetic-stop-one", "status": status,
            "stop_price": 100, "qty": 1, "captured_at": clock}


@pytest.mark.parametrize("clock,expected", [
    ("2026-11-04T14:59:00Z", True),
    ("2026-10-28T14:59:00Z", False),
    (None, False),
    ("2026-11-05T14:59:00Z", False),
])
def test_working_status_needs_current_observation(clock, expected):
    result = truth.stop_for("SyntheticAccountAlpha", "SYNTH",
                            broker_rows=[row(clock)], now=NOW)
    assert result["broker_protected"] is expected


@pytest.mark.parametrize("clock", [None, "broken", "2026-11-04T14:59:00",
                                  "2026-10-28T14:59:00Z", "2026-11-05T14:59:00Z"])
def test_unusable_observation_cannot_supply_active_count_or_zero_heat(tmp_path, clock):
    holdings = {"as_of": NOW.isoformat(), "generated_at": NOW.isoformat(),
                "holdings": [{"account": "SyntheticAccountAlpha", "symbol": "SYNTH",
                              "shares": 1, "price": 110, "market_value": 110,
                              "day_change": 0}]}
    document = truth.resolve(tmp_path, NOW, inputs={
        "holdings": holdings, "broker_stops": [row(clock)], "stop_fills": {},
        "companies": {}, "policy": {}, "planned_stops": {},
    })
    position = document["positions"]["rows"][0]
    assert position["broker_protected"] is False
    assert position["stop_status_raw"] == "WORKING"
    assert position["stop_category"] == "unknown"
    assert position["stop_note"]
    assert document["stops"]["active_count"] == 0
    assert document["positions"]["portfolio_heat_pct"] is None
    assert document["positions"]["resting_heat_pct"] is None
    assert position["resting_stop_distance_pct"] is None


@pytest.mark.parametrize("status", ["PENDING_ACTIVATION", "AWAITING_PARENT_ORDER",
                                   "AWAITING_MANUAL_REVIEW"])
def test_freshness_does_not_invent_session_or_activation_evidence(status):
    result = truth.stop_for("SyntheticAccountAlpha", "SYNTH",
                            broker_rows=[row("2026-11-04T14:59:00Z", status)], now=NOW)
    assert result["broker_protected"] is False
    assert result["stop_state"] == "pending_activation"
    assert result["stop_status_raw"] == status


def test_one_completed_session_is_fresh_even_across_weekend():
    result = truth.stop_for("SyntheticAccountAlpha", "SYNTH",
                            broker_rows=[row("2026-10-30T19:00:00Z")],
                            now=datetime(2026, 11, 2, 14, tzinfo=timezone.utc))
    assert result["broker_protected"] is True
    assert result["stale"] is False


def test_fresh_active_control_keeps_real_loss(tmp_path):
    document = truth.resolve(tmp_path, NOW, inputs={
        "holdings": {"as_of": NOW.isoformat(), "generated_at": NOW.isoformat(),
                     "holdings": [{"account": "SyntheticAccountAlpha", "symbol": "SYNTH",
                                   "shares": 1, "price": 110, "market_value": 110,
                                   "day_change": 0}]},
        "broker_stops": [row("2026-11-04T14:59:00Z")], "stop_fills": {},
        "companies": {}, "policy": {}, "planned_stops": {},
    })
    assert document["stops"]["active_count"] == 1
    assert document["positions"]["loss_at_stop_usd"] == 10
    assert document["positions"]["loss_at_resting_stops_usd"] == 10


def test_stale_pending_cannot_count_as_current_resting_stop():
    result = truth.stop_for("SyntheticAccountAlpha", "SYNTH",
                            broker_rows=[row("2026-10-28T14:59:00Z", "PENDING_ACTIVATION")], now=NOW)
    assert result["broker_protected"] is False
    assert result["stop_state"] == "unknown"
    assert result["stop_state_observed"] == "pending_activation"
    assert result["stop_status_raw"] == "PENDING_ACTIVATION"
    assert result["stop_observation"]["status"] == "STALE"
    assert "not refreshed since" in result["stop_note"]


def test_missing_one_account_clock_does_not_inherit_another_accounts_clock(tmp_path):
    fresh = row("2026-11-04T14:59:00Z")
    unknown = {**row(None), "account": "SyntheticAccountBeta"}
    document = truth.resolve(tmp_path, NOW, inputs={
        "holdings": {"as_of": NOW.isoformat(), "generated_at": NOW.isoformat(), "holdings": [
            {"account": account, "symbol": "SYNTH", "shares": 1, "price": 110,
             "market_value": 110, "day_change": 0}
            for account in ("SyntheticAccountAlpha", "SyntheticAccountBeta")]},
        "broker_stops": [fresh, unknown], "stop_fills": {},
        "companies": {}, "policy": {}, "planned_stops": {},
    })
    positions = document["positions"]["rows"]
    assert [p["broker_protected"] for p in positions] == [True, False]
    assert positions[1]["stop_observation"]["as_of"] is None
    assert document["stops"]["active_count"] == 1
    assert document["positions"]["portfolio_heat_pct"] is None
    assert document["positions"]["resting_heat_pct"] is None
    assert document["stops"]["stale"] is True
    assert document["stops"]["as_of"] is None
    assert document["stops"]["last_broker_read_at"] is None
    assert "1 of 2" in document["stops"]["gap"]["reason"]


@pytest.mark.parametrize("clock", [None, "broken", "2026-11-04T14:59:00",
                                  "2026-11-05T14:59:00Z"])
def test_partial_clock_cannot_make_stop_section_fresh(clock):
    result = truth.stop_clock([
        {"stop_source": "broker_resting", "stop_captured_at": "2026-11-04T14:59:00Z"},
        {"stop_source": "broker_resting", "stop_captured_at": clock},
    ], NOW, contract={"open_h": .25, "closed_h": 72})
    assert result["stale"] is True
    assert result["as_of"] is None
    assert result["last_broker_read_at"] is None
    assert "1 of 2" in result["gap"]["reason"]


def test_protect_reason_explains_old_evidence_instead_of_claiming_stop_absent(tmp_path):
    document = truth.resolve(tmp_path, NOW, inputs={
        "holdings": {"as_of": NOW.isoformat(), "generated_at": NOW.isoformat(),
                     "holdings": [{"account": "SyntheticAccountAlpha", "symbol": "SYNTH",
                                   "shares": 1, "price": 110, "market_value": 110,
                                   "day_change": 0}]},
        "broker_stops": [row("2026-10-28T14:59:00Z")], "stop_fills": {},
        "companies": {}, "policy": {}, "planned_stops": {}, "cio_status": {},
    })
    protect = [item for item in document["do_now"]["items"] if item["id"].startswith("protection:")]
    assert len(protect) == 1
    assert "not refreshed since 2026-10-28T14:59:00Z" in protect[0]["why"]
    assert "No active broker stop observed" not in protect[0]["why"]


def test_position_adapter_carries_unknown_evidence_and_raw_observation(tmp_path):
    document = truth.resolve(tmp_path, NOW, inputs={
        "holdings": {"as_of": NOW.isoformat(), "generated_at": NOW.isoformat(),
                     "holdings": [{"account": "SyntheticAccountAlpha", "symbol": "SYNTH",
                                   "shares": 1, "price": 110, "market_value": 110,
                                   "day_change": 0}]},
        "broker_stops": [row(None)], "stop_fills": {}, "companies": {}, "policy": {},
        "planned_stops": {}, "cio_status": {},
    })
    payload = truth.positions_payload({"trades": [{"account": "SyntheticAccountAlpha", "symbol": "SYNTH"}]},
                                      document=document)
    trade = payload["trades"][0]
    assert trade["broker_protected"] is False
    assert trade["stop_evidence"]["stale"] is True
    assert trade["stop_observation"]["status"] == "UNAVAILABLE"
    assert trade["stop_note"] == "Stop observation time is unavailable"
    assert trade["stop_status_raw"] == "WORKING"


def test_old_filled_observation_keeps_its_unsettled_sale_warning():
    result = truth.do_now_for([{
        "account_id": "SyntheticAccountAlpha", "account_label": "Synthetic account",
        "symbol": "SYNTH", "market_value": 110, "broker_protected": False,
        "stop_state": "filled", "stop_note": "stop filled; sale not yet checked against the trade ledger",
        "stop_observation": {"status": "STALE", "reason": "Stop not refreshed since the prior observation"},
    }], {"total": 0}, now=NOW)
    assert len(result["items"]) == 1
    assert result["items"][0]["why"] == "Stop filled; sale not yet checked against the trade ledger"


@pytest.mark.parametrize("clock", ["2026-11-04T14:59:00", "2026-11-05T14:59:00Z"])
def test_unavailable_clock_does_not_publish_a_fabricated_observation_age(clock):
    result = truth.stop_for("SyntheticAccountAlpha", "SYNTH",
                            broker_rows=[row(clock)], now=NOW)
    assert result["broker_protected"] is False
    assert result["age_hours"] is None
    assert result["as_of"] is None
    assert result["stop_captured_at"] is None
