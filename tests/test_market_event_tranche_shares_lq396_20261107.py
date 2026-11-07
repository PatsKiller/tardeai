"""LQ-20261107-396: a 0-share tranche must not be counted as dollars the brief can deploy.

MEASURED 2026-11-07 (cc-opus-2 LQ-380 go-live verify, proposal P1).  On the two small accounts
(Alpaca $5,000, moomoo $525) the 30/30/40 split lands under one share for most names: the tranche
carries $2.88 to $77 of budget and ``shares = floor(usd / entry_high) = 0``.  ``consumer_view``
summed every ready tranche's ``usd`` into ``plan.accounts[].tranche_usd``, and the brief's
``next_tranche_by_account`` summed that into "NEXT TRANCHE $ (READY names)" — so the line promised
money that cannot buy a single share once a name goes READY.

The fix is in the producer, not the brief: the dollars a 0-share tranche carries are excluded from
``tranche_usd`` and reported as ``below_one_share`` beside it, and the account row is still emitted
(never silently dropped — a missing account reads as "nothing to do", which is a different claim
from "nothing you can buy").

Synthetic fixtures only: invented labels, invented cash, SYNTH_* symbols.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import market_event_brief as meb  # noqa: E402
from lib import market_event_api as api  # noqa: E402

PRICE = 77.0  # one share at this entry_high costs exactly one tranche dollar-for-dollar


def _leg(n: int, usd: float | None, shares, *, ready: bool = True, price: float = PRICE) -> dict:
    return {"tranche": n, "pct": 30.0, "usd": usd, "shares": shares, "ready": ready,
            "entry_zone": [round(price - 1.0, 2), price], "trigger": "name gate"}


def _account(label: str, legs: list[dict], *, symbol: str = "SYNTH_B") -> dict:
    return {"account_label": label, "risk_budget_per_name_usd": 200.0,
            "names": [{"symbol": symbol, "invalidation": 52.4, "tranches": legs}]}


def _doc(accounts: list[dict], *, ready: int = 1, symbol: str = "SYNTH_B") -> dict:
    return {
        "market_gate": {"evaluated": True, "passed": False, "tier": "RED", "score": 61,
                        "primary": {"score_falling": False}, "confirmations": []},
        "episode": {"episode_id": "broad_selloff:market:2026-11-04", "kind": "broad_selloff",
                    "scope": "market", "state": "OPEN", "baseline_date": "2026-11-04"},
        "accounts": accounts,
        "candidates": [{"symbol": symbol, "rank": 1, "state": "READY", "tranches_ready": ready,
                        "reason_evidence": {"sector": "Technology"}}],
    }


def _row(doc: dict, symbol: str = "SYNTH_B", *, index: int = 0) -> dict:
    return doc["candidates"][0]["plan"]["accounts"][index]


# ── the 1-share boundary ─────────────────────────────────────────────────────────


def test_the_one_share_boundary_is_counted_and_one_cent_under_is_not():
    """usd == entry_high buys exactly 1 share; a cent less buys 0 and is not deployable dollars."""
    doc = api.consumer_view(_doc([_account("Small", [_leg(1, PRICE - 0.01, 0),
                                                     _leg(2, PRICE, 1)])]))
    plan = doc["candidates"][0]["plan"]
    legs = {x["n"]: x for x in plan["tranches"]}
    assert legs[1]["below_one_share"] is True
    assert legs[2]["below_one_share"] is False
    row = _row(doc)
    assert row["tranche_usd"] == PRICE              # only the tranche that buys a share
    assert row["tranches"] == [2]
    assert row["shares"] == 1
    # the excluded dollars are reported, not deleted
    assert row["below_one_share"] is True
    assert row["below_one_share_usd"] == round(PRICE - 0.01, 2)
    assert row["below_one_share_tranches"] == [1]
    assert row["below_one_share_label"] == "below one share"


def test_an_account_with_only_zero_share_tranches_keeps_its_row():
    """Never silently drop the account: $0 and a label, not a missing line."""
    doc = api.consumer_view(_doc([_account("Micro", [_leg(1, 2.88, 0), _leg(2, 3.10, 0)])], ready=2))
    row = _row(doc)
    assert row["account_label"] == "Micro"
    assert row["tranche_usd"] == 0.0
    assert row["tranches"] == []
    assert row["shares"] is None                   # no buyable shares, not a false "0 sh" total
    assert row["below_one_share"] is True
    assert row["below_one_share_usd"] == 5.98
    assert row["below_one_share_tranches"] == [1, 2]
    assert row["below_one_share_label"] == api.BELOW_ONE_SHARE


def test_all_buyable_tranches_are_unchanged():
    doc = api.consumer_view(_doc([_account("Main", [_leg(1, 600.0, 10), _leg(2, 600.0, 10)])], ready=2))
    row = _row(doc)
    assert row["tranche_usd"] == 1200.0 and row["tranches"] == [1, 2] and row["shares"] == 20
    assert row["below_one_share"] is False
    assert row["below_one_share_usd"] == 0.0
    assert row["below_one_share_tranches"] == []
    assert row["below_one_share_label"] is None


# ── what counts, and what does not ──────────────────────────────────────────────


def test_a_waiting_zero_share_tranche_is_labelled_on_the_leg_but_adds_no_dollars():
    doc = api.consumer_view(_doc([_account("Small", [_leg(1, PRICE, 1), _leg(2, 3.10, 0, ready=False)])]))
    plan = doc["candidates"][0]["plan"]
    assert {x["n"]: x["below_one_share"] for x in plan["tranches"]} == {1: False, 2: True}
    row = _row(doc)
    assert row["tranche_usd"] == PRICE             # the waiting tranche contributes nothing either way
    assert row["below_one_share_usd"] == 0.0       # only READY tranches can be below one share
    assert row["below_one_share"] is False


def test_an_unknown_share_count_is_not_treated_as_zero():
    """None means the engine did not compute shares; assuming 0 would understate deployable dollars."""
    doc = api.consumer_view(_doc([_account("Small", [_leg(1, 40.0, None)])]))
    row = _row(doc)
    assert row["tranche_usd"] == 40.0
    assert row["shares"] is None                   # the total is unknown, not a confident "0 sh"
    assert row["below_one_share"] is False
    assert row["below_one_share_label"] is None
    assert doc["candidates"][0]["plan"]["tranches"][0]["below_one_share"] is False


def test_a_known_share_count_still_totals_when_another_leg_is_known_zero():
    doc = api.consumer_view(_doc([_account("Small", [_leg(1, 40.0, 2), _leg(2, 3.10, 0)])], ready=2))
    row = _row(doc)
    assert row["shares"] == 2 and row["tranche_usd"] == 40.0
    assert row["below_one_share_usd"] == 3.10


def test_share_values_are_read_as_whole_shares():
    assert api._tranche_shares({"shares": 0}) == 0
    assert api._tranche_shares({"shares": 0.0}) == 0          # a float zero is a zero
    assert api._tranche_shares({"shares": 1.9}) == 1          # floored, never rounded up
    assert api._tranche_shares({"shares": None}) is None
    assert api._tranche_shares({"shares": "3"}) is None       # a string is not a computed count
    assert api._tranche_shares({"shares": True}) is None      # bool is an int subclass; not a count
    assert api._tranche_shares({}) is None


def test_no_ready_tranche_still_emits_no_account_row():
    doc = api.consumer_view(_doc([_account("Small", [_leg(1, 3.10, 0, ready=False)])], ready=0))
    plan = doc["candidates"][0]["plan"]
    assert plan["accounts"] == []
    assert plan["tranches"][0]["status"] == "waiting"


# ── the line that was wrong on screen ───────────────────────────────────────────


def test_next_tranche_total_drops_unbuyable_dollars_and_still_names_the_account():
    doc = api.consumer_view(_doc([
        _account("Main", [_leg(1, 600.0, 10)], symbol="SYNTH_A"),
        _account("Small", [_leg(1, 2.88, 0)], symbol="SYNTH_A"),
    ], symbol="SYNTH_A"))
    totals = meb.next_tranche_by_account(doc)
    assert totals == {"Main": 600.0, "Small": 0.0}
    assert "Small" in totals                      # present, with the honest number


def test_rendered_brief_prints_zero_not_the_unbuyable_dollars():
    doc = api.consumer_view(_doc([
        _account("Main", [_leg(1, 600.0, 10)], symbol="SYNTH_A"),
        _account("Small", [_leg(1, 2.88, 0)], symbol="SYNTH_A"),
    ], symbol="SYNTH_A"))
    _subject, body = meb.render_email(doc, slot="2026-11-08T20:00", changes=["Episode opened."],
                                      top_n=5, stale=False)
    section = body.split("NEXT TRANCHE $ (READY names)")[1].split("ACCOUNTS")[0]
    assert "Main: $600" in section
    assert "Small: $0" in section                 # the defect said Small: $3
    assert "$3" not in section.removeprefix("Main: $600")
