"""The earnings calendar is the dated catalyst an option needs (2026-09-26).

DELL's next earnings (2026-11-27) sat on the proposal while the card said
"catalysts missing" and blocked approval.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import options_thesis as ot  # noqa: E402
from lib.options_plain_english import committee_memo  # noqa: E402


def _p(nxt, exp="2026-11-20"):
    return {"symbol": "DELL", "strategy": "cash_secured_put", "expiration": exp, "strike": 490,
            "option_strategy_guid": "g", "enterprise": {"earnings": {"next_earnings": nxt}}}


def test_live_key_is_enterprise_earnings():
    # The shape the enterprise layer actually writes (options_desk_enterprise: ent["earnings"]).
    live = {"expiration": "2026-11-20", "enterprise": {"earnings": {"in_blackout": False, "next_earnings": "2026-11-27"}}}
    assert ot.calendar_catalyst(live).startswith("Calendar: next earnings 2026-11-27")


def test_earnings_after_expiry_is_stated_as_a_calendar_fact():
    c = ot.calendar_catalyst(_p("2026-11-27"))
    assert c.startswith("Calendar: next earnings 2026-11-27, after the 2026-11-20 expiry")


def test_earnings_inside_the_trade_is_flagged():
    assert "falls inside this trade" in ot.calendar_catalyst(_p("2026-11-10"))


def test_no_calendar_no_catalyst():
    assert ot.calendar_catalyst(_p(None)) is None
    assert ot.calendar_catalyst({"strategy": "protective_put", "expiration": "2026-11-20"}) is None


def test_record_and_memo_use_the_calendar():
    rec = ot.build_record(_p("2026-11-27"), {"thesis_state": "INSUFFICIENT_DATA"})
    assert rec["catalysts"] and rec["catalysts"][0].startswith("Calendar:")
    assert "catalysts" not in rec["missing_required"]
    m = committee_memo(_p("2026-11-27"), {}, {})
    assert m["why_now"].startswith("Calendar:")


def test_option_research_counts_as_partial_research():
    p = dict(_p("2026-11-27"), research_answers={"thesis": "AI server demand", "research_id": "res_1"})
    m = committee_memo(p, {"thesis_state": "INSUFFICIENT_DATA"}, {})
    assert m["research_status"] == "PARTIALLY_RESEARCHED" and m["investment_thesis"] == "AI server demand"
