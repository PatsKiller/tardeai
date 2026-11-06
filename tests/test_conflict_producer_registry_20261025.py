"""R1 producer freshness registry (EXCEPTIONS_MATRIX.md R1, gap (e) 2026-10-25).

A side's age is its OLDEST material input; superseded after min(14 d, 2 x cadence) — review 7 d, synthesis 14 d,
plan 7 d, quote per AGENTS.md 7A; refresh is queued only to a producer that writes the compared input.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from scripts.lib.conflicts import producer_registry as PR
from scripts.lib.conflicts.adapters import evaluate_inputs, security_inputs
from scripts.lib.conflicts.engine import Input

ROOT = Path(__file__).resolve().parents[1]
REG = PR.load_registry()
THURSDAY = datetime(2026, 10, 22, 17, tzinfo=timezone.utc)      # 13:00 ET, session open
SUNDAY = datetime(2026, 10, 25, 17, tzinfo=timezone.utc)
FRIDAY_CLOSE = datetime(2026, 10, 23, 20, 0, tzinfo=timezone.utc)  # 16:00 ET


def test_registry_covers_every_stance_producer_the_adapters_emit():
    for source in ("CIO record", "watchlist CIO review", "watchlist_final_synthesis", "trade_ai",
                   "reentry_decision_desk", "plan", "quote"):
        assert source in REG["producers"], source
    limits = {name: 2 * row["cadence_days"] for name, row in REG["producers"].items() if row.get("cadence_days")}
    # The matrix's limits (R1): review 7 d, synthesis 14 d, plan 7 d; the cap is 14 d.
    assert limits["watchlist CIO review"] == 7 and limits["watchlist_final_synthesis"] == 14 and limits["plan"] == 7
    assert REG["max_supersede_days"] == 14
    rulebook = json.loads((ROOT / "config/conflict_rulebook.json").read_text())["security_stance"]["supersede_days"]
    for source in ("watchlist CIO review", "watchlist_final_synthesis", "plan"):
        assert rulebook[source] == limits[source], source


def test_refresh_lanes_exist_and_a_retired_writer_never_gets_a_refresh():
    lanes = {r["lane_id"]: r for r in json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]}
    for name, row in REG["producers"].items():
        lane = row.get("refresh_lane")
        if lane:
            assert lane in lanes and lanes[lane]["state"] == "ACTIVE", (name, lane)
        for material in (row.get("materials") or {}).values():
            if material.get("refresh_lane"):
                assert lanes[material["refresh_lane"]]["state"] == "ACTIVE"
    # Desk synthesis: every lane that runs its writer is RETIRED, so it cannot be asked to refresh.
    writers = [r for r in lanes.values() if "process_watchlist_agent_jobs" in json.dumps(r)]
    assert writers and all(r["state"] == "RETIRED" for r in writers), "a synthesis writer is ACTIVE again: update R1 row"
    assert REG["producers"]["watchlist_final_synthesis"]["writes_compared_input"] is False


def test_validation_refuses_silent_or_unbounded_rows():
    good = json.loads(PR.REGISTRY_PATH.read_text())
    for mutate in (lambda d: d["producers"]["plan"].update(cadence_days=0),
                   lambda d: d["producers"]["watchlist CIO review"].update(writes_compared_input="yes"),
                   lambda d: d["producers"]["watchlist_final_synthesis"].pop("writes_compared_input_reason"),
                   lambda d: d["producers"]["trade_ai"].update(refresh_lane=None),
                   lambda d: d.update(schema="other")):
        doc = json.loads(json.dumps(good))
        mutate(doc)
        with pytest.raises(ValueError):
            PR.validate(doc)


def test_quote_ages_in_session_time_per_7a():
    authority = {r.get("domain"): r for r in json.loads((ROOT / "config/data_source_authority.json").read_text())["domains"]}
    stale_after = timedelta(hours=authority["quote_price"]["stale_after_hours"])
    quote = REG["producers"]["reentry_decision_desk"]["materials"]["quote"]
    assert PR.material_limit(quote, now=THURSDAY) == stale_after
    # Sunday: the Friday close quote is still the current quote.
    assert PR.material_limit(quote, now=SUNDAY) == stale_after + (SUNDAY - FRIDAY_CLOSE)


def desk_bundle(*, plan_age, quote_age, now=THURSDAY):
    return security_inputs(security_guid="g1", symbol="SYM", held=False,
                           canonical={"source": "CIO record", "stance": "WATCH", "as_of": (now - timedelta(hours=1)).isoformat()},
                           reentry={"state": "READY", "price_as_of": (now - quote_age).isoformat() if quote_age is not None else None,
                                    "plan_as_of": (now - plan_age).isoformat() if plan_age is not None else None})


def by_rule(findings, rule):
    return [f for f in findings if f.rule == rule]


def test_oldest_material_decides_and_no_refresh_goes_to_a_desk_nobody_writes():
    fresh = evaluate_inputs(desk_bundle(plan_age=timedelta(days=2), quote_age=timedelta(minutes=5)), now=THURSDAY)
    assert [f.summary for f in by_rule(fresh, "R15")] == ["Disagreement observed — confirmation due next run"]
    old_plan = evaluate_inputs(desk_bundle(plan_age=timedelta(days=8), quote_age=timedelta(minutes=5)), now=THURSDAY)
    (superseded,) = [f for f in old_plan if f.kind == "SUPERSEDED"]
    assert superseded.rule == "R1" and superseded.action == "none"
    assert superseded.sides[0]["as_of"] == (THURSDAY - timedelta(days=8)).isoformat()   # oldest material, not run time
    old_quote = evaluate_inputs(desk_bundle(plan_age=timedelta(days=1), quote_age=timedelta(hours=2)), now=THURSDAY)
    assert [f.kind for f in old_quote if f.rule == "R1"] == ["SUPERSEDED"]
    missing = evaluate_inputs(desk_bundle(plan_age=None, quote_age=timedelta(minutes=5)), now=THURSDAY)
    assert [f.kind for f in missing if f.rule == "R1"] == ["SUPERSEDED"]                 # missing time = stale
    weekend = evaluate_inputs(desk_bundle(plan_age=timedelta(days=3), quote_age=SUNDAY - FRIDAY_CLOSE, now=SUNDAY), now=SUNDAY)
    assert not [f for f in weekend if f.kind == "SUPERSEDED"]                            # no weekend false alarm


def review_bundle(source_row, age, now=THURSDAY):
    card = {}
    if source_row == "review":
        card = {"cio_review": {"verdict": "BUY", "status": "COMPLETE", "completed_at": (now - age).isoformat()}}
    else:
        card = {"decision": {"inputs": {"synthesis": "BUY", "synthesis_at": (now - age).isoformat()}}}
    return security_inputs(security_guid="g1", symbol="SYM", held=False,
                           canonical={"source": "CIO record", "stance": "WATCH", "as_of": (now - timedelta(hours=1)).isoformat()},
                           card=card)


def test_refresh_is_queued_only_to_a_producer_that_writes_the_input():
    review = [f for f in evaluate_inputs(review_bundle("review", timedelta(days=8)), now=THURSDAY) if f.kind == "SUPERSEDED"]
    assert [(f.rule, f.action) for f in review] == [("R1", "queue_refresh")]
    assert not [f for f in evaluate_inputs(review_bundle("review", timedelta(days=6)), now=THURSDAY) if f.kind == "SUPERSEDED"]
    synthesis = [f for f in evaluate_inputs(review_bundle("synthesis", timedelta(days=15)), now=THURSDAY) if f.kind == "SUPERSEDED"]
    assert [(f.rule, f.action) for f in synthesis] == [("R1", "none")]
    assert not [f for f in evaluate_inputs(review_bundle("synthesis", timedelta(days=13)), now=THURSDAY)
                if f.kind == "SUPERSEDED"]


def test_explicit_producer_values_win_and_unknown_sources_pass_through():
    item = Input("watchlist CIO review", "BUY", THURSDAY, metadata={"cadence_days": 1, "writes_compared_input": False})
    out = PR.annotate(item, now=THURSDAY, registry=REG)
    assert out.metadata["cadence_days"] == 1 and out.metadata["writes_compared_input"] is False
    assert item.metadata == {"cadence_days": 1, "writes_compared_input": False}             # pure: copy returned
    other = Input("unregistered_desk", "BUY", THURSDAY)
    assert PR.annotate(other, now=THURSDAY, registry=REG) is other
    bad = PR.annotate(Input("reentry_decision_desk", "READY", THURSDAY,
                            metadata={"materials": {"quote": THURSDAY.isoformat(), "plan": "yesterday"}}),
                      now=THURSDAY, registry=REG)
    assert bad.metadata["time_error"] is True
