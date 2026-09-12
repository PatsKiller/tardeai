"""Per-lane budget floors inside the shared daily LLM cap.

Reproduces the live starvation measured on 2026-09-11 (ET day): a shared
$1.50 global pool consumed to $1.14651 by advisory/hermes lanes, after which
every hourly L3 judgment refused `budget_cap` and the governed research
producer refused `BUDGET_REFUSED:CALLER_DAILY_CAP`. Per-process caps did not
help -- they sum to $15.48 against that $1.50 pool, so they constrain nobody.
"""

from __future__ import annotations

import json

import pytest

from scripts.lib.llm_lane_reservation import (
    LaneFloorConfigError,
    available_under_global_cap,
    explain,
    load_lane_floors,
    validate_floors_against_cap,
    withheld_for_other_lanes,
)

# Measured live spend, 2026-09-11 ET day.
LIVE_SPEND = {
    "advisory_desk_opinion": 0.83435,
    "hermes_external_research": 0.30519,
    "watchlist_cio_synthesis_cron": 0.00518,
    "watchlist_maria_flash_narrative": 0.00159,
    "advisory_desk_synthesis": 0.00020,
    "l3_judgment_author": 0.0,
    "governed_research_producer": 0.0,
}
LIVE_GLOBAL_SPENT = sum(LIVE_SPEND.values())
LIVE_CAP = 1.50


def _spent(lane: str) -> float:
    return LIVE_SPEND.get(lane, 0.0)


def test_reproduces_the_starvation_with_no_floors():
    """Control: today's behaviour. The maturity lanes get the crumbs left by
    whoever spent first, which on 2026-09-11 was $0.35 for everyone combined."""
    avail = available_under_global_cap(
        process_id="l3_judgment_author",
        global_cap=LIVE_CAP,
        spent_globally=LIVE_GLOBAL_SPENT,
        floors={},
        spent_by_lane=_spent,
    )
    assert avail == pytest.approx(LIVE_CAP - LIVE_GLOBAL_SPENT, abs=1e-9)
    assert avail < 0.36


def test_floor_protects_the_starved_lane_from_a_high_frequency_lane():
    """With a floor, the same live spend leaves L3 able to author."""
    floors = {"l3_judgment_author": 0.20, "governed_research_producer": 0.15}
    avail = available_under_global_cap(
        process_id="l3_judgment_author",
        global_cap=LIVE_CAP,
        spent_globally=LIVE_GLOBAL_SPENT,
        floors=floors,
        spent_by_lane=_spent,
    )
    # L3 is withheld only the research lane's unused floor, not its own.
    assert avail == pytest.approx(LIVE_CAP - LIVE_GLOBAL_SPENT - 0.15, abs=1e-9)
    assert avail > 0.19, "a floored lane must still be able to spend its floor"


def test_the_greedy_lane_is_the_one_that_loses_headroom():
    """The floor must bite on the lane that was doing the starving."""
    floors = {"l3_judgment_author": 0.20, "governed_research_producer": 0.15}
    avail = available_under_global_cap(
        process_id="advisory_desk_opinion",
        global_cap=LIVE_CAP,
        spent_globally=LIVE_GLOBAL_SPENT,
        floors=floors,
        spent_by_lane=_spent,
    )
    assert avail == pytest.approx(LIVE_CAP - LIVE_GLOBAL_SPENT - 0.35, abs=1e-9)
    assert avail == pytest.approx(0.0, abs=1e-9) or avail < 0.01


def test_a_consumed_floor_withholds_nothing():
    """A floor is not a permanent tax. Once a lane has spent its floor, the
    rest of the pool is open to everyone again."""
    spent = dict(LIVE_SPEND, l3_judgment_author=0.20)
    floors = {"l3_judgment_author": 0.20}
    avail = available_under_global_cap(
        process_id="advisory_desk_opinion",
        global_cap=LIVE_CAP,
        spent_globally=sum(spent.values()),
        floors=floors,
        spent_by_lane=spent.get,
    )
    assert withheld_for_other_lanes(
        process_id="advisory_desk_opinion", floors=floors, spent_by_lane=spent.get
    ) == pytest.approx(0.0)
    assert avail == pytest.approx(LIVE_CAP - sum(spent.values()), abs=1e-9)


def test_a_partially_consumed_floor_withholds_only_the_remainder():
    floors = {"l3_judgment_author": 0.20}
    spent = dict(LIVE_SPEND, l3_judgment_author=0.08)
    withheld = withheld_for_other_lanes(
        process_id="advisory_desk_opinion", floors=floors, spent_by_lane=spent.get
    )
    assert withheld == pytest.approx(0.12, abs=1e-9)


def test_floors_can_never_exceed_the_global_cap():
    """Silently clamping would leave an operator reading a config that says a
    lane is protected when it is not."""
    with pytest.raises(LaneFloorConfigError, match="exceed_global_cap"):
        validate_floors_against_cap({"a": 1.0, "b": 1.0}, 1.50)


