"""Isolated quote/account/authorization/broker adapters; never production 2FA."""
import copy
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]

from test_options_workflow import NOW, proposal, quote
from scripts.lib import options_workflow as w
from scripts.lib.options_workflow_accounts import eligibility
from scripts.lib.options_account_resources import project
from scripts.lib.options_validate import refresh_exact
from scripts.lib import options_workflow_service as service
from brokers import options_order_pilot as pilot


def prepared(strategy="long_call", n=1):
    p = proposal(strategy)
    p.update(account="fixture", contracts=n, tif="GTC", analysis_lane="chatgpt", workflow_version=1,
             short_strike=105, long_strike=100, put_strike=95, call_strike=105)
    p["legs"] = [{**quote(l), "occ_symbol": pilot._occ_symbol(l["symbol"], l["expiration"], l["option_type"], l["strike"])}
                 for l in w.proposal_legs(p)]
    p["workflow_economics"] = w.economics(p)
    p["revision"] = w.revision(p)
    return p


def account():
    return {"account_key": "fixture", "broker": "schwab", "display_name": "Fixture IRA",
            "supported_tif": ["DAY", "GTC"], "capabilities": {"verified": True, "options_level": "spreads"},
            "resources": {"as_of": NOW.isoformat(), "buying_power": 100000, "available_cash": 100000,
                          "uncommitted_shares": {"TEST": 500}, "commitments_complete": True, "positions_complete": True}}


def chain(p, age=0):
    rows = [{**l, "symbol": l["occ_symbol"], "side": l["option_type"], "quote_time": (NOW - timedelta(seconds=age)).isoformat()}
            for l in p["legs"]]
    return {"status": "ok", "underlying_price": 100, "underlying_quote_time": NOW.isoformat(),
            "expirations": [{"exp": p["expiration"], "strikes": rows}]}


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch):
    import schwab_transport
    from brokers import approval_service
    def forbidden(*a, **k):
        pytest.fail("Production broker/2FA/DB adapter reached by dry test")
    monkeypatch.setattr(schwab_transport, "get_option_chain", forbidden)
    monkeypatch.setattr(schwab_transport, "get_account", forbidden)
    monkeypatch.setattr(schwab_transport, "get_options_resources", forbidden)
    monkeypatch.setattr(schwab_transport, "place_order", forbidden)
    monkeypatch.setattr(approval_service, "request_approval", forbidden)
    monkeypatch.setattr(service, "query", forbidden)
    monkeypatch.setattr(service, "policy_refusals", lambda *a: [])


@pytest.mark.parametrize("strategy", sorted(w.STRATEGIES))
@pytest.mark.parametrize("n", [1, 3])
def test_each_strategy_same_account_resources_and_leg_quantity(strategy, n):
    p = prepared(strategy, n)
    a = account()
    assert eligibility(p, a, now=NOW)["eligible"]
    a["resources"].update(buying_power=0, available_cash=0, uncommitted_shares={"TEST": 0})
    assert not eligibility(p, a, now=NOW)["eligible"]
    spec = pilot.build_order_spec(p)
    intent = pilot.build_intent("fixture", p)
    assert spec == pilot.order_from_intent(intent)
    assert spec["duration"] == "GTC"
    assert all(l["quantity"] == n for l in spec["orderLegCollection"])


@pytest.mark.parametrize("change,code", [
    ({"capabilities": {"verified": True, "options_level": "none"}}, "strategy_not_permitted"),
    ({"capabilities": {}}, "permissions_unknown"),
    ({"broker": "unsupported"}, "account_unsupported"),
    ({"supported_tif": ["DAY"]}, "tif_unsupported"),
    ({"resources": {}}, "account_resources_stale"),
])
def test_account_name_never_grants_permission(change, code):
    a = {**account(), **change, "display_name": "Fully approved options account"}
    assert code in {r["code"] for r in eligibility(prepared(), a, now=NOW)["refusals"]}


