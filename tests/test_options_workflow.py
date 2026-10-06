"""Pure workflow contracts: no DB, broker, credentials, authorization or model calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib import options_workflow as w

NOW = datetime(2026, 10, 5, 15, tzinfo=timezone.utc)


def proposal(strategy="covered_call", **changes):
    return dict(id="fixture", symbol="TEST", underlying="TEST", strategy=strategy,
                strike=100, expiration="2026-11-20", option_type="call", contracts=1,
                premium=2, underlying_price=100, multiplier=100, dte=46,
                options_thesis={"pin": "fixture-thesis@v1"}, **changes)


def quote(leg, **changes):
    return dict(leg, bid=1.9, ask=2.0, quote_time=NOW.isoformat(),
                volume=120, oi=500, iv=25, delta=.5, gamma=.03, theta=-.02,
                vega=.1, rho=.02, multiplier=100, nonstandard=False, **changes)


@pytest.mark.parametrize("value", [0, -1, 1.5, "1.5", None, True, "NaN", float("inf")])
def test_invalid_quantity_never_coerced(value):
    with pytest.raises(ValueError):
        w.quantity(value)


@pytest.mark.parametrize("strategy,count", [(s, 2 if s in {"credit_spread", "debit_spread", "collar"} else 1)
                                            for s in w.STRATEGIES])
def test_all_strategy_leg_quantities(strategy, count):
    p = proposal(strategy)
    p.update(short_strike=105, long_strike=100, put_strike=95, call_strike=105)
    legs = w.proposal_legs(p, 3)
    assert len(legs) == count
    assert all(l["quantity"] == 3 for l in legs)
    if strategy == "cash_secured_put":
        assert legs[0]["side"] == "SELL" and legs[0]["option_type"] == "put"
    if strategy == "protective_put":
        assert legs[0]["side"] == "BUY" and legs[0]["option_type"] == "put"


@pytest.mark.parametrize("age,ok", [(0, True), (3, True), (3.001, False), (-.001, False), (30, False)])
def test_three_second_provider_clock(age, ok):
    leg = w.proposal_legs(proposal(), 1)[0]
    q = quote(leg)
    q["quote_time"] = (NOW - timedelta(seconds=age)).isoformat()
    q["received_at"] = NOW.isoformat()  # a new response never rescues an old price
    assert (not w.quote_refusals([q], now=NOW)) is ok


def test_stale_one_leg_and_missing_timestamp_refuse():
    legs = w.proposal_legs(proposal("credit_spread", short_strike=100, long_strike=95), 1)
    qs = [quote(l) for l in legs]
    qs[1]["quote_time"] = None
    qs[1]["trade_time"] = NOW.isoformat()
    assert any(r["code"] == "quote_timestamp_missing" for r in w.quote_refusals(qs, now=NOW))


@pytest.mark.parametrize("changes", [{"bid": 3}, {"ask": None}, {"volume": -1}, {"volume": .5},
                                    {"volume": None}, {"volume": float("nan")}])
def test_bad_prices_and_volume_refuse(changes):
    q = quote(w.proposal_legs(proposal(), 1)[0])
    q.update(changes)
    assert w.quote_refusals([q], now=NOW)


def test_account_quantity_limit_tif_and_versions_all_change_revision():
    p = proposal()
    p.update(account="fixture-a", tif="DAY", legs=w.proposal_legs(p, 1))
    for key, val in [("account", "fixture-b"), ("contracts", 2), ("premium", 2.1), ("tif", "GTC"),
                     ("directive_version", "v2"), ("options_thesis", {"pin": "v2"})]:
        changed = deepcopy(p)
        changed[key] = val
        assert w.revision(p) != w.revision(changed), key


def test_adjusted_multiplier_scales_greeks_and_position_not_contract_count():
    p = proposal("long_call")
    legs = w.proposal_legs(p, 3)
    q = quote(legs[0])
    q["multiplier"] = 10
    p.update(contracts=3, legs=[q], fees_total=1.5)
    e = w.economics(p)
    assert e["premium_total"] == 60
    assert e["max_loss"] == 61.5
    assert e["greeks"]["delta"] == 15
    assert e["per_contract"]["premium_total"] == 20
    assert e["early_assignment_probability"] is None


def test_unknown_greek_never_zero():
    p = proposal("long_call")
    p["legs"] = [quote(w.proposal_legs(p, 1)[0])]
    p["legs"][0]["rho"] = None
    assert w.economics(p)["greeks"]["rho"] is None


def test_covered_call_scenarios_separate_option_and_stock():
    p = proposal()
    p["legs"] = [quote(w.proposal_legs(p, 1)[0])]
    e = w.economics(p)
    high = next(s for s in e["scenarios"] if s["underlying_price"] == 120)
    assert high["option_pl"] == -1800
    assert high["combined_pl"] == 200


def test_analysis_requires_completed_bound_lane_and_disposition():
    p = proposal()
    p.update(account="fixture-a", tif="DAY", analysis_lane="fixture-lane")
    assert w.analysis_refusals(p, None, now=NOW)
    result = {"status": "completed", "lane": "fixture-lane", "binding": w.analysis_binding(p),
              "id": "analysis-fixture", "created_at": NOW.isoformat(), "objections": []}
    assert w.analysis_refusals(p, result, now=NOW) == []
    result["objections"] = ["Review dividend risk"]
    assert w.analysis_refusals(p, result, now=NOW)
    p["analysis_disposition"] = {"analysis_id": result["id"], "cio_decision_ref": "fixture-cio",
                                "note": "Dividend risk reviewed", "binding": result["binding"]}
    assert not w.analysis_refusals(p, result, now=NOW)
    p["contracts"] = 2
    assert w.analysis_refusals(p, result, now=NOW)


@pytest.mark.parametrize("delta", [{"ratio": 2}, {"side": "SELL"}, {"option_type": "put"}])
def test_strategy_shape_cannot_change_through_legs(delta):
    p = proposal("long_call")
    p["legs"] = [{**quote(w.proposal_legs(p)[0]), **delta}]
    with pytest.raises(ValueError):
        w.proposal_legs(p)


def test_fee_and_legacy_risk_totals_scale_with_quantity():
    p = proposal("long_call")
    p["legs"] = [quote(w.proposal_legs(p)[0])]
    p.update(fees_total=.65, fees_basis_contracts=1, contracts=3)
    e = w.stamp_economics(p)
    assert e["fees_total"] == pytest.approx(1.95)
    assert p["max_loss"] == pytest.approx(601.95)
    assert p["economics"]["cash_committed"] == pytest.approx(601.95)


@pytest.mark.parametrize("status,age,code", [("budget_refused", 0, "analysis_required"),
    ("completed", 86401, "analysis_stale"), ("completed", -1, "analysis_stale")])
def test_unusable_or_expired_analysis_never_passes(status, age, code):
    p = proposal()
    p["analysis_lane"] = "chatgpt"
    result = {"status": status, "id": "fixture", "lane": "chatgpt", "binding": w.analysis_binding(p),
              "created_at": (NOW - timedelta(seconds=age)).isoformat()}
    assert w.analysis_refusals(p, result, now=NOW)[0]["code"] == code
