"""Prospectus stop plan (operator 2026-10-26: "it should also recommend what the stops are").

The house recommended stop (persisted protection advisory within the stop policy band) beside the broker stop and
its state, read the way the Risk page reads it (cio_truth.stop_for over stop_last_known). Synthetic tickers,
accounts and prices only (public repo). No DB, no token store, no broker, no network; nothing is written.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import generate as gen  # noqa: E402
from scripts.lib.prospectus import render, stops  # noqa: E402
from scripts.lib.prospectus.inputs import Bundle  # noqa: E402

NOW = datetime(2026, 10, 26, 18, tzinfo=timezone.utc)
AT = "2026-10-26T17:10:00+00:00"
BAND = {"family": "fixture_tier", "family_source": "fixture", "label": "Fixture", "stop_min_pct": 5.0,
        "stop_max_pct": 10.0, "trail_min_pct": 6.0, "trail_max_pct": 10.0, "regime": "neutral"}
HOLDING = {"shares": 10.0, "market_value": 1000.0, "accounts": ["fixture_ira", "fixture_brokerage"]}


class Src:
    def __init__(self, rows=(), advisory=None, planned=None, db_error=False):
        self.rows, self.advisory, self.planned, self.db_error = list(rows), advisory, planned or {}, db_error

    def broker_stop_rows(self, sym):
        if self.db_error:
            return None
        return [r for r in self.rows if r["symbol"] == sym]

    def protection_advisory(self, sym):
        return self.advisory

    def planned_stops(self):
        return self.planned


def _row(status, price=90.0, account="fixture_ira", order="o1", sym="ZZST"):
    return {"account": account, "symbol": sym, "order_id": order, "stop_price": price, "qty": 10, "status": status,
            "captured_at": AT}


def _adv(level=92.0, created="2026-10-24T12:00:00+00:00", **kw):
    return {"stop_price": level, "trail_recommended": False, "trail_type": None, "trail_offset": None,
            "family": "fixture_tier", "family_bounds": {}, "sanity": "ok", "created_at": created, "model": "fixture",
            **kw}


def _bundle(sym="ZZST", scope="holding", last=100.0, atr=2.0):
    b = Bundle(symbol=sym, scope=scope, name="Fixture Stop Co")
    b.add("price", "Last close", value=last, unit="$", source="fixture", as_of="2026-10-26")
    b.blocks["risk_technicals"] = {"atr20": atr}
    return b


def _build(src, b=None, holding=HOLDING, monkeypatch=None):
    b = b or _bundle()
    if monkeypatch is not None:
        monkeypatch.setattr(stops, "policy_band", lambda *a, **k: dict(BAND))
    return b, stops.build(src, b, holding=holding, cfg={}, now=NOW, regime="neutral")


def test_contract_shape_and_house_level(monkeypatch):
    b, plan = _build(Src([_row("WORKING", 88.0)], advisory=_adv()), monkeypatch=monkeypatch)
    assert set(plan) == {"recommended", "broker", "comparison", "advisory", "gaps"}
    rec, broker = plan["recommended"], plan["broker"]
    assert {"level", "method", "distance_pct", "usd_at_risk", "policy", "as_of"} <= set(rec)
    assert {"level", "state", "as_of", "source"} <= set(broker)
    assert rec["level"] == 92.0 and rec["distance_pct"] == 8.0 and rec["usd_at_risk"] == 80.0
    assert "holding_protection_advisor" in rec["policy"] and "Fixture band 5–10% below" in rec["method"]
    assert rec["band"]["levels"] == [90.0, 95.0]
    assert broker["state"] == "active" and broker["level"] == 88.0
    assert plan["comparison"] == "Active broker stop $88.00 sits 4.3% below the house level $92.00."
    assert plan["advisory"] == "advisory — no AI places, sizes or stops orders" and plan["gaps"] == []
    tile = b.blocks["verdict_tiles"]["stop"]
    assert tile == {"value": "$88.00", "sub": "active · house $92.00", "tone": "success"}
    labels = {f["label"]: f for f in b.facts}
    assert labels["House recommended stop level (advisory)"]["value"] == 92.0
    assert labels["Dollars at risk at the house stop $"]["value"] == 80.0
    assert labels["Broker stop state"]["text"].startswith("active:")


def test_states_match_risk_categories(monkeypatch):
    cases = {"pending_activation": ("resting", "$90.00", "resting, pending activation · house $92.00"),
             "FILLED": ("filled", "Filled", "broker stop filled · house $92.00"),
             "awaiting_stop_condition": ("unknown", "$90.00", "state not reported · house $92.00")}
    for status, (state, value, sub) in cases.items():
        b, plan = _build(Src([_row(status)], advisory=_adv()), monkeypatch=monkeypatch)
        assert plan["broker"]["state"] == state, status
        assert (b.blocks["verdict_tiles"]["stop"]["value"], b.blocks["verdict_tiles"]["stop"]["sub"]) == (value, sub)
    # replaced / cancelled observations are dead, exactly as on Risk
    b, plan = _build(Src([_row("REPLACED")], advisory=_adv()), monkeypatch=monkeypatch)
    assert plan["broker"]["state"] == "none"
    assert b.blocks["verdict_tiles"]["stop"] == {"value": "None", "sub": "no broker stop on record · house $92.00",
                                                 "tone": "danger"}
    assert plan["comparison"] == "No resting broker stop; the house level is $92.00, 8.0% below the last close."


def test_strongest_state_wins_across_accounts_and_names_only(monkeypatch):
    rows = [_row("FILLED", 85.0, account="fixture_ira", order="a"),
            _row("pending_activation", 89.0, account="fixture_brokerage", order="b")]
    b, plan = _build(Src(rows, advisory=_adv()), monkeypatch=monkeypatch)
    assert plan["broker"]["state"] == "resting" and plan["broker"]["level"] == 89.0
    assert sorted(a["state"] for a in plan["broker"]["accounts"]) == ["filled", "resting"]
    assert all(not any(ch.isdigit() for ch in a["account"]) for a in plan["broker"]["accounts"])
    assert "Other accounts:" in plan["comparison"] and "filled $85.00" in plan["comparison"]
    assert "other accounts:" in b.blocks["verdict_tiles"]["stop"]["sub"]
    # a stop on record without a reported state still outranks a fill elsewhere (it may still be working)
    rows = [_row("FILLED", 85.0, account="fixture_ira", order="a"),
            _row("awaiting_stop_condition", 95.0, account="fixture_brokerage", order="b")]
    _, plan = _build(Src(rows, advisory=_adv()), monkeypatch=monkeypatch)
    assert plan["broker"]["state"] == "unknown" and plan["broker"]["level"] == 95.0


def test_planned_level_is_not_a_broker_order(monkeypatch):
    planned = {"ZZST:fixture_ira": {"account": "fixture_ira", "stop": 87.0, "set_date": "2026-10-01"}}
    b, plan = _build(Src([], advisory=_adv(), planned=planned), monkeypatch=monkeypatch)
    assert plan["broker"]["state"] == "none" and plan["broker"]["level"] == 87.0
    assert "not a broker order" in plan["broker"]["source"]
    assert b.blocks["verdict_tiles"]["stop"]["sub"].startswith("planned level, no broker order")


def test_missing_stale_and_failed_advisories_withhold_the_level(monkeypatch):
    _, plan = _build(Src([_row("WORKING")], advisory=None), monkeypatch=monkeypatch)
    assert plan["recommended"]["level"] is None and plan["recommended"]["method"] == "Fixture band 5–10% below"
    assert any("no house stop advisory" in g for g in plan["gaps"])
    assert plan["comparison"] == "Broker stop $90.00 (active); no current house level to compare."
    _, plan = _build(Src([], advisory=_adv(created="2026-08-01T00:00:00+00:00")), monkeypatch=monkeypatch)
    assert plan["recommended"]["level"] is None and plan["recommended"]["stale_level"] == 92.0
    assert any("days old" in g for g in plan["gaps"])
    _, plan = _build(Src([], advisory=_adv(sanity="fail")), monkeypatch=monkeypatch)
    assert plan["recommended"]["level"] is None and any("sanity" in g for g in plan["gaps"])


def test_out_of_band_and_above_price_are_flagged(monkeypatch):
    _, plan = _build(Src([], advisory=_adv(level=70.0)), monkeypatch=monkeypatch)
    assert plan["recommended"]["distance_pct"] == 30.0 and any("outside the current policy band" in g for g in plan["gaps"])
    _, plan = _build(Src([], advisory=_adv(level=101.0)), monkeypatch=monkeypatch)
    assert plan["recommended"]["usd_at_risk"] == 0.0 and any("at or above the last close" in g for g in plan["gaps"])


def test_trailing_method_names_the_trail(monkeypatch):
    _, plan = _build(Src([], advisory=_adv(trail_recommended=True, trail_type="PERCENT", trail_offset=8.0)),
                     monkeypatch=monkeypatch)
    assert plan["recommended"]["method"].startswith("trailing 8% (initial stop $92.00)")


def test_store_unreadable_is_unknown_not_none(monkeypatch):
    b, plan = _build(Src(db_error=True, advisory=_adv()), monkeypatch=monkeypatch)
    assert plan["broker"]["state"] == "unknown" and "broker stop store unreadable" in plan["gaps"]
    assert b.blocks["verdict_tiles"]["stop"]["value"] == "Unknown"


def test_watch_names_are_not_applicable_and_tiles_kept():
    b = _bundle(scope="watch")
    b.blocks["verdict_tiles"] = {"verdict": {"value": "HOLD"}}
    assert stops.build(Src(), b, holding=None, now=NOW) == {"not_applicable": "not held"}
    assert b.blocks["verdict_tiles"] == {"verdict": {"value": "HOLD"}}


def test_existing_verdict_tile_is_preserved(monkeypatch):
    b = _bundle()
    b.blocks["verdict_tiles"] = {"verdict": {"value": "ADD", "sub": "CIO conviction 60/100"}}
    _build(Src([_row("WORKING")], advisory=_adv()), b=b, monkeypatch=monkeypatch)
    assert set(b.blocks["verdict_tiles"]) == {"verdict", "stop"}


def test_policy_band_reads_the_house_stop_policy():
    band = stops.policy_band("ZZST", atr_pct=1.0, position_value=None, regime="neutral")
    assert band is not None and band["stop_min_pct"] < band["stop_max_pct"]


def test_writer_cannot_alter_the_level(monkeypatch):
    """The level is a fact; a sentence with a different stop number is dropped by the grounding guard."""
    b, _ = _build(Src([_row("WORKING", 88.0)], advisory=_adv()), monkeypatch=monkeypatch)
    log = []
    kept = gen.guard_text("The house stop sits at $92.00 [F2]. A better stop would be $83.50.", gen.allowed_values(b),
                          where="position_and_plan", log=log)
    assert "$92.00" in kept and "83.50" not in kept and log


def test_renderers_show_the_stop_plan(monkeypatch):
    b, plan = _build(Src([_row("WORKING", 88.0)], advisory=_adv()), monkeypatch=monkeypatch)
    doc = {"symbol": "ZZST", "name": "Fixture Stop Co", "scope": "holding", "facts": b.facts,
           "blocks": {"stop_plan": plan}, "sections": [], "charts": []}
    html = render.html(doc)
    assert "Stop plan · house policy vs broker" in html and "advisory — no AI places, sizes or stops orders" in html
    assert stops.stop_plan_table({"blocks": {"stop_plan": {"not_applicable": "not held"}}}) == []
