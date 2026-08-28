"""Pipeline Step 1: research join on the originating plan + honest CIO synthesis ledger.

READ_ONLY_ADVISORY. No notify, no broker, no action-gate change.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _make_plan(store, plan_id="plan_step1a"):
    return store.create_plan(
        situation_type="S6_CONCENTRATION_OR_DISPOSITION",
        symbols=["SCHD"],
        title="SCHD concentration",
        summary="research requested",
        options=[
            {"id": "hold", "label": "Hold"},
            {"id": "trim", "label": "Trim"},
        ],
        recommendation="Hold pending research",
        evidence_refs=[{"domain": "holdings_detail", "as_of": "2026-08-28"}],
        revisit_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        owner_agent="alex",
        plan_id=plan_id,
        extra={"hermes_research_id": "res_step1"},
    )


@pytest.fixture
def step1_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "cio").mkdir(parents=True)
    (tmp_path / "logs").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    monkeypatch.setenv("CIO_SITUATION_NOTIFY", "0")
    from scripts.lib.cio_plans import CIOPlanStore
    return CIOPlanStore(), tmp_path


def _valid_result(**kw):
    base = {
        "result_id": "rr_step1",
        "research_id": "res_step1",
        "plan_id": "plan_step1a",
        "symbol": "SCHD",
        "status": "completed",
        "summary": "SCHD concentration research as of 2026-08-28. Hold with thesis.",
        "sources": ["https://example.test/schd"],
        "as_of": "2026-08-28T12:00:00+00:00",
        "completed_ts": "2026-08-28T12:00:00+00:00",
    }
    base.update(kw)
    return base


def test_completed_valid_result_stamps_hermes_result_id(step1_cwd):
    store, _ = step1_cwd
    _make_plan(store)
    from scripts.lib.hermes_research_loop import on_hermes_completed
    out = on_hermes_completed(
        {"plan_id": "plan_step1a", "research_id": "res_step1", "symbol": "SCHD"},
        _valid_result(),
        resynth=False,
        notify=False,
    )
    assert out.get("ok") is True
    from scripts.lib.cio_plans import CIOPlanStore
    plan = CIOPlanStore().get_plan("plan_step1a")
    assert plan["hermes_result_id"] == "rr_step1"
    assert plan.get("research_id") == "res_step1" or plan.get("hermes_research_id") == "res_step1"
    assert plan.get("completed_ts") or plan.get("hermes_completed_ts")
    assert plan["plan_id"] == "plan_step1a"


def test_second_complete_same_ids_does_not_fork_plan(step1_cwd):
    store, _ = step1_cwd
    _make_plan(store)
    from scripts.lib.hermes_research_loop import on_hermes_completed
    req = {"plan_id": "plan_step1a", "research_id": "res_step1", "symbol": "SCHD"}
    on_hermes_completed(req, _valid_result(), resynth=False, notify=False)
    on_hermes_completed(req, _valid_result(), resynth=False, notify=False)
    from scripts.lib.cio_plans import CIOPlanStore
    folded = CIOPlanStore()
    assert len(folded._plans) == 1
    assert folded.get_plan("plan_step1a")["hermes_result_id"] == "rr_step1"


def test_failed_or_insufficient_result_does_not_join(step1_cwd):
    store, _ = step1_cwd
    _make_plan(store)
    from scripts.lib.hermes_research_loop import on_hermes_completed
    out = on_hermes_completed(
        {"plan_id": "plan_step1a", "research_id": "res_step1", "symbol": "SCHD"},
        _valid_result(summary="", status="completed"),
        resynth=False,
        notify=False,
    )
    assert out.get("ok") is True
    from scripts.lib.cio_plans import CIOPlanStore
    plan = CIOPlanStore().get_plan("plan_step1a")
    assert not plan.get("hermes_result_id")

    store.create_plan(
        situation_type="S1_POSITION_LIFECYCLE",
        symbols=["V"],
        title="fail",
        summary="s",
        options=[{"id": "hold", "label": "Hold"}, {"id": "trim", "label": "Trim"}],
        recommendation="hold",
        evidence_refs=[{"domain": "holdings_detail", "as_of": "2026-08-28"}],
        revisit_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        owner_agent="alex",
        plan_id="plan_fail",
    )
    on_hermes_completed(
        {"plan_id": "plan_fail", "research_id": "res_fail"},
        _valid_result(plan_id="plan_fail", research_id="res_fail", result_id="rr_fail", status="failed"),
        resynth=False,
        notify=False,
    )
    assert not CIOPlanStore().get_plan("plan_fail").get("hermes_result_id")


def test_attach_throw_does_not_raise_and_notes_stall(step1_cwd, monkeypatch):
    store, root = step1_cwd
    _make_plan(store)
    result_path = root / "data" / "cio" / "hermes_research_results.jsonl"
    result_path.write_text(json.dumps(_valid_result()) + "\n", encoding="utf-8")

    from scripts.lib.cio_plans import CIOPlanStore

    def boom(self, *a, **k):
        raise RuntimeError("attach_fail")

    monkeypatch.setattr(CIOPlanStore, "update_plan", boom)
    monkeypatch.setattr("lib.cio_plans.CIOPlanStore.update_plan", boom, raising=False)
    from scripts.lib.hermes_research_loop import on_hermes_completed
    out = on_hermes_completed(
        {"plan_id": "plan_step1a", "research_id": "res_step1", "symbol": "SCHD"},
        _valid_result(),
        resynth=False,
        notify=False,
    )
    assert out.get("ok") is True
    assert out.get("attach_error")
    persisted = result_path.read_text(encoding="utf-8")
    assert "rr_step1" in persisted
    stall = root / "logs" / "lineage_stalls.jsonl"
    assert stall.exists()
    assert "attach_fail" in stall.read_text(encoding="utf-8")


def test_fingerprint_join_is_not_material_change(step1_cwd, monkeypatch):
    store, _ = step1_cwd
    _make_plan(store)
    from scripts.lib import hermes_research_loop as loop

    from scripts.lib.cio_plans import CIOPlanStore
    plan0 = store.get_plan("plan_step1a")
    assert not plan0.get("hermes_result_id")
    before_join = loop._material_fingerprint(plan0)
    before_sub = loop._substantive_fingerprint(plan0)

    def _identity_enrich(plan, **kwargs):
        return {"plan": plan, "ok": True}

    monkeypatch.setattr("scripts.lib.cio_plan_enrichment.enrich_plan", _identity_enrich)
    monkeypatch.setattr("lib.cio_plan_enrichment.enrich_plan", _identity_enrich, raising=False)

    out = loop.on_hermes_completed(
        {"plan_id": "plan_step1a", "research_id": "res_step1", "symbol": "SCHD"},
        _valid_result(),
        resynth=True,
        notify=False,
    )
    plan1 = CIOPlanStore().get_plan("plan_step1a")
    assert plan1["hermes_result_id"] == "rr_step1"
    after_join = loop._material_fingerprint(plan1)
    after_sub = loop._substantive_fingerprint(plan1)
    assert after_join != before_join
    assert after_sub == before_sub
    assert out.get("material_changed") is False
    assert out.get("notified") is False


def test_deterministic_synthesis_fn_records_no_model_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    (tmp_path / "data" / "cio").mkdir(parents=True)

    from scripts.lib.cio_run import CIORunStore
    from scripts.lib.cio_run_worker import CIORunWorker
    from scripts.lib.cio_investment_product import build_investment_product_synthesis_fn

    store = CIORunStore(str(tmp_path / "data" / "cio" / "cio_runs.jsonl"))
    store.initialize()
    created = store.create_run(trigger_type="MANUAL", trigger_ref="step1", actor="test")
    run_id = created["payload"]["run_id"]
    fn = build_investment_product_synthesis_fn(root=tmp_path)
    worker = CIORunWorker(run_store=store, synthesis_fn=fn, mode="shadow")
    worker._run_id = run_id
    out = worker._cio_synthesis(
        {"run_id": run_id, "context": {}},
        {"snapshot_id": "snap_step1"},
        {"artifacts": []},
        {},
    )
    result = out["result"]
    assert out.get("llm_dispatch") is False
    assert result.get("llm_dispatch") is False
    assert result.get("model_calls") == 0
    assert result.get("cost_usd") == 0.0
    assert result.get("dispatch_kind") == "DETERMINISTIC_PRODUCT"
    assert worker._call_count == 0
    assert worker._cost_accrued == 0.0
    events = []
    for line in Path(store.store_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    model_events = [e for e in events if e.get("event_type") == "CIO_RUN_MODEL_CALL_RECORDED"]
    assert model_events == []
    assert not any(
        (e.get("payload") or {}).get("cost_usd") == 0.001
        for e in events
    )
    assert (tmp_path / "data" / "cio" / "cio_investment_brief.json").is_file()


def test_fallback_and_timer_paths_stay_honest(tmp_path):
    from scripts.lib.cio_run import CIORunStore
    from scripts.lib.cio_run_worker import CIORunWorker

    store = CIORunStore(str(tmp_path / "cio_runs.jsonl"))
    store.initialize()
    created = store.create_run(trigger_type="MANUAL", trigger_ref="step1b", actor="test")
    run_id = created["payload"]["run_id"]
    worker = CIORunWorker(run_store=store, synthesis_fn=None, mode="shadow")
    worker._run_id = run_id
    out = worker._cio_synthesis({"run_id": run_id, "context": {}}, {"snapshot_id": "s"}, {}, {})
    assert out.get("llm_dispatch") is False
    assert out["result"]["dispatch_kind"] == "DETERMINISTIC_PRODUCT"
    assert worker._cost_accrued == 0.0

    worker._load_persistent_cognition = lambda run, snapshot: {
        "portfolio_call": "NO_PORTFOLIO_CHANGE",
        "items": [{"symbol": "SCHD"}],
        "llm_eligible": False,
    }
    timed = worker._cio_synthesis({"run_id": run_id}, {"snapshot_id": "s"}, {}, {})
    assert timed.get("llm_dispatch") is False
    events = [
        json.loads(l)
        for l in Path(store.store_path).read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    assert [e for e in events if e.get("event_type") == "CIO_RUN_MODEL_CALL_RECORDED"] == []
