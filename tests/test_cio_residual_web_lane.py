"""ResidualWebLane@v1 — the gated residual web lane.

The operator's eight required tests are all here and each is named for the law
it defends:

  1. unchanged hashes            -> the lane is not chosen
  2. free-first hit              -> no web
  3. dust / TEST / cash-ticker   -> no web
  4. execution-language history  -> no web
  5. the stub hop makes ZERO vendor HTTP calls
  6. the shared matcher catches "do not add until price action confirms"
  7. 36 S5 plans still collapse to one subject (the SLEEVE:CASH question)
  8. telegram_sent stays False

Plus the budget, the librarian grade/staleness law, and the cognition rule that
the next question may never be the prompt just used.
"""
from __future__ import annotations

import socket
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib import cio_residual_web as rw
from scripts.lib import cio_web_librarian as lib
from scripts.lib.cio_instrument_record import (
    CASH_SLEEVE, apply_cognition, content_hash, new_record, subject_key,
)
from scripts.lib.cio_research_gate import (
    LANE_FOR, RESIDUAL_DECISION, RESIDUAL_LANE, collapse_same_day_duplicates,
    decide,
)
from scripts.lib.execution_language import find_imperative

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


# ────────────────────────────────────────────────────────────── helpers ────

def held(sym="NOC", **fields):
    rec = new_record("HELD", sym, symbols=[sym], market_value=25_000.0)
    rec.update(fields)
    return rec


def routed(**extra):
    """A gate decision that DID route to the residual rung."""
    d = {"decision": RESIDUAL_DECISION, "reason": "pro_unresolved_and_material"}
    d.update(extra)
    return d


def legal_case(record=None, **kw):
    kw.setdefault("gate_decision", routed())
    kw.setdefault("plan", {"material": True})
    kw.setdefault("now", NOW)
    return rw.legality(record if record is not None else held(), **kw)


# ─────────────────────────────────────────── the rung is reused, not new ────

def test_the_residual_rung_is_reused_not_invented():
    """`openai` IS the residual step; the lane names the executor, not a new rung."""
    assert RESIDUAL_DECISION == "openai"
    assert rw.RESIDUAL_DECISION == RESIDUAL_DECISION
    assert RESIDUAL_LANE == rw.LANE == "residual_web"
    assert LANE_FOR[RESIDUAL_DECISION] == "residual_web"


def test_the_ladder_still_has_exactly_seven_rungs():
    from scripts.lib.cio_research_gate import DECISIONS
    assert DECISIONS == ("skip", "reuse", "corpus_hit", "flash", "pro",
                         "openai", "grok_critique")
    assert "residual_web" not in DECISIONS


def test_the_gate_still_routes_pro_unresolved_to_the_residual_rung():
    """The lane must not change routing. This is the rung it feeds on."""
    r = decide({"material": True, "prior_outcome": "FAIL", "pro_attempted": True},
               now=NOW)
    assert r["decision"] == RESIDUAL_DECISION
    assert r["lane"] == "residual_web"


def test_we_did_not_invent_grok_execution_review():
    """The banned process_id may be NAMED in prose, never used as a value."""
    import pathlib
    src = pathlib.Path(rw.__file__).read_text(encoding="utf-8")
    body = src.split('"""', 2)[2]          # past the module docstring
    for line in body.splitlines():
        code = line.split("#", 1)[0]
        assert "grok_execution_review" not in code, line
    assert rw.PROCESS_ID != "grok_execution_review"


def test_the_lane_uses_a_registered_process_that_already_allows_it():
    import json
    import pathlib
    assert rw.PROCESS_ID == "hermes_external_research"
    reg = json.loads(
        (pathlib.Path(rw.__file__).resolve().parents[2]
         / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))
    procs = reg.get("processes") or []
    if isinstance(procs, list):
        procs = {p.get("id") or p.get("process_id"): p for p in procs}
    assert rw.PROCESS_ID in procs, "the lane must not invent a process_id"
    entry = procs[rw.PROCESS_ID]
    assert entry.get("default_mode") == "automated"
    assert float(entry.get("daily_cost_cap_usd") or 0) > 0, (
        "the lane must run under a real per-process cost cap")


# ───────────────────────────────────── 1. unchanged hashes -> not chosen ────

