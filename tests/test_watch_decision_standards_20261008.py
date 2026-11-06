"""Watch decision standards (operator 2026-10-07: "watchlist etc" — the Communications standards on the Watchlist).

Every Watch card gets a category, priority, five scores, a TTL with an expiry, a status and an actionability flag
from config/watch_decision_standards.yaml. The SIGNAL expires, never the membership; held positions never leave the
views; a search always finds the name. Fakes only: no database, no network.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.data_broker import watch_decision as wd  # noqa: E402

NOW = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)
FRESH = (NOW - timedelta(hours=6)).isoformat()
OLD = (NOW - timedelta(days=12)).isoformat()


def card(**k):
    base = {"symbol": "ABC", "last": 10.0, "trade_ai_state": "WAIT", "held": False, "proposal_allowed": False}
    base.update(k)
    return base


def plan(urgency="ready", conf=0.7, rr=3.0, lo=9.5, hi=10.5, stop=9.0, at=FRESH):
    return {"urgency": urgency, "confidence": conf, "risk_reward": rr, "entry_zone_low": lo, "entry_zone_high": hi,
            "stop_price": stop, "created_at": at}


def test_categories_and_ttls():
    cats = {c["id"]: c["ttl_hours"] for c in wd.categories()}
    assert cats["re_entry"] == cats["reward"] == cats["high_conviction_opportunity"] == 96
    assert cats["watchlist_candidate"] == 168 and "held_position" in cats


def test_strong_ready_plan_in_zone_is_high_conviction_and_actionable():
    d = wd.decide(card(), {"plan": plan()}, now=NOW)
    assert (d["category"], d["status"], d["actionable"]) == ("high_conviction_opportunity", "active", True)
    # FQ-074: "Review entry" is a research prompt, not an executable step. The structured kind travels with the
    # decision so the badge and the actionable filter never infer it from the copy.
    assert (d["action_kind"], d["executable"], d["action_hint"]) == ("review", False, "Review entry")
    assert d["time_sensitivity"] == 1.0 and d["confidence"] == 0.7
    assert d["expires_at"] == (datetime.fromisoformat(FRESH) + timedelta(hours=96)).isoformat()
    assert 0 < d["ttl_remaining_s"] <= 96 * 3600


def test_weak_ready_plan_is_reward_not_high_conviction():
    d = wd.decide(card(), {"plan": plan(conf=0.4, rr=1.5)}, now=NOW)
    assert d["category"] == "reward" and d["actionable"]


@pytest.mark.parametrize("state,status,actionable", [
    ("READY TO REVIEW", "confirmed", True), ("NEAR ENTRY", "potential", True), ("WAIT", "opportunity", False),
])
def test_reentry_desk_state_maps_to_reentry_status(state, status, actionable):
    d = wd.decide(card(), {"reentry": {"state": state, "price_as_of": FRESH, "action": "Review re-entry now"}}, now=NOW)
    assert (d["category"], d["reentry_status"], d["actionable"]) == ("re_entry", status, actionable)


def test_held_with_sell_synthesis_is_risk():
    d = wd.decide(card(held=True), {"synthesis": {"recommendation": "SELL", "updated_at": FRESH}}, now=NOW)
    assert d["category"] == "risk" and d["actionable"] and d["risk_score"] >= 0.9
    assert (d["action_kind"], d["executable"], d["action_hint"]) == ("review", False, "Review the held position")


def test_reentry_desk_hints_carry_a_structured_kind():
    ready = wd.decide(card(), {"reentry": {"state": "READY TO REVIEW", "price_as_of": FRESH}}, now=NOW)
    near = wd.decide(card(), {"reentry": {"state": "NEAR ENTRY", "price_as_of": FRESH}}, now=NOW)
    assert (ready["action_kind"], ready["action_hint"]) == ("review", "Review re-entry now")
    assert (near["action_kind"], near["executable"], near["action_hint"]) == ("execute", True, "Set a re-entry alert")


def test_old_signal_expires_but_a_held_name_stays_visible():
    idea = wd.decide(card(), {"plan": plan(urgency="near_entry", at=OLD)}, now=NOW)
    # plan older than plan_fresh_hours no longer counts — no evidence left
    assert idea["status"] == "needs_data"
    syn_old = (NOW - timedelta(days=9)).isoformat()      # past the 168 h held_position TTL
    exp = wd.decide(card(held=True), {"synthesis": {"recommendation": "HOLD", "updated_at": syn_old}}, now=NOW)
    assert exp["category"] == "held_position" and exp["status"] == "expired"
    assert wd.in_view(exp)                                   # held: shown, badge says "signal expired — review"
    assert not wd.is_live(exp)                               # ...but an expired signal is not a live one (2026-10-22)
    non_held = dict(exp, held=False)
    assert not wd.in_view(non_held)                          # a non-held expired signal leaves the active views


def test_avoid_synthesis_invalidates_non_held_only():
    inp = {"synthesis": {"recommendation": "AVOID", "updated_at": FRESH}}
    assert wd.decide(card(), inp, now=NOW)["status"] == "invalidated"
    assert wd.decide(card(held=True), inp, now=NOW)["status"] != "invalidated"


def test_priority_rises_at_most_one_tier_above_base():
    d = wd.decide(card(), {"plan": plan(conf=0.5, rr=9.0)}, now=NOW)   # reward rule, base medium, huge score
    assert d["priority"] in ("medium", "high")


def test_no_evidence_is_needs_data_not_expired():
    d = wd.decide(card(), {}, now=NOW)
    assert d["status"] == "needs_data" and d["expires_at"] is None and wd.is_live(d)


# ── filters, sorts, board ───────────────────────────────────────────────────

def _items():
    rows = [
        card(symbol="HC"), card(symbol="RE"), card(symbol="OLD"), card(symbol="AV"), card(symbol="H", held=True),
    ]
    inputs = {
        "HC": {"plan": plan()},
        "RE": {"reentry": {"state": "NEAR ENTRY", "price_as_of": FRESH, "distance_pct": 1.0}},
        "OLD": {"synthesis": {"recommendation": "HOLD", "updated_at": (NOW - timedelta(days=9)).isoformat()}},
        "AV": {"synthesis": {"recommendation": "AVOID", "updated_at": FRESH}},
        "H": {"synthesis": {"recommendation": "TRIM", "updated_at": FRESH}},
    }
    for c in rows:
        c["decision"] = wd.decide(c, inputs[c["symbol"]], now=NOW)
    return rows


def test_default_view_hides_expired_and_invalidated_but_search_finds_them():
    rows = _items()
    live = [c["symbol"] for c in rows if wd.passes(c["decision"], {})]
    assert "OLD" not in live and "AV" not in live and {"HC", "RE", "H"} <= set(live)
    assert wd.passes(rows[3]["decision"], {"q": "AV"})
    assert wd.passes(rows[2]["decision"], {"decision_status": "expired"})


def test_filters_by_category_priority_actionable_and_scores():
    rows = _items()
    pick = lambda q: [c["symbol"] for c in rows if wd.passes(c["decision"], q)]  # noqa: E731
    assert pick({"category": "re_entry"}) == ["RE"]
    assert pick({"reentry_status": "potential"}) == ["RE"]
    # FQ-074: the actionable filter selects executable steps only. HC ("Review entry") and H ("Review the held
    # position") are research prompts; RE's "Set a re-entry alert" is the executable step.
    assert set(pick({"actionable": "1"})) == {"RE"}
    assert "HC" in pick({"min_time": "0.9"})


def test_a_review_prompt_is_not_selectable_as_an_actionable_decision():
    by = {c["symbol"]: c["decision"] for c in _items()}
    assert by["HC"]["actionable"] and not by["HC"]["executable"]           # has a next step, not executable
    assert by["H"]["action_kind"] == "review" and not by["H"]["executable"]
    assert by["RE"]["action_kind"] == "execute" and by["RE"]["executable"]
    for symbol in ("HC", "H"):
        assert not wd.passes(by[symbol], {"actionable": "1"}), symbol
    assert wd.passes(by["RE"], {"actionable": "1"})
    # The next-step filter still sees a review prompt: it has something to show, it just is not an order.
    assert {s for s in by if wd.passes(by[s], {"next_step": "1"})} == {"HC", "H", "RE"}


def test_sorts_cover_every_score():
    rows = [{"card": c} for c in _items()]
    for s in ("priority_score", "confidence", "risk_score", "reward_score", "time_sensitivity", "expires_at"):
        assert s in wd.SORTS
        out = sorted(rows, key=wd.sort_key(s))
        assert len(out) == len(rows)
    by_risk = sorted(rows, key=wd.sort_key("risk_score"))
    assert by_risk[0]["card"]["symbol"] == "H"


def test_board_answers_the_six_questions_over_live_items():
    b = wd.board(_items(), now=NOW)
    assert list(b["panels"]) == ["attention", "reward", "reentry", "risk", "expiring", "recent"]
    # FQ-074: the actionable count and its panels select executable steps only, matching the actionable filter.
    # "Needs attention" keeps every live signal with a next step, so a held name whose synthesis says TRIM is not
    # dropped from the board merely because its step reads "review".
    assert {i["symbol"] for i in b["panels"]["attention"]["items"]} == {"HC", "RE", "H"}
    # The tile's count and the filter its preset sends must select the same set (the count/filter agreement rule).
    assert {i["symbol"] for i in b["panels"]["attention"]["items"]} == {
        c["symbol"] for c in _items() if wd.passes(c["decision"], {"next_step": "1"})}
    assert b["actionable"] == 1
    assert {i["symbol"] for i in b["panels"]["recent"]["items"]} == {"RE"}
    assert [i["symbol"] for i in b["panels"]["reentry"]["items"]] == ["RE"]
    assert b["facets"]["status"]["expired"] == 1 and b["facets"]["status"]["invalidated"] == 1


def test_projection_wires_the_standards():
    src = (ROOT / "scripts" / "lib" / "data_broker" / "watch_intelligence.py").read_text()
    assert "_wd.attach(" in src and '"decision_board": decision_board' in src and '"expired",' in src
    ui = (ROOT / "apps" / "command-center-v3" / "src" / "pages" / "WatchIntelligenceUnified.tsx").read_text()
    assert "WatchDecisionBoard" in ui and "WatchDecisionFilterModal" in ui and "WatchDecisionBadges" in ui
