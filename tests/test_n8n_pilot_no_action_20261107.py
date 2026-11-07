"""LQ-20261107-210: a reminder run with nothing to remind about fires no pilot event. Synthetic receipts only."""
from pathlib import Path

from scripts.n8n_pilot_dispatch import plan_lane

LANE = "approval-package-reminder"


def _obs(**over):
    rr = {"run_id": "run-x1", "outcome": "NO_ACTION", "action_count": 0, "delivery_status": "NO_ACTION"}
    rr.update(over)
    return {"run_receipt": rr}


def test_no_action_run_fires_nothing():
    plan = plan_lane(LANE, _obs(), Path("."))
    assert plan["fired"] is False and plan["why"] == "no_action"


def test_run_with_actions_still_fires():
    assert plan_lane(LANE, _obs(outcome="SENT", action_count=2, delivery_status="DELIVERY_OBSERVED"), Path("."))["fired"]


def test_unknown_action_count_still_fires():
    obs = _obs()
    del obs["run_receipt"]["action_count"]
    assert plan_lane(LANE, obs, Path("."))["fired"]


def test_observed_delivery_with_zero_actions_still_fires():
    assert plan_lane(LANE, _obs(delivery_status="DELIVERY_OBSERVED"), Path("."))["fired"]