def test_unchanged_hashes_do_not_choose_the_lane():
    """A subject that is not due and whose observables did not move is refused."""
    rec = held(next_eligible_at=(NOW + timedelta(days=3)).isoformat())
    rec["hashes"] = {"price": content_hash(101.0), "weight": content_hash(0.04),
                     "earnings": None, "analyst": None}
    verdict = legal_case(rec, observed={"price": 101.0, "weight": 0.04})
    assert verdict["legal"] is False
    assert verdict["refused_by"] == "due_or_hash_changed"
    assert verdict["hash_moved"] is None


def test_a_moved_hash_overrides_the_cadence_skip():
    rec = held(next_eligible_at=(NOW + timedelta(days=3)).isoformat())
    rec["hashes"] = {"price": content_hash(101.0), "weight": None,
                     "earnings": None, "analyst": None}
    verdict = legal_case(rec, observed={"price": 999.0})
    assert verdict["legal"] is True
    assert verdict["hash_moved"] == "price"


def test_an_unset_hash_is_not_a_change():
    """First contact is not an event. An UNSET hash must not open the faucet."""
    rec = held(next_eligible_at=(NOW + timedelta(days=3)).isoformat())
    verdict = legal_case(rec, observed={"price": 123.0, "weight": 0.07})
    assert verdict["hash_moved"] is None
    assert verdict["legal"] is False
    assert verdict["refused_by"] == "due_or_hash_changed"


def test_a_due_subject_is_legal_without_any_hash_change():
    rec = held(next_eligible_at=(NOW - timedelta(days=1)).isoformat())
    assert legal_case(rec)["legal"] is True


# ─────────────────────────────────────────── 2. free-first hit -> no web ────

def test_a_corpus_close_means_no_web():
    verdict = legal_case(corpus={"closes": True, "reason": "corpus_fact_reproduced"})
    assert verdict["legal"] is False
    assert verdict["refused_by"] == "free_first_miss"


def test_a_reuse_decision_means_no_web():
    verdict = legal_case(gate_decision={"decision": "reuse",
                                        "reason": "valid_on_disk_within_ttl"})
    assert verdict["legal"] is False
    # the gate never routed here in the first place
    assert "gate_routed_to_residual" in verdict["failed_checks"]


def test_the_lane_never_promotes_a_subject_the_gate_did_not_route():
    for tok in ("skip", "reuse", "corpus_hit", "flash", "pro", "grok_critique"):
        verdict = legal_case(gate_decision={"decision": tok})
        assert verdict["legal"] is False, tok
        assert "gate_routed_to_residual" in verdict["failed_checks"], tok


def test_not_material_means_no_web():
    verdict = legal_case(plan={"material": False})
    assert verdict["legal"] is False
    assert "material" in verdict["failed_checks"]


# ──────────────────────────────────────────── 3. dust / TEST -> no web ────

@pytest.mark.parametrize("sym", ["TEST", "SPACEX_TEST", "DUMMY"])
def test_test_tickers_get_no_web(sym):
    verdict = legal_case(held(sym))
    assert verdict["legal"] is False
    assert verdict["refused_by"] == "not_dust_test_or_cash_ticker"


@pytest.mark.parametrize("sym", ["CASH", "USD", "SPAXX", "FDRXX"])
def test_cash_as_a_ticker_gets_no_web(sym):
    """The $630k cash question is SLEEVE:CASH, not a HELD:CASH holding."""
    verdict = legal_case(held(sym))
    assert verdict["legal"] is False
    assert verdict["refused_by"] == "not_dust_test_or_cash_ticker"


def test_dust_gets_no_web():
    rec = held("ZZZQ")
    rec["market_value"] = 12.0          # below DUST_MAX_MARKET_VALUE_USD
    verdict = legal_case(rec)
    assert verdict["legal"] is False
    assert verdict["refused_by"] == "not_dust_test_or_cash_ticker"


def test_the_cash_sleeve_itself_is_eligible():
    """SLEEVE:CASH is a sleeve and a lawful subject; HELD:CASH is not."""
    rec = new_record("SLEEVE", "CASH")
    assert rec["subject_key"] == CASH_SLEEVE
    assert legal_case(rec)["legal"] is True


# ───────────────────────────────── 4. execution-language history -> no web ────

