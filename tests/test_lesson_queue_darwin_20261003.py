"""Policy Review P2 (operator-approved 2026-10-03): only outcome-backed lessons are queued; Darwin
scores only real market outcomes.

Measured on prod that day: all 633 queued lessons fail the rule (609 case-summary filler, 19 with no
settled outcome, 5 "TRIM on SCHD" lessons resting on horizon prices of ~$18.5 for a fund stored at
~$34 on the same dates). Darwin had scored 1,822 cases whose outcome was EXPIRED (no market result).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import lesson_outcome_quality as loq  # noqa: E402
import lesson_promotion as lp  # noqa: E402
from scripts.lib import cio_production_case as cs  # noqa: E402

PRICES = {("SCHD", "2026-09-08"): 34.39, ("SCHD", "2026-09-09"): 34.08}


def _price_on(symbol, day):
    return STORE.get((symbol, str(day)[:10]))


STORE: dict = {}


def _vol(_symbol):
    return 0.01


def _outcome(oid, d0, d1, p0, p1, sym="ABC", rec="BUY"):
    STORE[(sym, d0)] = p0
    STORE[(sym, d1)] = p1
    return {"outcome_id": oid, "realized_state": {"symbol": sym, "recommendation": rec, "decision_price_date": d0,
                                                   "horizon_price_date": d1, "price_at_decision": p0,
                                                   "price_at_horizon": p1, "change_pct": (p1 / p0 - 1) * 100}}


def _proc(pid, outcome_ids, task_class="BUY", statement="BUY on ABC held consistently across outcomes."):
    return {"schema": lp.SCHEMA, "event": "QUEUED", "status": "QUEUED", "procedure_id": pid, "source": "lesson_candidates",
            "statement": statement, "applies_to": {"scope": "ABC", "task_class": task_class}, "symbols": [],
            "evidence": {"supporting_outcome_ids": list(outcome_ids)}}


def _cio(tmp_path: Path, procs: list[dict], outcomes: list[dict]) -> dict:
    cio = tmp_path / "cio"
    cio.mkdir()
    (cio / "lesson_promotions.jsonl").write_text("".join(json.dumps(p) + "\n" for p in procs), encoding="utf-8")
    (cio / "outcome_observations.jsonl").write_text("".join(json.dumps(o) + "\n" for o in outcomes), encoding="utf-8")
    return {"TRADEAI_CIO_DIR": str(cio)}


@pytest.fixture(autouse=True)
def _clean_store():
    STORE.clear()
    yield
    STORE.clear()


def _three_good(prefix="o", start=1):
    return [_outcome(f"{prefix}{i}", f"2026-09-0{i + start}", f"2026-09-1{i + start}", 10.0, 10.3) for i in range(3)]


# --- quality check ---------------------------------------------------------

def test_schd_style_bad_price_row_is_refused():
    STORE.update(PRICES)
    bad = {"outcome_id": "fd5a", "realized_state": {"symbol": "SCHD", "recommendation": "TRIM",
           "decision_price_date": "2026-09-08", "horizon_price_date": "2026-09-09",
           "price_at_decision": 34.39, "price_at_horizon": 18.55, "change_pct": -46.06}}
    v = loq.check_outcome(bad, price_on=_price_on, daily_vol=_vol)
    assert v["ok"] is False
    assert any(r.startswith("price_basis_mismatch: horizon 18.55") for r in v["reasons"])
    assert any(r.startswith("implausible_move") for r in v["reasons"])


def test_split_like_jump_is_refused_even_when_the_store_agrees():
    o = _outcome("s1", "2026-09-01", "2026-09-02", 40.0, 20.0)
    v = loq.check_outcome(o, price_on=_price_on, daily_vol=lambda s: 0.5)
    assert any(r.startswith("split_like_jump") for r in v["reasons"])


def test_no_price_store_fails_closed():
    v = loq.check_outcome(_outcome("x", "2026-09-01", "2026-09-05", 10.0, 10.2))
    assert v["ok"] is False and v["reasons"][0].startswith("unverifiable")


# --- queue rule ------------------------------------------------------------

def test_three_independent_quality_outcomes_qualify_two_do_not():
    outs = {o["outcome_id"]: o for o in _three_good()}
    v3 = lp.queue_verdict(_proc("p", list(outs)), outs, price_on=_price_on, daily_vol=_vol)
    assert v3["eligible"] is True and v3["independent"] == 3
    v2 = lp.queue_verdict(_proc("p", list(outs)[:2]), outs, price_on=_price_on, daily_vol=_vol)
    assert v2["eligible"] is False and v2["reason"].startswith("insufficient_quality_outcomes: 2 of 3")


def test_same_decision_date_counts_once():
    outs = [_outcome("a", "2026-09-01", "2026-09-02", 10.0, 10.1), _outcome("b", "2026-09-01", "2026-09-08", 10.0, 10.2),
            _outcome("c", "2026-09-02", "2026-09-03", 10.0, 10.1)]
    idx = {o["outcome_id"]: o for o in outs}
    v = lp.queue_verdict(_proc("p", list(idx)), idx, price_on=_price_on, daily_vol=_vol)
    assert v["independent"] == 2 and v["eligible"] is False


def test_case_summary_is_never_queued():
    outs = {o["outcome_id"]: o for o in _three_good()}
    v = lp.queue_verdict(_proc("p", list(outs), task_class=lp.CASE_SUMMARY_TASK_CLASS), outs,
                         price_on=_price_on, daily_vol=_vol)
    assert v["eligible"] is False and v["reason"].startswith("case_summary_context")


def test_archive_plan_and_archive_are_append_only(tmp_path):
    outs = _three_good()
    env = _cio(tmp_path, [_proc("good", [o["outcome_id"] for o in outs]),
                          _proc("filler", [], task_class=lp.CASE_SUMMARY_TASK_CLASS)], outs)
    plan = lp.archive_plan(None, env, price_on=_price_on, daily_vol=_vol)
    assert [p["procedure_id"] for p in plan] == ["filler"]
    q = Path(env["TRADEAI_CIO_DIR"]) / "lesson_promotions.jsonl"
    before = q.read_text()
    lp.archive("filler", plan[0]["reason"], root=None, env=env)
    after = q.read_text()
    assert after.startswith(before)
    st = lp.state(None, env)
    assert st["filler"]["status"] == "ARCHIVED" and st["good"]["status"] == "QUEUED"
    assert lp.promoted(None, env) == []
    assert all(i["procedure_id"] != "filler" for i in lp.package_items(None, env))


# --- digest ----------------------------------------------------------------

def test_digest_caps_at_five_and_ranks_by_evidence(tmp_path):
    procs, outs = [], []
    for n in range(7):
        k = 4 if n == 6 else 3
        group = [_outcome(f"g{n}_{i}", f"2026-08-{10 + i:02d}", f"2026-08-{20 + i:02d}", 10.0, 10.2) for i in range(k)]
        outs += group
        procs.append(_proc(f"p{n}", [o["outcome_id"] for o in group]))
    env = _cio(tmp_path, procs, outs)
    d = lp.weekly_digest(None, env, price_on=_price_on, daily_vol=_vol)
    assert d["eligible_total"] == 7
    assert len(d["candidates"]) == 5
    assert d["candidates"][0]["procedure_id"] == "p6"
    assert d["candidates"][0]["independent_outcomes"] == 4


# --- contradiction -> RETIRE_PROPOSED ----------------------------------------

def test_contradicted_lesson_is_proposed_for_retirement_not_retired(tmp_path):
    support = _three_good()
    later = [_outcome(f"l{i}", f"2026-09-2{i}", f"2026-09-2{i + 5}" if i < 4 else "2026-09-30", 10.0, 9.7) for i in range(4)]
    env = _cio(tmp_path, [_proc("p", [o["outcome_id"] for o in support])], support + later)
    plan = lp.contradiction_plan(None, env, price_on=_price_on, daily_vol=_vol)
    assert len(plan) == 1 and plan[0]["procedure_id"] == "p" and len(plan[0]["contradicting"]) == 4
    lp.propose_retirement("p", plan[0], root=None, env=env)
    st = lp.state(None, env)["p"]
    assert st["status"] == "RETIRE_PROPOSED"
    with pytest.raises(PermissionError):
        lp.decide("p", "RETIRED", by="policy:lesson_queue_p2", env=env)


def test_enqueue_holds_unbacked_and_fails_closed_without_prices(tmp_path, monkeypatch):
    outs = _three_good()
    env = _cio(tmp_path, [], outs)
    cands = [lp._procedure(statement="BUY on ABC held consistently across outcomes.", source="lesson_candidates",
                           source_id="1", applies_to={"scope": "ABC", "task_class": "BUY"},
                           evidence={"supporting_outcome_ids": [o["outcome_id"] for o in outs]}),
             lp._procedure(statement="CASE_SUMMARY supporting context for ABC (plan x).", source="lesson_candidates",
                           source_id="2", applies_to={"scope": "ABC", "task_class": lp.CASE_SUMMARY_TASK_CLASS})]
    monkeypatch.setattr(lp, "gather", lambda root=None, env=None: cands)
    blind = lp.enqueue(None, env, apply=False)
    assert blind["new"] == 0 and blind["held_by_policy"] == {"insufficient_quality_outcomes": 1, "case_summary_context": 1}
    seen = lp.enqueue(None, env, apply=True, price_on=_price_on, daily_vol=_vol)
    assert seen["new"] == 1 and seen["written"] == 1


# --- Darwin ----------------------------------------------------------------

def test_darwin_skips_expired_and_scores_real_outcomes():
    expired = {"status": "MATURED", "operator_disposition": {"disposition": "ack"},
               "outcome": {"outcome_status": "EXPIRED", "evaluation_horizon": "7d", "maturity_at": "2026-09-01T00:00:00+00:00"}}
    r = cs.score_case_darwin(expired)
    assert r["eligible"] is False and r["darwin_status"] == cs.UNSCORED_NO_MARKET_OUTCOME
    assert r["reason"] == "unscored: no market outcome" and r["score"] is None
    positive = dict(expired, outcome={"outcome_status": "POSITIVE", "evaluation_horizon": "7d",
                                      "maturity_at": "2026-09-01T00:00:00+00:00"})
    assert cs.score_case_darwin(positive)["score"] == 80  # 50 + ack 10 + POSITIVE 20


def test_legacy_darwin_score_on_expired_case_is_withdrawn_in_projection():
    events = [
        {"case_id": "c1", "event_type": cs.DECISION_OPENED, "payload": {"decision_id": "d1"}, "decision_id": "d1"},
        {"case_id": "c1", "event_type": cs.CASE_MATURED, "decision_id": "d1",
         "payload": {"outcome_status": "EXPIRED", "evaluation_horizon": "7d", "maturity_at": "2026-09-01T00:00:00+00:00"}},
        {"case_id": "c1", "event_type": cs.DARWIN_SCORED, "decision_id": "d1",
         "payload": {"eligible": True, "darwin_status": "SCORED", "score": 60}},
    ]
    case = cs._fold_events("c1", events)
    assert case["darwin"]["darwin_status"] == cs.UNSCORED_NO_MARKET_OUTCOME
    assert case["darwin"]["withdrawn_score"] == 60
    assert case["status"] == "MATURED"
