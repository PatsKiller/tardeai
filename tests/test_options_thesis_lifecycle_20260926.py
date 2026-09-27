"""Options thesis lifecycle and the living CIO view (operator 2026-09-26).

"Insufficient data should not sit indefinitely": research is requested, answers
come back, the CIO review issues a Decision GUID, or the thesis is archived after
the window. Established tickers show the CIO view already on file. No network,
DB or model: research, review and the decision sink are stubbed.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import options_thesis as ot  # noqa: E402
from lib import options_thesis_lifecycle as lc  # noqa: E402
from lib import ticker_cio_view as tv  # noqa: E402
from lib import options_cio_review as ocr  # noqa: E402

CFG = {"options_thesis_lifecycle": {"abandon_after_hours": 48, "cio_review_mode": "live", "max_reviews_per_run": 6}}
T0 = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def _p(guid="g1", missing=("catalysts", "exit_criteria"), pin="opt_g1@v1", **kw):
    return {"symbol": "DELL", "strategy": "cash_secured_put", "option_strategy_guid": guid, "expiration": "2026-11-20",
            "dte": 55, "options_thesis": {"pin": pin, "missing_required": list(missing)}, **kw}


def _store(tmp_path, guid="g1"):
    s = ot.OptionsThesisStore(tmp_path / "t.jsonl")
    s._append({"event_type": "OPTIONS_THESIS_VERSION", "position_guid": guid, "version": 1, "pin": f"opt_{guid}@v1",
               "recorded_at": T0.isoformat()})
    return s


def _run(store, props, now, research=None, status=None, review=None, sink=None, apply=True):
    return lc.advance(props, store, CFG,
                      request_research=research or (lambda p, qs=None: {"research_id": "res_1", "plan_id": "plan_1"}),
                      research_status=status or (lambda rid: {"status": "queued"}),
                      review_fn=review or (lambda p, m: {"status": "DRY_RUN"}),
                      record_decision=sink or (lambda r: None), apply=apply, now=now)


def test_incomplete_thesis_requests_research_then_reads_answers(tmp_path):
    s = _store(tmp_path)
    assert _run(s, [_p()], T0 + timedelta(minutes=5))[0]["action"] == "REQUEST_RESEARCH"
    assert s.lifecycle("g1")["stage"] == "RESEARCH_QUEUED"
    assert _run(s, [_p()], T0 + timedelta(minutes=10))[0]["action"] == "WAIT_RESEARCH"
    result = {"answers": [
        {"question_id": "q_catalyst_map", "status": "answered", "summary": "Earnings 2026-11-24 after expiry"},
        {"question_id": "q_invalidation", "status": "answered", "summary": "Exit if AI server backlog shrinks"},
        {"question_id": "q_bear_case", "status": "unanswered", "summary": "withheld"}]}
    step = _run(s, [_p()], T0 + timedelta(minutes=30), status=lambda rid: {"status": "completed", "result": result})[0]
    assert step["action"] == "RESEARCH_COMPLETE" and step["answers"] == ["catalysts", "invalidation"]
    ans = s.lifecycle("g1")["research"]["answers"]
    assert ans["catalysts"].startswith("Earnings") and "bear_case" not in ans


def test_research_answers_fill_the_record():
    t = {"thesis_state": "INSUFFICIENT_DATA"}
    p = {"symbol": "DELL", "strategy": "cash_secured_put", "option_strategy_guid": "g", "strike": 490,
         "expiration": "2026-11-20", "research_answers": {"research_id": "res_1", "thesis": "AI server demand",
                                                           "catalysts": "Earnings 11-24", "invalidation": "Backlog shrinks"}}
    rec = ot.build_record(p, t)
    assert rec["catalysts"] == ["Earnings 11-24"]
    assert "Backlog shrinks" in rec["exit_criteria"]
    assert rec["investment_thesis"]["state"] == "RESEARCHED_FOR_OPTION"
    assert rec["thesis_gate_state"] == "RESEARCHED_FOR_OPTION"


def test_complete_thesis_gets_a_decision_guid(tmp_path):
    s = _store(tmp_path)
    sunk = []
    rev = {"outcome": "MORE_RESEARCH", "confidence": "MEDIUM", "reasoning": "Catalyst after expiry",
           "concerns": ["earnings after expiry"], "evidence_for": [], "evidence_against": []}
    step = _run(s, [_p(missing=())], T0 + timedelta(hours=1),
                review=lambda p, m: {"status": "OK", "review": rev, "decision_guid": "dec_abc"}, sink=sunk.append)[0]
    assert step == {**step, "action": "DECISION", "outcome": "MORE_RESEARCH", "decision_guid": "dec_abc"}
    life = s.lifecycle("g1")
    assert life["stage"] == "DECISION_ISSUED" and life["decision"]["decision_guid"] == "dec_abc"
    # MORE_RESEARCH is not a dead end (operator 2026-09-26): the next pass starts follow-up research.
    assert sunk and _run(s, [_p(missing=())], T0 + timedelta(hours=2))[0]["action"] == "REQUEST_FOLLOWUP"


def test_still_incomplete_after_48h_is_archived_with_reason(tmp_path):
    s = _store(tmp_path)
    step = _run(s, [_p()], T0 + timedelta(hours=49))[0]
    assert step["action"] == "ABANDON" and "catalysts" in step["reason"]
    assert s.lifecycle("g1")["stage"] == "ARCHIVED_ABANDONED"


def test_dry_run_writes_nothing(tmp_path):
    s = _store(tmp_path)
    assert _run(s, [_p()], T0 + timedelta(minutes=5), apply=False)[0]["action"] == "REQUEST_RESEARCH"
    assert s.lifecycle("g1")["stage"] == "CREATED"


def test_queue_position_and_eta_come_from_the_projection():
    proj = {"by_research_id": {"a": {"status": "queued", "created_ts": "1"}, "b": {"status": "running", "created_ts": "0"},
                               "c": {"status": "queued", "created_ts": "2"}, "d": {"status": "completed", "created_ts": "0"}}}
    q = lc.queue_position(proj, "c", lc.settings(CFG))
    assert q == {"position": 3, "of": 3, "eta_minutes": 45}


def test_established_ticker_shows_the_cio_view_not_insufficient_data():
    thesis = {"symbol_thesis_version": "symbol_spcx@v13", "thesis_state": "CURRENT", "thesis_stance": "HOLD",
              "thesis_summary": "Low-conviction, confirmation-first", "last_reviewed": "2026-09-25T10:25:02+00:00"}
    decisions = [{"decision_id": "cio-spcx-2", "action": "HUMAN_REVIEW", "action_class": None, "rationale": "r2",
                  "created_at": "2026-09-25T20:41"},
                 {"decision_id": "cio-spcx-1", "action": "HOLD", "action_class": None, "rationale": "r1",
                  "created_at": "2026-09-24T20:41"}]
    v = tv.cio_view("SPCX", thesis, decisions=decisions, research={"count": 24, "last_completed": "2026-09-25"})
    assert v["has_view"] and not v["genuinely_new"]
    assert v["latest_decision"]["source"] == "rule engine"
    assert v["change_since_previous"] == {"previous": "HOLD", "current": "HUMAN_REVIEW", "previous_at": "2026-09-24T20:41"}


def test_genuinely_new_ticker_is_labelled_new():
    v = tv.cio_view("DELL", {"thesis_state": "INSUFFICIENT_DATA"}, decisions=[], research={"count": 0, "last_completed": None})
    assert v["genuinely_new"] and not v["has_view"]


def test_cio_review_refuses_sizing_and_untraceable_numbers():
    facts = {"strike": 490, "premium": 21.57}
    ok, errs = ocr.validate({"outcome": "APPROVE", "confidence": "HIGH", "reasoning": "Sell 5 contracts at 490"}, facts)
    assert not ok and any("sizing" in e for e in errs)
    ok, errs = ocr.validate({"outcome": "APPROVE", "confidence": "HIGH", "reasoning": "Breakeven near 468.43 is 12% below"}, facts)
    assert not ok and any("traceable" in e for e in errs)
    ok, _ = ocr.validate({"outcome": "MONITOR_ONLY", "confidence": "LOW", "reasoning": "Strike 490 is fine; wait for earnings"}, facts)
    assert ok


def test_live_mode_is_the_operator_choice_in_config():
    import yaml
    blk = yaml.safe_load((ROOT / "assets" / "portfolio_intent.yaml").read_text())["options_desk_settings"]["options_thesis_lifecycle"]
    assert blk["cio_review_mode"] == "live" and blk["abandon_after_hours"] == 48


def test_truncated_review_is_named_not_unparseable():
    cut = '{"outcome": "MORE_RESEARCH", "confidence": "MEDIUM", "reasoning": "long text that never ends'
    r = ocr.review({"symbol": "DELL", "option_strategy_guid": "g"}, mode="live", llm_fn=lambda p: {"response": cut})
    assert r["status"] == "TRUNCATED" and "unclosed" in r["errors"][0]


def test_complete_review_is_ok_and_limit_is_config():
    good = '{"outcome": "MORE_RESEARCH", "confidence": "MEDIUM", "reasoning": "No authored thesis yet"}'
    r = ocr.review({"symbol": "DELL", "option_strategy_guid": "g"}, mode="live", llm_fn=lambda p: {"response": good})
    assert r["status"] == "OK" and r["review"]["outcome"] == "MORE_RESEARCH" and r["decision_guid"].startswith("dec_")
    import yaml
    blk = yaml.safe_load((ROOT / "assets" / "portfolio_intent.yaml").read_text())["options_desk_settings"]["options_thesis_lifecycle"]
    assert blk["review_max_tokens"] >= 2000


def test_review_facts_carry_derived_figures_and_uncut_answers():
    p = {"symbol": "DELL", "strategy": "cash_secured_put", "underlying_price": 562.89, "strike": 490.0,
         "premium": 21.57, "dte": 55, "breakeven": 468.43,
         "research_answers": {"research_id": "r", "invalidation": "x" * 2000, "bear_case": "b"},
         "committee_memo": {"investment_thesis": "t" * 5000}}
    f = ocr.build_facts(p)
    assert f["derived"]["breakeven_vs_spot_pct"] == -16.8 and f["derived"]["strike_vs_spot_pct"] == -12.9
    assert f["derived"]["desk_floor_min_pop_pct"] == 52
    assert len(f["thesis"]) <= 1201 and f["research_answers"]["bear_case"] == "b"
    ok, errs = ocr.validate({"outcome": "MONITOR_ONLY", "confidence": "LOW",
                             "reasoning": "Breakeven sits 16.8% below spot; POP clears the 52 floor"}, f)
    assert ok, errs


def test_memo_exit_plan_uses_research_invalidation():
    from lib.options_plain_english import committee_memo
    m = committee_memo({"strategy": "cash_secured_put", "symbol": "HOOD",
                        "research_answers": {"invalidation": "Close below the pullback low on volume"}}, {}, {})
    assert m["exit_plan"]["thesis_invalid_when"] == ["Close below the pullback low on volume"]


# ── continuous loop after a decision (operator 2026-09-26: "continuous automated process") ──
def _decide(s, outcome, at, guid="g1", review=None):
    s._append({"event_type": "OPTIONS_THESIS_DECISION", "position_guid": guid, "decision_guid": f"dec_{outcome}_{at}",
               "outcome": outcome, "review": review or {"unknowns": ["No authored DELL thesis", "Bear case thin"],
                                                         "concerns": ["Catalyst after expiry"]},
               "recorded_at": at})


def test_more_research_starts_named_followup_with_a_due_time(tmp_path):
    s = _store(tmp_path)
    _decide(s, "MORE_RESEARCH", (T0 + timedelta(hours=1)).isoformat())
    asked = []
    step = _run(s, [_p(missing=())], T0 + timedelta(hours=1, minutes=10),
                research=lambda p, qs=None: asked.append(qs) or {"research_id": "res_fu", "plan_id": "plan_fu"})[0]
    assert step["action"] == "REQUEST_FOLLOWUP"
    assert [d.split(": ", 2)[-1] for d in step["deliverables"]] == ["No authored DELL thesis", "Bear case thin", "Catalyst after expiry"]
    assert all("find dated, sourced facts" in d for d in step["deliverables"])
    assert asked[0][0]["intent"] == "cio_followup_1"
    fu = s.lifecycle("g1")["followup"]
    assert fu["research_id"] == "res_fu" and fu["due_at"].startswith("2026-09-27")


def test_delivered_followup_triggers_a_new_decision(tmp_path):
    s = _store(tmp_path)
    _decide(s, "MORE_RESEARCH", (T0 + timedelta(hours=1)).isoformat())
    research = lambda p, qs=None: {"research_id": "res_fu"}
    _run(s, [_p(missing=())], T0 + timedelta(hours=1, minutes=10), research=research)
    result = {"answers": [{"question_id": "q_cio_followup_1", "status": "answered", "summary": "Thesis: AI servers"},
                          {"question_id": "q_cio_followup_2", "status": "unanswered", "summary": ""}]}
    step = _run(s, [_p(missing=())], T0 + timedelta(hours=2), research=research,
                status=lambda rid: {"status": "completed", "result": result})[0]
    assert step["action"] == "FOLLOWUP_COMPLETE" and step["answered"] == 1 and step["of"] == 3
    rev = {"outcome": "APPROVE", "confidence": "MEDIUM", "reasoning": "Thesis now supported"}
    step = _run(s, [_p(missing=())], T0 + timedelta(hours=2, minutes=15), research=research,
                review=lambda p, m: {"status": "OK", "review": rev, "decision_guid": "dec_new"})[0]
    assert step["action"] == "DECISION" and step["outcome"] == "APPROVE" and step["decision_guid"] == "dec_new"
    life = s.lifecycle("g1")
    assert [d["outcome"] for d in life["decisions"]] == ["MORE_RESEARCH", "APPROVE"]
    assert life["decision"]["supersedes"].startswith("dec_MORE_RESEARCH")


def test_followup_past_due_is_archived(tmp_path):
    s = _store(tmp_path)
    _decide(s, "MORE_RESEARCH", (T0 + timedelta(hours=1)).isoformat())
    _run(s, [_p(missing=())], T0 + timedelta(hours=1, minutes=10), research=lambda p, qs=None: {"research_id": "r"})
    step = _run(s, [_p(missing=())], T0 + timedelta(hours=30), status=lambda rid: {"status": "queued"})[0]
    assert step["action"] == "ABANDON" and "due time" in step["reason"]


def test_endless_more_research_is_capped(tmp_path):
    s = _store(tmp_path)
    for h in (1, 3, 5):
        _decide(s, "MORE_RESEARCH", (T0 + timedelta(hours=h)).isoformat())
    step = _run(s, [_p(missing=())], T0 + timedelta(hours=6))[0]
    assert step["action"] == "ABANDON" and "3 times" in step["reason"]


def test_monitor_only_rechecks_after_the_window(tmp_path):
    s = _store(tmp_path)
    _decide(s, "MONITOR_ONLY", (T0 + timedelta(hours=1)).isoformat())
    assert _run(s, [_p(missing=())], T0 + timedelta(hours=5))[0]["action"] == "WAIT_MONITOR"
    step = _run(s, [_p(missing=())], T0 + timedelta(hours=26),
                review=lambda p, m: {"status": "OK", "review": {"outcome": "REJECT", "confidence": "LOW", "reasoning": "r"},
                                     "decision_guid": "dec_2"})[0]
    assert step["action"] == "DECISION" and step["outcome"] == "REJECT"


def test_reject_and_approve_are_final(tmp_path):
    for outcome in ("REJECT", "APPROVE"):
        s = _store(tmp_path / outcome)
        _decide(s, outcome, (T0 + timedelta(hours=1)).isoformat())
        assert _run(s, [_p(missing=())], T0 + timedelta(hours=40)) == []


def test_followup_for_symbol_without_thesis_asks_the_thesis_questions_first(tmp_path):
    """2026-09-26 DELL: concerns pasted as statements were answered "Confirmed: no thesis"."""
    rev = {"unknowns": ["No authored DELL thesis"], "concerns": ["Bear case thin"]}
    qs = lc.followup_questions({"symbol": "DELL", "strategy": "cash_secured_put", "thesis_state": "INSUFFICIENT_DATA",
                                "expiration": "2026-11-20", "dte": 55}, rev, 5)
    intents = [q["intent"] for q in qs]
    assert intents[:4] == ["thesis_check", "catalyst_map", "invalidation", "bear_case"]
    assert intents[4:] == ["cio_followup_1", "cio_followup_2"]
    assert "do not restate it" in qs[4]["text"]


def test_followup_answers_are_keyed_by_intent(tmp_path):
    dels = [{"intent": "thesis_check", "text": "q1"}, {"intent": "cio_followup_1", "text": "q2"}]
    result = {"answers": [{"question_id": "q_thesis_check", "status": "answered", "summary": "AI server backlog"},
                          {"question_id": "q_cio_followup_1", "status": "answered", "summary": "Earnings 11-25"}]}
    ans = lc.followup_answers(result, dels)
    assert [a["answer"] for a in ans] == ["AI server backlog", "Earnings 11-25"]