def test_execution_language_history_gets_no_web():
    verdict = legal_case(held(last_outcome="execution_language"))
    assert verdict["legal"] is False
    assert verdict["refused_by"] == "no_execution_language_history"


def test_research_blocked_gets_no_web():
    rec = held()
    rec["research_blocked"] = True
    verdict = legal_case(rec)
    assert verdict["legal"] is False
    assert verdict["refused_by"] == "no_execution_language_history"


def test_one_hop_per_subject_per_day():
    assert rw.MAX_HOPS_PER_SUBJECT_PER_DAY == 1
    assert legal_case(hops_today=0)["legal"] is True
    second = legal_case(hops_today=1)
    assert second["legal"] is False
    assert second["refused_by"] == "under_daily_subject_cap"


# ─────────────────────────── 5. the stub hop makes ZERO vendor HTTP calls ────

class _NetworkUsed(AssertionError):
    pass


@pytest.fixture()
def no_network(monkeypatch):
    """Make ANY outbound socket a hard test failure."""
    def boom(*a, **k):
        raise _NetworkUsed(f"vendor network call attempted: {a[:1]}")

    monkeypatch.setattr(socket.socket, "connect", boom, raising=False)
    monkeypatch.setattr(socket.socket, "connect_ex", boom, raising=False)
    monkeypatch.setattr(socket, "create_connection", boom, raising=False)
    import http.client
    monkeypatch.setattr(http.client.HTTPConnection, "connect", boom, raising=False)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", boom, raising=False)
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", boom, raising=False)
    try:
        import requests
        monkeypatch.setattr(requests.sessions.Session, "request", boom, raising=False)
        monkeypatch.setattr(requests, "post", boom, raising=False)
        monkeypatch.setattr(requests, "get", boom, raising=False)
    except Exception:                                            # noqa: BLE001
        pass
    return boom


def test_stub_hop_makes_no_vendor_http_call(no_network):
    hop = rw.run_hop(CASH_SLEEVE, question="What changed in the cash sleeve?",
                     question_ids=["q1"], now=NOW)
    assert hop["applied"] is False
    assert hop["provider"] == "stub"
    assert hop["cost_usd"] == 0.0
    assert hop["paid_dispatch_entered"] == 0


def test_stub_hop_is_the_default(no_network):
    """`apply` defaults to False: the safe path is the one you get by accident."""
    import inspect
    assert inspect.signature(rw.run_hop).parameters["apply"].default is False
    assert rw.run_hop("HELD:NOC", question="q", now=NOW)["provider"] == "stub"


def test_the_paid_dispatch_probe_still_fails_closed():
    """The probe we rely on must itself still refuse a paid dispatch."""
    from scripts.lib.evidence_refresh_job import (
        PAID_FORBIDDEN, dispatch_paid_provider, paid_dispatch_entered,
        reset_paid_dispatch_probe,
    )
    reset_paid_dispatch_probe()
    assert paid_dispatch_entered() == 0
    with pytest.raises(RuntimeError, match=PAID_FORBIDDEN):
        dispatch_paid_provider(state="LLM_ELIGIBLE")
    assert paid_dispatch_entered() == 1
    reset_paid_dispatch_probe()


def test_the_stub_transport_imports_nothing():
    """Structural proof: the stub path cannot reach a vendor even by accident.

    The live transport's imports are local to `_live_transport`, so importing
    the module never pulls in a network client.
    """
    import ast
    import inspect
    stub = ast.parse(inspect.getsource(rw._stub_transport).strip())
    assert not [n for n in ast.walk(stub)
                if isinstance(n, (ast.Import, ast.ImportFrom))], (
        "the stub transport must import nothing")
    live = inspect.getsource(rw._live_transport)
    assert "from scripts.lib.searxng_client import" in live
    assert "from llm_lane import" in live


def test_module_has_no_module_level_network_import():
    import pathlib
    head = pathlib.Path(rw.__file__).read_text(encoding="utf-8").split(
        "def _live_transport")[0]
    for banned in ("import requests", "import urllib", "import httpx",
                   "from llm_lane", "searxng_client"):
        assert banned not in head, banned


