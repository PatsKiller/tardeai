"""RESEARCH_LANDED_UNSENT: the answer is on disk and the operator does not have it.

2026-09-14 opr_74cc87d6ae62 (HPE): Hermes completed at 09:16, the pending stayed
open, and no monitor rule could see it -- PENDING_NEVER_CLOSED waits two hours
and says nothing about research that already landed. Pure-function tests; the
ledgers and projection are dicts.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_operator_answer_quality as m  # noqa: E402

COVERS = ["scripts/check_operator_answer_quality.py"]

NOW = datetime(2026, 9, 14, 13, 45, tzinfo=timezone.utc)
PENDING = [{"pending_id": "opr_hpe", "status": "open", "ts": "2026-09-14T13:12:38+00:00",
            "operator_text": "Do some more research on hpe", "chat_id": "42"}]
ASKS = [{"pending_id": "opr_hpe", "kind": "hermes_operator_forced", "plan_id": "plan_hpe"}]


def _proj(status="completed", minutes_ago=29, plan="plan_hpe"):
    done = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    return {"by_research_id": {"res_hpe": {"plan_id": plan, "status": status,
                                           "latest_result_id": "rr_hpe", "completed_ts": done}}}


def test_completed_research_on_an_open_pending_is_a_finding():
    out = m.research_landed_unsent(PENDING, ASKS, _proj(), now=NOW)
    assert [(f["pending_id"], f["result_id"], f["landed_minutes_ago"]) for f in out] == [("opr_hpe", "rr_hpe", 29)]


def test_inside_the_grace_window_is_not_a_finding():
    assert m.research_landed_unsent(PENDING, ASKS, _proj(minutes_ago=4), now=NOW) == []


def test_a_fulfilled_pending_is_not_a_finding():
    rows = PENDING + [{"pending_id": "opr_hpe", "status": "fulfilled"}]
    assert m.research_landed_unsent(rows, ASKS, _proj(), now=NOW) == []


def test_research_still_running_is_not_a_finding():
    assert m.research_landed_unsent(PENDING, ASKS, _proj(status="running"), now=NOW) == []


def test_reused_request_matches_by_research_id():
    asks = [{"pending_id": "opr_hpe", "kind": "hermes_operator_forced", "plan_id": "plan_x", "research_id": "res_hpe"}]
    assert len(m.research_landed_unsent(PENDING, asks, _proj(plan="plan_elsewhere"), now=NOW)) == 1


def test_rule_is_registered_with_an_action():
    assert "RESEARCH_LANDED_UNSENT" in m.RULES and "RESEARCH_LANDED_UNSENT" in m._WHAT_WILL_BE_DONE
