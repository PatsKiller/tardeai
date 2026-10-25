"""R1 material time: the entry-plan read model carries the plan's own created_at (gap (e) 2026-10-25).

The re-entry desk builds plan_as_of from plan.get("created_at") (reentry_decision_desk.py), but
data_broker.entry_plan.get_entry_plans never selected it, so every stored desk row had plan_as_of = null and the
conflict engine had to treat the desk's plan material as missing (R1: missing time = stale).
"""
from datetime import datetime, timezone

from scripts.lib.data_broker.entry_plan import get_entry_plans


def test_latest_plan_carries_its_created_at():
    at = datetime(2026, 10, 19, 23, 13, tzinfo=timezone.utc)
    seen = {}

    def db_query(sql, params=None, fetch="all"):
        seen["sql"] = " ".join(sql.split())
        return [{"symbol": "dt", "entry_zone_low": 54.8, "entry_zone_high": 56.2, "stop_price": 53.2,
                 "target_price": 68.0, "risk_reward": 5.4, "urgency": "watch", "proposal_tag": None, "created_at": at}]
    plans = get_entry_plans(db_query, ["DT"])
    assert plans["DT"]["created_at"] == at and plans["DT"]["entry_zone_low"] == 54.8
    assert "created_at FROM watchlist_entry_plans" in seen["sql"] and seen["sql"].startswith("SELECT")