def test_a_stub_artifact_must_cost_zero():
    with pytest.raises(rw.ResidualWebRefused):
        rw.run_hop("HELD:NOC", question="q", now=NOW,
                   transport=lambda req: {"provider": "stub", "outcome": "VALID",
                                          "cost_usd": 0.42})


def test_the_stub_returns_unavailable_rather_than_inventing_findings():
    hop = rw.run_hop("HELD:NOC", question="q", question_ids=["q1", "q2"], now=NOW)
    assert hop["answers"] == []
    assert hop["source_urls"] == []
    assert hop["still_unresolved"] == ["q1", "q2"]
    assert "UNAVAILABLE" in (hop["note"] or "")


# ────────────────────────────────── 6. the shared matcher, unchanged ────

def test_matcher_catches_do_not_add_until_price_action_confirms():
    """The operator's phrase. The matcher already catches it; this locks it in."""
    assert find_imperative("do not add until price action confirms") == "do not add"
    assert find_imperative("Do not add until price action confirms.") == "Do not add"


@pytest.mark.parametrize("phrase", [
    "do not add until price action confirms",
    "maintain the position",
    "add to the position here",
    "keep the position",
    "trim the position",
])
def test_the_lane_refuses_a_narrative_carrying_execution_language(phrase):
    assert rw._has_execution_language(phrase)
    rec = held()
    hop = rw.run_hop("HELD:NOC", question="q", now=NOW)
    hop["note"] = phrase
    with pytest.raises(rw.ResidualWebRefused, match="execution language"):
        rw.apply_hop(rec, {**hop, "outcome": "VALID"}, now=NOW)


def test_a_rejected_hop_writes_no_narrative_at_all():
    """REJECT means no attach and no prose — not prose that got filtered."""
    rec = held()
    hop = rw.run_hop("HELD:NOC", question="Is the thesis intact?", now=NOW)
    out, changed = rw.apply_hop(rec, {**hop, "outcome": "REJECT"}, now=NOW)
    assert out["research_blocked"] is True
    assert out["last_artifact_id"] is None
    assert out["cc_narrative"] is None
    assert out["last_outcome"] == "rejected"
    for verb in ("maintain", "add", "buy", "sell", "trim"):
        assert verb not in str(out["next_research_question"]).lower().split()


# ──────────────────────── 7. 36 S5 plans collapse to one subject ────

def test_36_s5_plans_collapse_to_one_subject():
    """36 rows asking the one SLEEVE:CASH question must not buy 36 paid calls.

    The gate report keys S5_CASH_DEPLOYMENT as kind="default" with symbol
    "CASH"; the record identity for that single question is SLEEVE:CASH.
    """
    decisions = [
        decide({"material": True, "kind": "default", "symbol": "CASH",
                "plan_id": f"p{i}", "research_id": f"r{i}",
                "prior_outcome": "FAIL", "pro_attempted": True}, now=NOW)
        for i in range(36)
    ]
    assert all(d["decision"] == RESIDUAL_DECISION for d in decisions)

    report = collapse_same_day_duplicates(decisions, now=NOW)

    survivors = [d for d in decisions if d["decision"] in {"flash", "pro",
                                                           RESIDUAL_DECISION,
                                                           "grok_critique"}]
    assert len(survivors) == 1, "36 S5 plans must collapse to one paid subject"
    assert report["collapsed"] == 35
    assert report["surviving_subject_count"] == 1
    assert report["surviving_subjects"] == [("default", "CASH")]
    assert {d["reason"] for d in decisions if d["decision"] == "skip"} == {
        "duplicate_subject_same_day"}
    # and the one question they were all asking has one record identity
    assert subject_key("SLEEVE", "CASH") == CASH_SLEEVE


def test_distinct_subjects_are_not_collapsed():
    decisions = [
        decide({"material": True, "kind": "held_core_thesis", "symbol": s,
                "prior_outcome": "FAIL", "pro_attempted": True}, now=NOW)
        for s in ("NOC", "RTX", "PFLT")
    ]
    collapse_same_day_duplicates(decisions, now=NOW)
    assert [d["decision"] for d in decisions] == [RESIDUAL_DECISION] * 3


def test_the_daily_budget_is_three_subjects():
    assert rw.DAILY_SUBJECT_BUDGET == 3
    cands = []
    for i, sym in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE"]):
        rec = held(sym)
        cands.append({"record": rec, "legality": legal_case(rec)})
    out = rw.select_daily(cands, now=NOW)
    assert len(out["selected"]) == 3
    assert len(out["deferred"]) == 2


