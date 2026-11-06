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


def row(clock, status="WORKING", symbol="SYNTH"):
    return {"account": "SyntheticAccountAlpha", "symbol": symbol,
            "order_id": "synthetic-stop-one", "status": status,
            "stop_price": 100, "qty": 1, "captured_at": clock}


def holdings(*specs):
    """specs: (account, symbol, shares, price, market_value)."""
    return {"as_of": NOW.isoformat(), "generated_at": NOW.isoformat(),
            "holdings": [{"account": account, "symbol": symbol, "shares": shares, "price": price,
                          "market_value": market_value, "day_change": 0}
                         for account, symbol, shares, price, market_value in specs]}


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
    # The same unusable observation is not a definite "unprotected" claim either.
    assert document["stops"]["unprotected_count"] is None
    assert document["positions"]["unprotected_value_usd"] is None
    # It is published as the unproven set instead.
    assert document["stops"]["unproven_count"] == 1
    assert document["positions"]["unproven_value_usd"] == 110.0


def test_stale_resting_stop_is_unproven_not_a_definite_unprotected_figure(tmp_path):
    """A stale stop read says WORKING with a stop at $100; the evidence is old, not absent.

    Mirrors the four nulled heat figures: unknown evidence must not become a definite unprotected count or
    dollar figure under the Risk panel's "Value without active protection".
    """
    document = truth.resolve(tmp_path, NOW, inputs={
        "holdings": {"as_of": NOW.isoformat(), "generated_at": NOW.isoformat(),
                     "holdings": [{"account": "SyntheticAccountAlpha", "symbol": "SYNTH",
                                   "shares": 100, "price": 110, "market_value": 11000,
                                   "day_change": 0}]},
        "broker_stops": [row("2026-10-28T14:59:00Z")], "stop_fills": {},
        "companies": {}, "policy": {}, "planned_stops": {}, "cio_status": {},
    })
    position = document["positions"]["rows"][0]
    assert position["broker_protected"] is False
    assert position["stop_state"] == "unknown"
    assert position["stop_state_observed"] == "active"
    assert position["stop_observation"]["status"] == "STALE"
    # Not a definite all-clear and not a definite "unprotected" figure.
    assert document["stops"]["unprotected_count"] is None
    assert document["positions"]["unprotected_value_usd"] is None
    # The unproven set is published on its own.
    assert document["stops"]["unproven_count"] == 1
    assert document["positions"]["unproven_value_usd"] == 11000.0
    # Same standard as the four siblings the PR already nulls.
    assert document["positions"]["loss_at_stop_usd"] is None
    assert document["positions"]["portfolio_heat_pct"] is None
    assert document["positions"]["loss_at_resting_stops_usd"] is None
    assert document["positions"]["resting_heat_pct"] is None


def test_unproven_position_is_excluded_from_the_definite_unprotected_figures(tmp_path):
    """An unmapped broker stop state is unproven, not unprotected: the definite figures cover only the rest."""
    document = truth.resolve(tmp_path, NOW, inputs={
        "holdings": holdings(
            ("SyntheticAccountAlpha", "SYNTH", 100, 110, 11000),
            ("SyntheticAccountAlpha", "NOSP", 50, 100, 5000)),
        "broker_stops": [row("2026-11-04T14:59:00Z", status="SOME_UNMAPPED_STATE")],
        "stop_fills": {}, "companies": {}, "policy": {}, "planned_stops": {}, "cio_status": {},
    })
    unproven, no_stop = document["positions"]["rows"]
    assert unproven["stop_state"] == "unknown"
    assert unproven["stop_observation"]["status"] == "FRESH"  # the time is current; the state is unmapped
    assert no_stop["stop_state"] == "none"
    # A current observation means no whole-book uncertainty: the definite figures still publish, excluding the
    # unproven row instead of counting it as unprotected.
    assert document["stops"]["unprotected_count"] == 1
    assert document["positions"]["unprotected_value_usd"] == 5000.0
    assert document["stops"]["unproven_count"] == 1
    assert document["positions"]["unproven_value_usd"] == 11000.0


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


# ---- codex-cloud P1 (BLOCK a6402008e): a value the unprotected figure excludes must not reappear as protected ---
def _unproven_document(tmp_path):
    """One $11,000 holding whose broker stop carries a status nothing maps: unproven, not protected."""
    return truth.resolve(tmp_path, NOW, inputs={
        "holdings": {"as_of": NOW.isoformat(), "generated_at": NOW.isoformat(),
                     "holdings": [{"account": "SyntheticAccountAlpha", "symbol": "SYNTH",
                                   "shares": 100, "price": 110, "market_value": 11000,
                                   "day_change": 0}]},
        "broker_stops": [row("2026-11-04T14:59:00Z", status="MYSTERY")],
        "stop_fills": {}, "companies": {}, "policy": {}, "planned_stops": {}, "cio_status": {},
    })


def test_an_unproven_holding_is_not_counted_as_protected_value(tmp_path):
    document = _unproven_document(tmp_path)
    assert document["positions"]["unprotected_value_usd"] == 0
    assert document["positions"]["unproven_value_usd"] == 11000

    payload = truth.risk_payload(document=document)

    assert payload["total_protected_mv"] == 0, "an unproven holding was counted as protected value"
    assert payload["pct_protected"] == 0
    assert payload["total_unproven_mv"] == 11000, "the unproven value must be stated, not absorbed"


