"""Research Escalation Circle, Phase 1: GUIDs, the score, the Context Analyzer's grounding, check-ins. Offline."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import research_circle as rc  # noqa: E402

COVERS = ["scripts/lib/research_circle.py", "scripts/run_research_circle.py"]
NOW = datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)
TODAY = NOW.date().isoformat()


def _ev(kind, source, text, *, as_of=TODAY, value=None, channel="provider"):
    return rc.Evidence(kind, source, text, as_of=as_of, value=value, channel=channel)


def test_question_guid_is_stable_and_distinct():
    a = rc.question_guid("42", "7", "Do some more research on HPE")
    assert a == rc.question_guid("42", "7", "do  some more research on hpe")
    assert a != rc.question_guid("42", "8", "Do some more research on HPE")


def test_needs_are_read_from_the_question():
    needs = rc.detect_needs("what's a good entry support resistance with an analyst saying and how long has volume been more than normal")
    assert {"levels", "analysts", "volume"} <= set(needs)
    assert rc.detect_needs("hello") == ["research"]


def test_an_undated_line_is_never_stamped_today():
    assert rc.stated_date("Buy · 20 analysts · mean target $67.43", now=NOW) is None
    assert rc.stated_date("Sep 11 earnings beat · Sep 14 Evercore cuts HPE", now=NOW) == "2026-09-14"
    assert rc.stated_date("Dec 03 next report", now=NOW) == "2025-12-03"
    assert rc.stated_date("filed 2026-08-30, due 2026-12-01", now=NOW) == "2026-08-30"


def test_cross_checked_house_and_outside_evidence_scores_high():
    ev = [_ev("quote", "trade_ai:ticker_prices", "HPE close $55.96", value=55.96, channel="house"),
          _ev("quote", "yahoo", "HPE last $56.05", value=56.05)]
    s = rc.score_lap(["price"], ev, now=NOW)
    assert s["per_need"]["price"]["score"] == 100 and s["maturity"] == "M2" and not s["contradictions"]


def test_contradicting_numbers_are_named_and_cap_the_score():
    ev = [_ev("quote", "trade_ai:ticker_prices", "XLI close $7.49", value=7.49, channel="house"),
          _ev("quote", "yahoo", "XLI last $169.25", value=169.25)]
    s = rc.score_lap(["price"], ev, now=NOW)
    assert s["contradictions"] and s["per_need"]["price"]["score"] <= 50


def test_stale_only_evidence_is_not_sufficient():
    ev = [_ev("analyst", "trade_ai:analysts", "Buy, target $96.50", as_of="2026-06-24", channel="house")]
    s = rc.score_lap(["analysts"], ev, now=NOW)
    assert s["per_need"]["analysts"] == {"score": 20, "fresh_items": 0, "sources": [], "stale_only": True}
    assert rc.deterministic_decision(s, lap=1)["decision"] == "climb"


def test_deterministic_decision_climbs_then_stops_at_the_bound():
    weak = rc.score_lap(["research"], [], now=NOW)
    assert rc.deterministic_decision(weak, lap=1) == {"decision": "climb", "next_channel": "hermes", "missing_facts": ["research"]}
    assert rc.deterministic_decision(weak, lap=2)["decision"] == "stop_bound"


def test_a_grounded_model_verdict_is_used():
    ev = [_ev("news", "yahoo:Reuters", "ELMT wins $450M government investment")]
    raw = json.dumps({"sufficiency_score": 78, "per_need": {"news": 78}, "maturity": "M2", "decision": "sufficient",
                      "next_channel": None, "missing_facts": [], "contradictions": [],
                      "answer_summary": f"ELMT is up on a government investment [{ev[0].id}]", "falsifier": None,
                      "checkin_days": 7, "checkin_reason": "fast-moving"})
    score = rc.score_lap(["news"], ev, now=NOW)
    v = rc.analyze("why is ELMT up", ["news"], ev, score, lap=1, call_model=lambda m: {"ok": True, "content": raw})
    assert v["analyzer"] == "deepseek-flash" and v["decision"] == "sufficient" and v["maturity"] == "M2"


def test_a_verdict_citing_unknown_evidence_is_rejected():
    ev = [_ev("news", "yahoo:Reuters", "ELMT headline")]
    raw = json.dumps({"sufficiency_score": 95, "maturity": "M3", "decision": "sufficient", "checkin_days": 7,
                      "answer_summary": "invented [ev_0123456789ab]"})
    score = rc.score_lap(["news"], ev, now=NOW)
    v = rc.analyze("why is ELMT up", ["news"], ev, score, lap=1, call_model=lambda m: {"ok": True, "content": raw})
    assert v["analyzer"] == "deterministic" and "unknown evidence ids" in v["analyzer_note"]


def test_the_model_cannot_call_an_empty_lap_sufficient():
    raw = json.dumps({"sufficiency_score": 90, "maturity": "M3", "decision": "sufficient", "checkin_days": 7})
    score = rc.score_lap(["research"], [], now=NOW)
    v = rc.analyze("dig deeper on HPE", ["research"], [], score, lap=1, call_model=lambda m: {"ok": True, "content": raw})
    assert v["decision"] == "climb" and v["analyzer_override"]


def test_checkin_is_the_day_after_a_dated_catalyst():
    ev = [_ev("catalyst", "yahoo", "HPE earnings report 2026-12-03 (Yahoo calendar)")]
    c = rc.plan_checkin("HPE outlook", ev, {"decision": "sufficient"}, now=NOW)
    assert c["due_at"].startswith("2026-12-04") and "earnings 2026-12-03" in c["reason"]


def test_checkin_defaults_to_seven_or_fourteen_days():
    open_q = rc.plan_checkin("HPE outlook", [], {"decision": "climb"}, now=NOW)
    held = rc.plan_checkin("WMT outlook", [], {"decision": "sufficient"}, held=True, now=NOW)
    assert open_q["days"] == 7 and held["days"] == 14


def test_volume_streak_counts_completed_sessions_above_normal():
    from datetime import date
    days = [date(2026, 7, 1) + timedelta(days=i) for i in range(40)] + [NOW.date()]
    vols = [1_000_000] * 37 + [2_000_000, 2_500_000, 3_000_000] + [9_000_000]  # today's partial bar is dropped
    s = rc.volume_streak(vols, days, today=NOW.date())
    assert s["streak"] == 3 and s["last_completed"] == days[39].isoformat()
    assert rc.volume_streak([1] * 10, days[:10], today=NOW.date()) is None


def test_targeted_queries_strip_ids_and_are_bounded():
    q = rc.targeted_queries("HPE", ["No multi-day volume history [ev_0123456789ab] to answer 'how long'",
                                    "No dated analyst actions beyond the Sep 14 Evercore downgrade", "third"])
    assert len(q) == 2 and all(x.startswith("HPE ") and "ev_" not in x for x in q)


def test_the_circle_runs_a_targeted_second_lap_over_everything_found(tmp_path):
    ledger = rc.Ledger(tmp_path / "l.jsonl", tmp_path / "c.jsonl")
    lap1 = [_ev("analyst", "yahoo", "HPE Buy, target $67")]
    searched = []

    def targeted(q):
        searched.append(q)
        return [_ev("web", "searxng:reuters.com", f"result for {q}", channel="web_free")]
    laps = rc.run_circle("dig deeper on HPE research outlook", chat_id="1", message_id="2", symbols=["HPE"],
                         subject_guids={}, channels={"yahoo": lambda: lap1}, ledger=ledger, targeted=targeted)
    assert [lap.lap for lap in laps] == [1, 2] and searched
    assert lap1[0].id in {e.id for e in laps[-1].evidence}
    assert laps[-1].checkin is not None
    states = [r["state"] for r in ledger.rows]
    assert states.count("ASKED") == 1 and states.count("ANALYZED") == 2 and states[-1] == "SCHEDULED"


def test_a_lap_that_finds_nothing_new_ends_without_a_model_call(tmp_path):
    ledger = rc.Ledger(tmp_path / "l.jsonl", tmp_path / "c.jsonl")
    lap1 = [_ev("analyst", "yahoo", "HPE Buy, target $67")]
    calls = []

    def model(messages):
        calls.append(1)
        return {"ok": True, "content": json.dumps({"sufficiency_score": 50, "maturity": "M1", "decision": "targeted_lap",
                                                   "next_channel": "brave", "missing_facts": ["HPE research outlook"],
                                                   "checkin_days": 7})}
    laps = rc.run_circle("dig deeper on HPE research outlook", chat_id="1", message_id="2", symbols=["HPE"],
                         subject_guids={}, channels={"yahoo": lambda: lap1}, ledger=ledger,
                         targeted=lambda q: list(lap1), call_model=model)
    assert len(laps) == 2 and len(calls) == 1
    assert laps[-1].verdict["analyzer_note"] == "targeted lap found no new evidence"
    assert laps[-1].verdict["decision"] == "stop_bound" and laps[-1].checkin is not None


def test_a_lap_writes_the_lifecycle_only_when_applied(tmp_path):
    ledger = rc.Ledger(tmp_path / "ledger.jsonl", tmp_path / "checkins.jsonl", apply=False)
    # run_lap reads the real clock, so this evidence is dated from it: a fixed 2026-09-14 date went stale at UTC
    # midnight, the lap no longer stood, and SCHEDULED was never written (CI 2026-09-15 00:23Z).
    fresh = datetime.now(timezone.utc).isoformat()
    ev = [_ev("quote", "trade_ai:ticker_prices", "HPE close $55.96", as_of=fresh, value=55.96, channel="house"),
          _ev("quote", "yahoo", "HPE last $56.05", as_of=fresh, value=56.05)]
    res = rc.run_lap("what is HPE price right now", chat_id="42", message_id="7", symbols=["HPE"], subject_guids={},
                     channels={"all": lambda: ev, "broken": lambda: (_ for _ in ()).throw(RuntimeError("down"))},
                     ledger=ledger)
    states = [r["state"] for r in ledger.rows]
    assert states[:3] == ["ASKED", "GATHERING", "ANALYZED"] and "SCHEDULED" in states
    assert res.channel_errors == {"broken": "RuntimeError: down"}
    assert not (tmp_path / "ledger.jsonl").exists()
    applied = rc.Ledger(tmp_path / "ledger.jsonl", tmp_path / "checkins.jsonl", apply=True)
    rc.run_lap("what is HPE price right now", chat_id="42", message_id="7", symbols=["HPE"], subject_guids={},
               channels={"all": lambda: ev}, ledger=applied)
    rows = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert {r["question_guid"] for r in rows} == {res.question_guid}
    assert (tmp_path / "checkins.jsonl").exists()