def test_selection_prefers_a_held_name_whose_hash_moved():
    moved = held("MOVD")
    moved["hashes"] = {"price": content_hash(1.0), "weight": None,
                       "earnings": None, "analyst": None}
    sleeve = new_record("SLEEVE", "CASH")
    quiet = held("QUIET")
    cands = [
        {"record": sleeve, "legality": legal_case(sleeve)},
        {"record": quiet, "legality": legal_case(quiet)},
        {"record": moved,
         "legality": legal_case(moved, observed={"price": 2.0})},
    ]
    out = rw.select_daily(cands, budget=1, now=NOW)
    assert out["selected"] == ["HELD:MOVD"]


def test_the_cash_sleeve_outranks_a_quiet_held_name():
    """"held hash-changed preferred, ELSE SLEEVE:CASH if due."

    Regression from the live dry run: 15 quiet HELD records filled a budget of
    3 every day and SLEEVE:CASH was never reached.
    """
    sleeve = new_record("SLEEVE", "CASH")
    cands = [{"record": sleeve, "legality": legal_case(sleeve)}]
    for sym in ("AMANX", "ARKX", "BAH", "CCC"):     # alphabetically before/around
        rec = held(sym)
        cands.append({"record": rec, "legality": legal_case(rec)})
    out = rw.select_daily(cands, now=NOW)
    assert out["selected"][0] == CASH_SLEEVE
    assert len(out["selected"]) == 3


def test_a_moved_held_name_still_outranks_the_cash_sleeve():
    moved = held("ZZZZ")            # last alphabetically, so only tier can win
    moved["hashes"] = {"price": content_hash(1.0), "weight": None,
                       "earnings": None, "analyst": None}
    sleeve = new_record("SLEEVE", "CASH")
    cands = [
        {"record": sleeve, "legality": legal_case(sleeve)},
        {"record": moved, "legality": legal_case(moved, observed={"price": 2.0})},
    ]
    out = rw.select_daily(cands, budget=1, now=NOW)
    assert out["selected"] == ["HELD:ZZZZ"]


def test_the_cash_sleeve_is_the_fallback_when_nothing_held_is_legal():
    sleeve = new_record("SLEEVE", "CASH")
    dusty = held("DUSTY")
    dusty["market_value"] = 1.0
    cands = [
        {"record": dusty, "legality": legal_case(dusty)},
        {"record": sleeve, "legality": legal_case(sleeve)},
    ]
    out = rw.select_daily(cands, now=NOW)
    assert out["selected"] == [CASH_SLEEVE]
    assert out["refused"][0]["refused_by"] == "not_dust_test_or_cash_ticker"


# ───────────────────────────────────────────── 8. telegram_sent False ────

def test_cc_binding_declares_telegram_not_sent():
    rec = held()
    hop = rw.run_hop("HELD:NOC", question="What changed?", now=NOW)
    out, _ = rw.apply_hop(rec, {**hop, "outcome": "PARTIAL"}, now=NOW)
    block = rw.cc_binding(out, hop, now=NOW)
    assert block["telegram_sent"] is False
    assert block["would_send"] is False
    assert block["financial_action"] is False
    assert block["memory_behavior_influence"] == 0


def test_cc_binding_binds_the_updated_narrative():
    rec = held()
    hop = rw.run_hop("HELD:NOC", question="What changed?", now=NOW)
    out, changed = rw.apply_hop(rec, {**hop, "outcome": "PARTIAL"}, now=NOW)
    block = rw.cc_binding(out, hop, now=NOW)
    assert block["cc_narrative"] is out["cc_narrative"]
    assert block["cc_narrative"] != rec["cc_narrative"]
    assert "cc_narrative" in changed


def test_notify_may_rise_to_cc_but_never_to_immediate():
    rec = held()
    hop = {"outcome": "VALID"}
    assert rw.notify_priority_for(rec, hop, hash_moved="price") == "cc"
    assert rw.notify_priority_for(rec, hop, hash_moved=None) == "cc"
    assert "immediate" not in rw.NOTIFY_ON_HASH_CHANGE
    # a rejected hop never raises the volume
    assert rw.notify_priority_for(rec, {"outcome": "REJECT"},
                                  hash_moved="price") == "none"


