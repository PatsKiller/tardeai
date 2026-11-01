"""The retired overnight-LLM lane's frozen backlog is not a Do-now P1 (Home showed "CRIT: 1928 pending, 0 done").

deep_overnight_llm_queue is drained only by the deep-overnight-llm lane, RETIRED since 2026-06 (crontab PHASE102),
and the table is KEEP_FOREVER in config/data_retention_policy.json. Nothing can drain it by design, so the P1 was
noise. A live (non-retired) queue keeps its CRIT exactly as before. Hermetic.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.lib import needs_action as NA

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 31, 14, tzinfo=timezone.utc)
LIVE = {
    "measured": True,
    "pending": 1928,
    "failed": 268,
    "done_today": 0,
    "cap_tonight": 100,
    "estimated_completion_nights": 19.3,
}


def test_retired_lane_backlog_raises_no_do_now_item():
    assert NA.rule_queue({**LIVE, "retired": True, "lane_state": "RETIRED"}, NOW) == []


def test_live_lane_backlog_still_raises_p1():
    items = NA.rule_queue({**LIVE, "retired": False, "lane_state": "ACTIVE"}, NOW)
    assert len(items) == 1 and items[0]["severity"] == "P1"


def test_unreadable_queue_still_reports_source_unavailable():
    import pytest

    with pytest.raises(NA.SourceUnavailable):
        NA.rule_queue({"measured": False, "retired": True}, NOW)


def test_registry_and_retention_agree_the_lane_is_retired_and_kept():
    lanes = json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]
    assert next(r for r in lanes if r.get("lane_id") == "deep-overnight-llm")["state"] == "RETIRED"
    raw = (ROOT / "config/data_retention_policy.json").read_text()
    assert '"table": "deep_overnight_llm_queue"' in raw and "KEEP_FOREVER" in raw