def test_an_unknown_unproven_figure_leaves_the_protected_total_unstated(tmp_path):
    """Protected is derived: if any part of the subtraction is unknown, the figure is not stated."""
    document = _unproven_document(tmp_path)
    document["positions"]["unproven_value_usd"] = None
    payload = truth.risk_payload(document=document)
    assert payload["total_protected_mv"] is None
    assert payload["pct_protected"] is None


def test_a_fully_proven_portfolio_still_reports_its_split(tmp_path):
    """Positive control: with nothing unproven, protected is still total minus unprotected."""
    document = truth.resolve(tmp_path, NOW, inputs={
        "holdings": {"as_of": NOW.isoformat(), "generated_at": NOW.isoformat(),
                     "holdings": [{"account": "SyntheticAccountAlpha", "symbol": "SYNTH",
                                   "shares": 10, "price": 100, "market_value": 1000, "day_change": 0},
                                  {"account": "SyntheticAccountAlpha", "symbol": "BETA",
                                   "shares": 5, "price": 50, "market_value": 250, "day_change": 0}]},
        "broker_stops": [row("2026-11-04T14:59:00Z")],
        "stop_fills": {}, "companies": {}, "policy": {}, "planned_stops": {}, "cio_status": {},
    })
    assert document["positions"]["unproven_value_usd"] == 0
    payload = truth.risk_payload(document=document)
    assert payload["total_protected_mv"] == 1000
    assert payload["pct_protected"] == 80.0


# ---- cx-openai D52 triage (#2677): risk uncertainty must cover what the monetary total covers ----
FRESH_CLOCK = "2026-11-04T14:59:00Z"
STALE_CLOCK = "2026-10-28T14:59:00Z"


def _risk_document(tmp_path, specs, stop_rows):
    return truth.resolve(tmp_path, NOW, inputs={
        "holdings": holdings(*specs), "broker_stops": stop_rows, "stop_fills": {},
        "companies": {}, "policy": {}, "planned_stops": {}, "cio_status": {},
    })


def test_a_book_of_only_sub_100_positions_does_not_publish_zero_risk(tmp_path):
    """The loss sum covered every position, the uncertainty guard only the >= $100 ones. A book whose positions are
    all smaller than that produced an empty loss list — and `all([])` is True — so a stale stop set published
    loss_at_stop_usd 0.0 and portfolio_heat_pct 0.0: a zero-risk figure nobody had observed."""
    document = _risk_document(tmp_path, [("SyntheticAccountAlpha", "SML", 0.5, 110, 55.0)],
                              [row(STALE_CLOCK, symbol="SML")])
    section = document["positions"]
    assert section["rows"][0]["broker_protected"] is False
    assert section["loss_at_stop_usd"] is None, section["loss_at_stop_usd"]
    assert section["portfolio_heat_pct"] is None, section["portfolio_heat_pct"]


def test_a_measured_protected_position_still_publishes_its_loss(tmp_path):
    document = _risk_document(tmp_path, [("SyntheticAccountAlpha", "BIG", 100, 110, 11000.0)],
                              [row(FRESH_CLOCK, symbol="BIG")])
    section = document["positions"]
    assert section["rows"][0]["broker_protected"] is True
    assert section["loss_at_stop_usd"] == 1000.0, section["loss_at_stop_usd"]
    assert section["portfolio_heat_pct"] is not None


def test_a_stale_small_position_also_makes_the_whole_risk_block_unknown(tmp_path):
    """The same rule whether or not the position clears the $100 counting threshold: a stale observation anywhere in
    the book means the risk figures are not fully measured, so they are withheld rather than published as the
    measured subset (which would read as the whole book)."""
    document = _risk_document(tmp_path,
                              [("SyntheticAccountAlpha", "BIG", 100, 110, 11000.0),
                               ("SyntheticAccountAlpha", "SML", 0.5, 110, 55.0)],
                              [row(FRESH_CLOCK, symbol="BIG"), row(STALE_CLOCK, symbol="SML")])
    assert document["positions"]["loss_at_stop_usd"] is None
    assert document["positions"]["portfolio_heat_pct"] is None


def test_a_cash_only_book_is_zero_risk_not_unknown(tmp_path):
    """Nothing is held, so nothing can be lost at a stop: 0 is the measured answer here, not a stand-in for unknown."""
    document = truth.resolve(tmp_path, NOW, inputs={
        "holdings": {"as_of": NOW.isoformat(), "generated_at": NOW.isoformat(),
                     "holdings": [{"account": "SyntheticAccountAlpha", "symbol": "CASH", "is_cash": True,
                                   "shares": 1000, "price": 1, "market_value": 1000, "day_change": 0}]},
        "broker_stops": [], "stop_fills": {}, "companies": {}, "policy": {}, "planned_stops": {}, "cio_status": {},
    })
    assert document["positions"]["rows"] == []
    assert document["positions"]["loss_at_stop_usd"] == 0.0