def test_notify_does_not_downgrade_an_existing_immediate_candidate():
    rec = held(notify_priority="immediate_candidate")
    assert rw.notify_priority_for(rec, {"outcome": "VALID"},
                                  hash_moved="price") == "immediate_candidate"


# ────────────────────────────────────── the instrument record write ────

def test_a_valid_hop_writes_the_full_instrument_record():
    rec = held()
    hop = rw.run_hop(
        "HELD:NOC", question="What did the last 10-Q change?",
        question_ids=["q1"], now=NOW,
        transport=lambda req: {
            "provider": "stub", "outcome": "VALID", "cost_usd": 0.0,
            "still_unresolved": [],
            "source_urls": ["https://www.sec.gov/Archives/edgar/data/1/x.htm"],
        })
    out, changed = rw.apply_hop(rec, hop, observed={"price": 512.0}, now=NOW)

    assert out["last_artifact_id"] == hop["artifact_id"]
    assert out["last_outcome"] == "VALID"
    assert out["research_blocked"] is False
    assert out["next_eligible_at"] > NOW.isoformat()
    assert out["last_event_hash"]
    assert out["hashes"]["price"] == content_hash(512.0)
    assert set(changed) >= {"next_research_question", "next_eligible_at",
                            "cc_narrative"}
    refs = out["cc_narrative"]["evidence_refs"]
    assert refs and refs[0]["grade"] == "A"
    assert refs[0]["stale_after_days"] == 180
    assert "source_id" in refs[0] and "as_of" in refs[0]


def test_the_next_question_must_differ_from_the_prompt_just_used():
    """Cognition apply: re-asking the prompt that failed is learning nothing."""
    asked = ("Prior residual web pass was refused (rejected). What INDEPENDENT "
             "evidence would settle this without restating it?")
    rec = held()
    hop = rw.run_hop("HELD:NOC", question=asked, now=NOW)
    out, _ = rw.apply_hop(rec, {**hop, "outcome": "REJECT"}, now=NOW)
    assert out["next_research_question"] != asked
    assert out["next_research_question"].endswith("(reframed)")


def test_a_replayed_hop_still_moves_the_question_rather_than_silently_passing():
    """A second identical refusal must not quietly re-persist the same prompt.

    The reframe guarantees the question moves, so the replay is a real persist
    and not a no-op that merely looked like learning.
    """
    rec = held()
    hop = rw.run_hop("HELD:NOC", question="q", now=NOW)
    once, _ = rw.apply_hop(rec, {**hop, "outcome": "REJECT"}, now=NOW)
    twice, changed = rw.apply_hop(once, {**hop, "outcome": "REJECT"}, now=NOW)
    assert twice["next_research_question"] != once["next_research_question"]
    assert "next_research_question" in changed


def test_a_cognition_write_that_moves_nothing_is_a_failed_persist():
    from scripts.lib.cio_instrument_record import CognitionNoOp
    rec = held(next_research_question="unchanged?")
    with pytest.raises(CognitionNoOp):
        apply_cognition(rec, next_research_question="unchanged?")


def test_the_lane_can_never_write_behaviour():
    from scripts.lib.cio_instrument_record import BehaviorWriteRefused
    with pytest.raises(BehaviorWriteRefused):
        apply_cognition(held(), next_research_question="q",
                        recommended_delta_usd=25_000)
    assert rw.MBI_BEHAVIOR == 0 and rw.MBI_COGNITION == 1
    assert rw.FINANCIAL_ACTION is False


# ─────────────────────────────────────────────── librarian-lite ────

def test_every_url_becomes_a_typed_ref():
    ref = lib.source_ref("https://www.sec.gov/cgi-bin/browse-edgar?a=NOC", now=NOW)
    assert ref["schema"] == "WebSourceRef@v1"
    assert set(ref) >= {"source_id", "grade", "as_of", "stale_after_days"}
    assert ref["source_id"].startswith("web:www.sec.gov:")
    assert ref["grade"] == "A" and ref["official"] is True