def test_a_floor_never_raises_the_global_cap():
    """A lane with a floor still cannot spend past the pool."""
    floors = {"l3_judgment_author": 1.0}
    avail = available_under_global_cap(
        process_id="l3_judgment_author",
        global_cap=LIVE_CAP,
        spent_globally=LIVE_CAP,
        floors=floors,
        spent_by_lane=lambda _l: 0.0,
    )
    assert avail == 0.0


def test_availability_is_never_negative():
    avail = available_under_global_cap(
        process_id="whoever",
        global_cap=1.0,
        spent_globally=5.0,
        floors={},
        spent_by_lane=lambda _l: 0.0,
    )
    assert avail == 0.0


def test_absent_config_means_no_floors_not_an_error(tmp_path):
    assert load_lane_floors(tmp_path / "nope.json") == {}


def test_malformed_config_refuses_rather_than_degrading(tmp_path):
    """A broken floors file must not read as 'no protection'. Degrading here
    would reintroduce the starvation silently."""
    bad = tmp_path / "floors.json"
    bad.write_text("{ not json")
    with pytest.raises(LaneFloorConfigError, match="unreadable"):
        load_lane_floors(bad)

    wrong_schema = tmp_path / "schema.json"
    wrong_schema.write_text(json.dumps({"schema": "Something@v9", "floors": {}}))
    with pytest.raises(LaneFloorConfigError, match="schema_mismatch"):
        load_lane_floors(wrong_schema)

    negative = tmp_path / "neg.json"
    negative.write_text(
        json.dumps({"schema": "LlmLaneFloors@v1", "floors": {"lane": -1.0}})
    )
    with pytest.raises(LaneFloorConfigError, match="negative"):
        load_lane_floors(negative)

    nonnumeric = tmp_path / "nan.json"
    nonnumeric.write_text(
        json.dumps({"schema": "LlmLaneFloors@v1", "floors": {"lane": "lots"}})
    )
    with pytest.raises(LaneFloorConfigError, match="not_numeric"):
        load_lane_floors(nonnumeric)


def test_valid_config_round_trips(tmp_path):
    good = tmp_path / "floors.json"
    good.write_text(
        json.dumps(
            {
                "schema": "LlmLaneFloors@v1",
                "floors": {"l3_judgment_author": 0.20, "zero_lane": 0},
            }
        )
    )
    loaded = load_lane_floors(good)
    assert loaded == {"l3_judgment_author": 0.20}


def test_refusal_explanation_separates_empty_pool_from_withheld_floor():
    """'budget_cap' alone cannot tell an operator whether to raise the cap or
    to retune a floor. Those are opposite actions."""
    floors = {"governed_research_producer": 0.15}
    detail = explain(
        process_id="l3_judgment_author",
        global_cap=LIVE_CAP,
        spent_globally=LIVE_GLOBAL_SPENT,
        floors=floors,
        spent_by_lane=_spent,
    )
    assert detail["withheld_by_other_lane_floors_usd"] == pytest.approx(0.15)
    assert detail["floors_configured"] == ["governed_research_producer"]
    assert detail["own_floor_usd"] == 0.0

    empty_pool = explain(
        process_id="l3_judgment_author",
        global_cap=LIVE_CAP,
        spent_globally=LIVE_CAP,
        floors={},
        spent_by_lane=_spent,
    )
    assert empty_pool["withheld_by_other_lane_floors_usd"] == 0.0
    assert empty_pool["available_usd"] == 0.0


# ---------------------------------------------------------------------------
# Wiring: the pure algorithm above must actually reach the gate the provider
# client calls. The first attempt at this change wired reserve(), which the
# DeepSeek client never invokes -- the live path is check_cost_cap().
# ---------------------------------------------------------------------------


def test_live_gate_is_check_cost_cap_and_it_consults_floors():
    import inspect

    from scripts.lib import llm_consumption as lc

    src = inspect.getsource(lc.check_cost_cap)
    assert "available_under_global_cap" in src, (
        "check_cost_cap is the gate scripts/lib/deepseek_client.py reaches via "
        "provider_cost.budget.ensure_budget_allows_call; floors must apply there"
    )
    assert "lane_floor" in src


def test_reserve_path_also_consults_floors():
    import inspect

    from scripts.lib import llm_consumption as lc

    fn = lc.reserve_projected_cost
    assert "available_under_global_cap" in inspect.getsource(fn)


def test_unregistered_lane_is_reported_not_exempted():
    """An unregistered lane used to skip the process cap silently, making the
    lane with no declared budget the least constrained caller on the host."""
    import inspect

    from scripts.lib import llm_consumption as lc

    src = inspect.getsource(lc.check_cost_cap)
    assert "_unregistered_lane_observed" in src
    assert callable(lc._unregistered_lane_observed)


def test_no_floors_configured_changes_nothing(monkeypatch, tmp_path):
    """Rollback property: empty the config and the decision is the old one."""
    from scripts.lib.llm_lane_reservation import available_under_global_cap

    for spent in (0.0, 0.5, 1.4, 1.5, 2.0):
        assert available_under_global_cap(
            process_id="any",
            global_cap=1.5,
            spent_globally=spent,
            floors={},
            spent_by_lane=lambda _l: 0.0,
        ) == pytest.approx(max(0.0, 1.5 - spent))
