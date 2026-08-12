"""Hermes research loop + worker: claim, complete, de-dupe, attach, fail-soft."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def hermes_tmp(tmp_path, monkeypatch):
    import lib.cio_hermes_research as hr

    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "cio").mkdir(parents=True)
    monkeypatch.setattr(hr, "REQUEST_PATH", Path("data/cio/hermes_research_requests.jsonl"))
    monkeypatch.setattr(hr, "RESULT_PATH", Path("data/cio/hermes_research_results.jsonl"))
    monkeypatch.setattr(hr, "PROJECTION_PATH", Path("data/cio/hermes_research_projection.json"))
    return hr


def _plan(**kw):
    base = {
        "plan_id": "plan_loop_1",
        "situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
        "symbols": ["SCHD"],
        "thesis_version": "desk@v5",
        "fire_reasons": ["weight_17.5pct"],
    }
    base.update(kw)
    return base


def test_enqueue_duplicate_in_flight(hermes_tmp):
    hr = hermes_tmp
    r1 = hr.enqueue_research_request(_plan(), priority="normal")
    assert r1["ok"] and r1["created"]
    rid = r1["research_id"]
    r2 = hr.enqueue_research_request(_plan(), priority="normal")
    assert r2["ok"]
    assert r2["deduped"] or r2["reason"] == "duplicate_in_flight"
    assert r2["research_id"] == rid


def test_claim_run_complete_with_stub(hermes_tmp):
    hr = hermes_tmp
    from lib.hermes_worker import HermesWorker, StubResearchBackend

    enq = hr.enqueue_research_request(_plan(plan_id="plan_w1"), priority="high")
    assert enq["created"]
    rid = enq["research_id"]

    done = []

    def _on_completed(req, result):
        done.append((req.get("research_id"), result.get("result_id")))

    w = HermesWorker(
        store=hr,
        backend=StubResearchBackend(),
        worker_id="test-w1",
        on_completed=_on_completed,
    )
    summary = w.run_once(limit=1)
    assert summary["claimed"] == 1
    assert summary["completed"] == 1
    assert done and done[0][0] == rid

    meta = hr.get_request(rid)
    assert meta is None or meta.get("status") in ("completed", "running", None)
    # projection status
    proj = hr._load_projection()
    assert proj["by_research_id"][rid]["status"] == "completed"
    assert proj["by_research_id"][rid].get("latest_result_id")


def test_ttl_reuse_no_second_run(hermes_tmp):
    hr = hermes_tmp
    from lib.hermes_worker import HermesWorker, StubResearchBackend

    p = _plan(plan_id="plan_ttl")
    enq = hr.enqueue_research_request(p, priority="high")
    w = HermesWorker(store=hr, backend=StubResearchBackend(), worker_id="w-ttl")
    w.run_once(limit=1)

    # Second enqueue within TTL → reuse
    r2 = hr.enqueue_research_request(p, priority="high")
    assert r2["ok"]
    assert r2["reason"] == "reused_fresh_result"
    assert r2["reused"] is True


def test_force_refresh_bypasses_ttl(hermes_tmp):
    hr = hermes_tmp
    from lib.hermes_worker import HermesWorker, StubResearchBackend

    p = _plan(plan_id="plan_force")
    hr.enqueue_research_request(p, priority="high")
    HermesWorker(store=hr, backend=StubResearchBackend(), worker_id="w-f").run_once(limit=1)

    r = hr.enqueue_research_request(p, priority="high", force_refresh=True, operator_forced=True)
    assert r["ok"]
    assert r["created"] is True
    assert r["reason"] == "created"


def test_order_language_rejected(hermes_tmp):
    hr = hermes_tmp
    from lib.hermes_worker import HermesWorker, HermesWorkerError

    class BadBackend:
        def run(self, request):
            return {
                "answers": [{"question_id": "q1", "status": "answered", "summary": "buy now", "confidence": 0.9}],
                "findings": ["place stop under 100"],
                "summary": "buy now the dip",
            }

    enq = hr.enqueue_research_request(_plan(plan_id="plan_bad"), priority="normal")
    w = HermesWorker(store=hr, backend=BadBackend(), worker_id="w-bad")
    summary = w.run_once(limit=1)
    assert summary["failed"] == 1
    rid = enq["research_id"]
    assert hr._load_projection()["by_research_id"][rid]["status"] == "failed"


def test_empty_queue_zeros(hermes_tmp):
    from lib.hermes_worker import HermesWorker, StubResearchBackend

    w = HermesWorker(store=hermes_tmp, backend=StubResearchBackend(), worker_id="w-empty")
    s = w.run_once(limit=3)
    assert s["claimed"] == 0
    assert s["completed"] == 0


def test_claim_cannot_double(hermes_tmp):
    hr = hermes_tmp
    hr.enqueue_research_request(_plan(plan_id="plan_race"), priority="critical")
    c1 = hr.claim_next(worker_id="w1", limit=1)
    c2 = hr.claim_next(worker_id="w2", limit=1)
    assert len(c1) == 1
    assert len(c2) == 0


def test_should_enqueue_escalation():
    from lib.hermes_research_loop import should_enqueue_for_plan

    ok, pri, reason = should_enqueue_for_plan({
        "situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
        "fire_reasons": ["weight_17pct"],
    })
    assert ok and pri == "high"
    ok2, pri2, _ = should_enqueue_for_plan({
        "situation_type": "S1_POSITION_LIFECYCLE",
        "fire_reasons": ["deep_drawdown_from_basis_26pct"],
    })
    assert ok2 and pri2 == "high"
    ok3, _, r3 = should_enqueue_for_plan({"situation_type": "S0_OPERATOR_CONVERSE"})
    assert not ok3


def test_evidence_domain_shape():
    from lib.hermes_research_schema import evidence_domain_from_result, lint_execution_language

    assert lint_execution_language("buy now") is not None
    assert lint_execution_language("hold with thesis") is None
    dom = evidence_domain_from_result({
        "research_id": "res_x",
        "result_id": "rr_x",
        "as_of": "2026-08-12T00:00:00+00:00",
        "status": "completed",
        "summary": "observe",
        "findings": ["no force deploy"],
        "answers": [{"confidence": 0.6}],
        "desk_implications": {"suggestion_bias": "hold_with_thesis", "watch_triggers": ["weight>=16.5"]},
    })
    assert dom["domain"] == "hermes_research"
    assert dom["quality_state"] == "OK"
    assert dom["desk_bias"] == "hold_with_thesis"