@pytest.mark.parametrize("url,grade", [
    ("https://www.sec.gov/x", "A"),
    ("https://www.federalreserve.gov/x", "A"),
    ("https://fred.stlouisfed.org/series/DGS10", "A"),
    ("https://ir.example.com/quarterly", "A"),
    ("https://example.com/investors/results", "A"),
    ("https://example.substack.com/p/hot-take", "D"),
    ("https://seekingalpha.com/article/1", "D"),
    ("https://www.reddit.com/r/stocks/x", "D"),
    ("https://someresearchhouse.com/note", "C"),
])
def test_grades_come_from_what_the_source_is(url, grade):
    assert lib.source_ref(url, now=NOW)["grade"] == grade


def test_a_blog_cannot_be_promoted_to_a_closing_grade():
    """The prompt does not get to hand back 'A' for a substack."""
    ref = lib.source_ref("https://x.substack.com/p/a", grade="A", now=NOW)
    assert ref["grade"] == "D"
    assert lib.may_close(ref, now=NOW) is False


def test_grade_c_and_d_cannot_corpus_hit():
    for g, url in (("C", "https://someresearchhouse.com/n"),
                   ("D", "https://medium.com/@x/y")):
        ref = lib.source_ref(url, now=NOW)
        assert ref["grade"] == g
        assert lib.may_close(ref, now=NOW) is False
        assert lib.context_only(ref, now=NOW) is True


def test_a_stale_source_cannot_corpus_hit_even_at_grade_a():
    fresh = lib.source_ref("https://www.sec.gov/x", as_of=NOW, now=NOW)
    assert lib.may_close(fresh, now=NOW) is True
    later = NOW + timedelta(days=181)
    assert lib.is_stale(fresh, now=later) is True
    assert lib.may_close(fresh, now=later) is False


def test_an_undated_source_is_stale_fail_closed():
    assert lib.is_stale({"grade": "A"}, now=NOW) is True


def test_entity_questions_may_use_official_pages_not_blogs():
    official = lib.source_ref("https://www.sec.gov/x", now=NOW)
    blog = lib.source_ref("https://seekingalpha.com/article/1", now=NOW)
    assert lib.admissible_for_entity_question(official) is True
    assert lib.admissible_for_entity_question(blog) is False
    assert rw.entity_admissible_refs([official, blog]) == [official]


def test_the_closing_grade_law_is_the_corpus_law_not_a_second_one():
    from scripts.lib.cio_corpus_index import CLOSING_GRADES, CONTEXT_ONLY_GRADES
    assert lib.CLOSING_GRADES is CLOSING_GRADES
    assert lib.CONTEXT_ONLY_GRADES is CONTEXT_ONLY_GRADES
    assert CLOSING_GRADES == frozenset({"A", "B"})


def test_discovery_is_capped_at_three_candidates_a_week():
    from scripts.lib.cio_source_discovery import (
        MAX_PROPOSALS_PER_ENTITY_PER_WEEK,
    )
    assert MAX_PROPOSALS_PER_ENTITY_PER_WEEK == 3
    assert lib.MAX_CANDIDATES_PER_ENTITY_PER_WEEK == 3
    out = lib.discover("NOC", proposals=[
        {"source_id": f"s{i}", "url": f"https://sec.gov/{i}"} for i in range(5)])
    assert len(out["accepted"]) == 3
    assert [r["reason"] for r in out["rejected"]] == ["weekly_cap_reached"] * 2


def test_a_candidate_is_never_a_fact_and_carries_no_grade():
    out = lib.discover("NOC", proposals=[{"source_id": "s1",
                                          "url": "https://sec.gov/1"}])
    cand = out["accepted"][0]
    assert cand["status"] == "CANDIDATE"
    assert cand["evidence_grade"] is None
    assert cand["is_fact"] is False


def test_the_librarian_summary_names_what_may_close():
    refs = [lib.source_ref("https://www.sec.gov/x", now=NOW),
            lib.source_ref("https://seekingalpha.com/a", now=NOW)]
    s = lib.summarize(refs, now=NOW)
    assert s["by_grade"] == {"A": 1, "D": 1}
    assert len(s["may_close"]) == 1
    assert s["closing_grades"] == ["A", "B"]


def test_the_librarian_never_fetches():
    import inspect
    src = inspect.getsource(lib)
    for banned in ("requests", "urlopen", "httpx", "socket"):
        assert banned not in src, banned