def test_commitments_reduce_same_account_shares_and_cash():
    raw = {"securitiesAccount": {"type": "CASH", "currentBalances": {"cashAvailableForTrading": 20000},
        "positions": [{"longQuantity": 200, "shortQuantity": 0, "instrument": {"assetType": "EQUITY", "symbol": "TEST"}},
                      {"longQuantity": 0, "shortQuantity": 1, "instrument": {"assetType": "OPTION", "symbol": "TEST261120C00105000", "multiplier": 100}}]}}
    orders = [{"status": "WORKING", "remainingQuantity": 1, "quantity": 1,
               "orderLegCollection": [{"quantity": 1, "instruction": "SELL_TO_OPEN",
                 "instrument": {"assetType": "OPTION", "symbol": "TEST261120P00100000", "multiplier": 100}}]}]
    resources = project(raw, orders, as_of=NOW.isoformat())
    assert resources["uncommitted_shares"]["TEST"] == 100
    assert resources["available_cash"] == 10000
    a = {**account(), "resources": resources}
    assert not eligibility(prepared("covered_call", 2), a, now=NOW)["eligible"]
    assert not eligibility(prepared("cash_secured_put", 2), a, now=NOW)["eligible"]
    # Missing reservation evidence cannot be interpreted as zero commitments.
    del raw["securitiesAccount"]["positions"][1]["instrument"]["multiplier"]
    assert not project(raw, orders, as_of=NOW.isoformat())["commitments_complete"]


@pytest.mark.parametrize("age,accepted", [(0, True), (3, True), (3.001, False), (-1, False)])
def test_exact_refresh_uses_provider_time_after_response(age, accepted):
    p = prepared()
    r = refresh_exact(p, chain_fn=lambda *a, **k: chain(p, age), clock=lambda: NOW)
    assert r["ok"] is accepted


def test_slow_http_response_cannot_refresh_old_quote():
    p = prepared()
    r = refresh_exact(p, chain_fn=lambda *a, **k: chain(p), clock=lambda: NOW + timedelta(seconds=4))
    assert not r["ok"] and "quote_stale" in {x["code"] for x in r["refusals"]}


def test_one_bad_leg_refuses_entire_spread():
    p = prepared("credit_spread")
    c = chain(p)
    c["expirations"][0]["strikes"][1]["quote_time"] = None
    r = refresh_exact(p, chain_fn=lambda *a, **k: c, clock=lambda: NOW)
    assert not r["ok"] and any(x["code"] == "quote_timestamp_missing" for x in r["refusals"])


def final(p, intent, quote_reader=None):
    return service.final_validation(intent, p, accounts_reader=lambda: [account()],
        quote_reader=quote_reader or (lambda *a, **k: chain(p)), clock=lambda: NOW,
        revision_writer=lambda *a: {"proposal_id": "fixture-new-revision"},
        review_checker=lambda p, rev, **k: [] if w.revision(p) == rev else [w.refusal("revision_changed", "changed")])


def test_after_2fa_refresh_preserves_authorized_tif_and_limit():
    p = prepared()
    i = pilot.build_intent("fixture", p)
    before = pilot.order_from_intent(i)
    r = final(p, i)
    assert r["ok"] and pilot.order_from_intent(i) == before
    assert i.meta.signal_evidence["final_quote_receipt"]["legs"][0]["quote_time"] == NOW.isoformat()


@pytest.mark.parametrize("field,value", [("account", "tampered"), ("contracts", 2), ("premium", 2.01), ("tif", "DAY")])
def test_edited_proposal_cannot_use_old_confirmation(field, value):
    p = prepared()
    i = pilot.build_intent("fixture", p)
    p[field] = value
    assert not final(p, i)["ok"]


def test_intent_tif_tampering_is_refused():
    from brokers.order_intent import TIF
    p = prepared()
    i = pilot.build_intent("fixture", p)
    i.tif = TIF.DAY
    assert not final(p, i)["ok"]


