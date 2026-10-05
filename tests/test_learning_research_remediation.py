"""Offline research replays. These are fixtures, never organic-learning evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from scripts import due_diligence_questions as ddq
from scripts.lib import intelligence_client as ic
from scripts.lib.cio_product_reassessment import research_impact
from scripts.lib.research_thesis_delta import build_research_thesis_delta

NOW = datetime(2026, 10, 5, 14, tzinfo=timezone.utc)


def result(**patch):
    return {"result_id": "result-v-1", "research_id": "research-v-1", "symbol": "V",
            "as_of": NOW.isoformat(), "sources": ["filing-v-1"], **patch}


def evaluate(research=None, new=None):
    prior = {"plan_id": "plan-v", "recommendation": "HOLD", "summary": "Margins stable", "material": True,
             "premises": [{"id": "margin", "text": "Margins stable"}], "thesis_id": "thesis-v", "version": 3}
    return research_impact(symbol="V", result_id="result-v-1", research_id="research-v-1",
                           prior=prior, new=new or prior, request={"symbol": "V"}, result=research or result(),
                           critique={"verdict": "VALID"}, prior_thesis=prior, now=NOW)


@pytest.mark.parametrize("invalidates", [False, True])
def test_cited_conflict_opens_review_without_forcing_judgment(invalidates):
    r = result(contradictory_evidence=[{"premise_id": "margin", "evidence_refs": ["filing-v-1"],
                                      "invalidates": invalidates}])
    out = evaluate(r)
    assert out["disposition"] == "REVIEW_REQUIRED"
    assert out["before"] == out["after"]
    assert out["evidence_usage"]["used_refs"] == ["filing-v-1"]
    assert out["premise_conflicts"][0]["kind"] == ("INVALIDATION" if invalidates else "CONFLICT")
    assert out["thesis_id"] == "thesis-v" and out["prior_thesis_version"] == 3


def test_label_alone_does_not_change_judgment_or_publish_thesis():
    r = result(classification="WEAKENS", summary="Margins lower", confidence=.9)
    assert evaluate(r)["disposition"] == "NO_CHANGE"
    delta = build_research_thesis_delta("V", r, prompt_context={"standing_thesis": {"version": 3}}, research_id="r")
    assert delta["review_required"] and not delta["thesis_publish_eligible"]


def test_uncited_or_unknown_premise_does_not_create_verified_review():
    assert evaluate(result(contradictory_evidence=[{"premise_id": "unknown", "source_refs": ["filing-v-1"]}]))["disposition"] == "NO_CHANGE"
    assert evaluate(result(contradictory_evidence=[{"premise_id": "margin", "source_refs": ["invented"]}]))["disposition"] == "NO_CHANGE"


@pytest.mark.parametrize("patch,reason", [
    ({"symbol": "MA"}, "subject_mismatch:symbol"),
    ({"sources": []}, "insufficient_sources"),
    ({"as_of": (NOW-timedelta(days=40)).isoformat()}, "stale_evidence"),
    ({"expires_at": NOW.isoformat()}, "expired_evidence"),
    ({"as_of": "2026-10-05T14:00:00"}, "evidence_time_missing_or_ambiguous"),
    ({"status": "failed"}, "research_not_completed"),
    ({"status": "queued"}, "research_not_completed"),
    ({"status": "running"}, "research_not_completed"),
])
def test_bad_evidence_blocks_even_when_product_fields_change(patch, reason):
    out = evaluate(result(**patch), new={"plan_id": "plan-v", "recommendation": "SELL"})
    assert out["disposition"] == "BLOCKED"
    assert reason in out["evidence_validation"]["reasons"]
    assert not out["evidence_usage"]["used_refs"]


def test_mismatched_request_identity_is_blocked():
    from scripts.lib.research_quality import evidence_eligibility
    out = evidence_eligibility({"symbol": "V", "research_id": "different-request"}, result(),
                               {"verdict": "VALID"}, now=NOW)
    assert not out["eligible"]
    assert "research_request_mismatch" in out["reasons"]


def test_retry_retains_original_evidence_without_paid_research(tmp_path, monkeypatch):
    import sys
    from scripts.lib import cio_product_reassessment as pr
    from scripts.lib import cio_investment_product as prod
    from scripts.lib import cio_persistent_cognition as cog
    from scripts.lib import research_thesis_delta as delta
    monkeypatch.setitem(sys.modules, "cio_investment_product", prod)
    monkeypatch.setattr(cog, "build_cio_cognition", lambda *a, **k: {})
    monkeypatch.setattr(delta, "accept_research_result", lambda *a, **k: {"version_published": False})
    monkeypatch.setattr(prod, "load_brief", lambda *a, **k: {})
    def unavailable(**kwargs):
        raise OSError("fixture build failure")
    monkeypatch.setattr(prod, "build_product", unavailable)
    fresh = result(as_of=datetime.now(timezone.utc).isoformat())
    request = {"research_id": fresh["research_id"], "symbol": "V", "question_class": "thesis"}
    first = pr.reassess_on_research_completed(request, fresh, critique={"verdict": "VALID"}, root=tmp_path, notify=False)
    assert first["research_evaluation"]["disposition"] == "BLOCKED"
    seen = []
    def retry(req, res, **kwargs):
        from scripts.lib.research_quality import evidence_eligibility
        assert res["sources"] == fresh["sources"]
        assert res["as_of"] == fresh["as_of"]
        assert req["research_id"] == fresh["research_id"]
        assert evidence_eligibility(req, res, kwargs["critique"])["eligible"]
        seen.append(res["result_id"])
        return {"ok": True}
    monkeypatch.setattr(pr, "reassess_on_research_completed", retry)
    out = pr.retry_pending_reassessments(root=tmp_path, limit=1)
    assert out["retried_ok"] == 1 and not out["paid_research_repeated"]
    assert seen == [fresh["result_id"]]


def test_change_records_before_after_and_retrieval_identity():
    out = evaluate(result(retrieval_receipt_id="retrieval-v-1"), new={"plan_id": "plan-v", "recommendation": "REVIEW"})
    assert out["disposition"] == "CHANGED_ADVISORY_JUDGMENT"
    assert out["before"]["recommendation"] == "HOLD" and out["after"]["recommendation"] == "REVIEW"
    assert out["retrieval_receipt_id"] == "retrieval-v-1"
    # A difference does not prove which source caused it.
    assert not out["evidence_usage"]["judgment_changing_refs"]


def test_product_completion_persists_review_and_duplicate_is_suppressed(tmp_path, monkeypatch):
    from scripts.lib import cio_product_reassessment as pr
    from scripts.lib import cio_investment_product as prod
    from scripts.lib import cio_persistent_cognition as cog
    from scripts.lib import research_thesis_delta as delta
    from scripts.lib import cio_production_eligibility as eligible
    monkeypatch.setattr(cog, "build_cio_cognition", lambda *a, **k: {})
    monkeypatch.setattr(delta, "accept_research_result", lambda *a, **k: {"version_published": False})
    monkeypatch.setattr(eligible, "prior_visible_for_what_changed", lambda a, b: a)
    prior = {"product_id": "prior", "reentry_book": {"names": [{"symbol": "V", "status": "WAIT"}]}}
    monkeypatch.setattr(prod, "load_brief", lambda *a, **k: deepcopy(prior))
    monkeypatch.setattr(prod, "build_product", lambda **k: deepcopy(prior))
    persisted = []
    monkeypatch.setattr(prod, "persist_product", lambda p, **k: persisted.append(deepcopy(p)))
    # Some callers import the same canonical module by its legacy top-level name.
    import sys
    monkeypatch.setitem(sys.modules, "cio_investment_product", prod)
    fresh = result(as_of=datetime.now(timezone.utc).isoformat(), contradictory_evidence=[
        {"premise_id": "margin", "source_refs": ["filing-v-1"]}])
    request = {"symbol": "V", "prompt_context": {"standing_thesis": {"premises": ["margin"]}}}
    kwargs = dict(request=request, result=fresh, critique={"verdict": "VALID"}, root=tmp_path, notify=False)
    first = pr.reassess_on_research_completed(**kwargs)
    assert first["ok"] and first["research_evaluation"]["disposition"] == "REVIEW_REQUIRED"
    assert persisted[0]["research_evaluation"]["disposition"] == "REVIEW_REQUIRED"
    second = pr.reassess_on_research_completed(**kwargs)
    assert second["duplicate"] and second["notification"]["notification_class"] == "SUPPRESSED"
    assert len(persisted) == 1
    assert second["research_evaluation"]["disposition"] == "NO_CHANGE"
    assert second["research_evaluation"]["original_disposition"] == "REVIEW_REQUIRED"
    assert second["research_evaluation"]["notification_ids"] == []


def test_review_notification_retains_message_identity(tmp_path, monkeypatch):
    from scripts.lib import cio_plan_enrichment as enrich
    from scripts.lib import cio_telegram_converse as telegram
    from scripts.lib import cio_advisory_curator as curator
    from scripts.lib import cio_prompt_eval as structural
    from scripts.lib import cio_notify_freshness as freshness
    monkeypatch.setattr(structural, "structural_check", lambda *a: {})
    monkeypatch.setattr(freshness, "stale_claim", lambda *a: None)
    monkeypatch.setattr(freshness, "stale_evidence", lambda *a: None)
    monkeypatch.setattr(curator, "curate", lambda *a, **k: {"reason": "disabled"})
    monkeypatch.setattr(enrich, "should_skip_notify", lambda *a, **k: (False, "fixture"))
    monkeypatch.setattr(enrich, "record_notify", lambda *a, **k: None)
    monkeypatch.setattr(telegram, "allowlist_chat_ids", lambda: [123])
    monkeypatch.setattr(telegram, "format_structured_reply", lambda **k: "HOLD")
    sent = []
    def send(chat, text):
        sent.append(text)
        return {"ok": True, "message_id": 456}
    monkeypatch.setattr(telegram, "send_cio_message", send)
    plan = {"status": "draft", "plan_id": "plan_v", "situation_type": "S0_OPERATOR_CONVERSE",
            "recommendation": "HOLD", "extra": {"research_evaluation": {"disposition": "REVIEW_REQUIRED"}}}
    assert enrich.maybe_notify_plan(plan, policy={"situation_notify_telegram": True}, ledger_path=tmp_path/"notify.jsonl")
    assert sent[0].startswith("Research review required:")
    assert plan["recommendation"] == "HOLD"
    assert plan["telegram_notification_ids"] == ["telegram:123:456"]


def test_plan_load_failure_still_records_blocked_completion(tmp_path, monkeypatch):
    import json
    from scripts.lib import hermes_research_loop as loop
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    def unavailable():
        raise OSError("fixture unavailable")
    monkeypatch.setattr(loop, "_import_plans", unavailable)
    out = loop.on_hermes_completed({"symbol": "V", "plan_id": "plan_unavailable"},
                                  result(as_of=datetime.now(timezone.utc).isoformat()),
                                  resynth=False, notify=False)
    assert out["plan_load_error"] == "OSError"
    assert out["research_evaluation"]["disposition"] == "BLOCKED"
    rows = [json.loads(line) for line in (tmp_path/"data/cio/hermes_research_requests.jsonl").read_text().splitlines()]
    completion = [r for r in rows if r.get("event") == "HERMES_LOOP_COMPLETED"][-1]
    assert completion["research_evaluation"]["disposition"] == "BLOCKED"
    assert not completion["notified"]


def test_shared_visa_identity_reuses_same_evidence_without_paid_generation(tmp_path):
    loaders = ic.Loaders(
        resolve_subject=lambda s: {"security_guid": "11111111-2222-3333-4444-555555555555", "identity_status": "CONFIRMED"},
        thesis=lambda s: {"thesis_id": "symbol_v", "version": 3, "summary": "Visa payments network", "updated_ts": NOW.isoformat()},
        now=lambda: NOW)
    refs = []
    for surface in ("held", "research", "cio"):
        ctx = ic.open_context({"lane_id": surface}, "RESEARCH", ["V"], mode="ENFORCED", loaders=loaders, write_receipt=False)
        out = ic.retrieve_or_generate(ctx, {"text": "What is the Visa thesis?", "question_class": "thesis"},
                                     generator=lambda *a: pytest.fail("redundant paid generation"),
                                     loaders=loaders, root=tmp_path, write_receipt=False)
        assert out["decision"] == "HIT_FRESH" and not out["generated"]
        refs.append(out["receipt"]["evidence_stages"]["retrieved_refs"])
        assert not out["receipt"]["evidence_stages"]["used_refs"]
    assert refs[0] == refs[1] == refs[2]


def test_usage_does_not_claim_unretrieved_or_rejected_evidence():
    ctx = {"retrieval_evidence_stages": ic.evidence_stages(
        {"traversed_graph_edge_refs": ["edge-v-filing"]}, [{"refs": ["filing", "rejected"]}])}
    usage = ic.reported_evidence_usage(ctx, {"used_evidence_refs": ["filing", "invented", "rejected"],
          "rejected_evidence_refs": ["rejected"], "judgment_changing_evidence_refs": ["filing", "invented"]})
    assert usage["used_refs"] == usage["judgment_changing_refs"] == ["filing"]
    assert usage["unjoined_reported_refs"] == ["invented"]
    assert usage["graph_edge_refs"] == ["edge-v-filing"]


@pytest.mark.parametrize("rows,expiry,status", [
    ([{"id": 1, "status": "sent", "recommendation": "Answer", "evidence_json": [{"url": "source"}]}], None, "ANSWERED"),
    ([{"id": 1, "status": "sent", "recommendation": "Answer"}], None, "PARTIALLY_ANSWERED"),
    ([{"id": 1, "status": "error", "recommendation": "provider error"}], None, "UNRESOLVED"),
    ([], NOW.isoformat(), "EXPIRED"),
    ([], None, "UNRESOLVED"),
])
def test_question_answer_lifecycle(rows, expiry, status):
    out = ddq.answer_state(rows, expires_at=expiry, now=NOW)
    assert out["status"] == status
    assert out["answer_ids"] == (["hermes_external_research:1"] if rows else [])


def test_question_dry_run_cannot_call_model_or_write(monkeypatch):
    class Cursor:
        def execute(self, query, args=None):
            assert query.startswith("SELECT")
        def fetchone(self):
            return ("due_diligence_questions",)
    class Connection:
        def cursor(self):
            return Cursor()
        def set_session(self, **kwargs):
            assert kwargs == {"readonly": True}
        def close(self):
            pass
        def commit(self):
            pytest.fail("dry-run commit")
    monkeypatch.setattr(ddq, "_db", Connection)
    monkeypatch.setattr(ddq, "pending_changes", lambda *a: [{"symbol": "V"}])
    monkeypatch.setattr(ddq, "ask_model", lambda *a: pytest.fail("dry-run external call"))
    monkeypatch.setattr("sys.argv", ["due_diligence_questions.py"])
    assert ddq.main() == 0


def test_origin_gap_closes_once_without_touching_other_subjects(tmp_path, monkeypatch):
    from scripts.lib import research_gap as gaps
    monkeypatch.setattr(gaps, "_register_on_spine", lambda g: None)
    gap = gaps.build_gap(security_guid="guid-v", symbol="V", reason="margin_data", question="Are margins stable?")
    other = gaps.build_gap(security_guid="guid-ma", symbol="MA", reason="margin_data", question="Are margins stable?")
    gaps.upsert_gap(tmp_path, gap)
    gaps.upsert_gap(tmp_path, other)
    request = {"gap_id": gap["gap_id"], "symbol": "V", "subject_guid": "guid-v"}
    completed = result(as_of=datetime.now(timezone.utc).isoformat(), subject_guid="guid-v",
                       answers=[{"gap_id": gap["gap_id"], "answer": "Margins stable in filing."}])
    first = gaps.reconcile_research_completion(tmp_path, request, completed, critique={"verdict": "VALID"})
    assert first["changes"][0]["answer_status"] == "ANSWERED"
    assert gaps.reconcile_research_completion(tmp_path, request, completed, critique={"verdict": "VALID"})["updated"] == 0
    import json
    rows = [json.loads(line) for line in (tmp_path / gaps.PATH).read_text().splitlines()]
    by_id = {r["gap_id"]: r for r in rows}
    assert by_id[other["gap_id"]]["status"] == "OPEN"
    assert by_id[gap["gap_id"]]["resolved_by_artifact_guids"] == ["result-v-1"]
    assert len(by_id[gap["gap_id"]]["lifecycle_events"]) == 1
