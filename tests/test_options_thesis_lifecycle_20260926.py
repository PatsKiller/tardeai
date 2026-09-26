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
                      request_research=research or (lambda p: {"research_id": "res_1", "plan_id": "plan_1"}),
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
    assert sunk and _run(s, [_p(missing=())], T0 + timedelta(hours=2)) == []   # decided: nothing more to do


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