def test_material_movement_requires_review_and_never_changes_order():
    p = prepared()
    i = pilot.build_intent("fixture", p)
    original = pilot.order_from_intent(i)
    c = chain(p)
    c["expirations"][0]["strikes"][0].update(bid=3, ask=3.1)
    r = final(p, i, quote_reader=lambda *a, **k: c)
    assert not r["ok"] and r["review_required"] and r["material_changes"]
    assert pilot.order_from_intent(i) == original


def test_dry_receipts_cannot_enter_fill_evidence():
    from options_fill_evidence import _validate_identity
    with pytest.raises(ValueError, match="Dry-test"):
        _validate_identity({"environment": "dry_test", "broker_execution_id": "fake"}, "fixture", False)


def test_dry_authorization_simulation_has_no_production_calls():
    p = prepared()
    calls = []
    def fake_authorize(order):
        calls.append("fake_authorization")
        return {"ok": True, "binding": w.digest(order), "environment": "dry_test"}
    def fake_broker(order, receipt):
        assert receipt["binding"] == w.digest(order)
        calls.append("fake_broker")
        return {"environment": "dry_test", "transmitted": False, "message": "DRY RUN ONLY — no order transmitted."}
    order = pilot.build_order_spec(p)
    result = fake_broker(order, fake_authorize(order))
    assert calls == ["fake_authorization", "fake_broker"] and not result["transmitted"]


def test_expiry_table_matches_long_call_arithmetic_without_fixed_market_facts():
    p = prepared()
    p.update(strike=120, underlying_price=167.78, premium=65.23, expiration="2027-12-17",
             legs=[], directive={"thesis_target": 300}, scenario_prices=[120, 150, 167.78, 185.23, 200, 250, 300])
    p["legs"] = [quote(l) for l in w.proposal_legs(p)]
    e = w.economics(p)
    flat = next(r for r in e["scenarios"] if r["label"] == "flat")
    target = next(r for r in e["scenarios"] if r["label"] == "recorded target")
    assert flat["option_pl"] == -1745 and flat["option_expiry_value"] == 4778 and flat["stock_return_pct"] == 0
    assert target["option_expiry_value"] == 18000 and target["option_pl"] == 11477
    assert e["breakevens"] == [185.23]
    assert "not before-expiry price forecasts" in e["before_expiry_note"]


def test_model_wait_quote_refresh_keeps_reviewed_order_and_analysis(monkeypatch):
    p = prepared()
    events = []
    import schwab_transport
    import scripts.lib.options_thesis as thesis
    from types import SimpleNamespace
    monkeypatch.setattr(schwab_transport, "get_option_chain", lambda *a, **k: chain(p))
    monkeypatch.setattr(service, "refresh_exact", lambda value, **k: refresh_exact(value, **k, clock=lambda: NOW))
    monkeypatch.setattr(thesis, "OptionsThesisStore", lambda: SimpleNamespace(append_event=lambda *a, **k: events.append(k)))
    p["option_strategy_guid"] = "fixture-guid"
    p["revision"] = w.revision(p)
    refreshed = service.refresh_review_quotes(p)
    assert refreshed["ok"] and events
    assert refreshed["proposal"]["revision"] == w.revision(p)
    assert w.analysis_binding(refreshed["proposal"]) == w.analysis_binding(p)
    assert pilot.build_order_spec(refreshed["proposal"]) == pilot.build_order_spec(p)


def test_subcent_limit_is_never_silently_changed():
    p = prepared()
    p["premium"] = 2.005
    with pytest.raises(ValueError, match="exact cent"):
        pilot.build_order_spec(p)


def test_ambiguous_import_is_data_blocked_with_good_quotes():
    import options_lifecycle_engine as engine
    result = engine.decide({"strategy_type": "unknown_multi_leg"}, {"flags": []}, {})
    assert result["recommendation"] == "DATA_BLOCKED"
