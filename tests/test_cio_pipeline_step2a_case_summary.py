"""Pipeline Step 2A: CASE_SUMMARY from attached VALID Hermes research.

READ_ONLY_ADVISORY. Completeness only. No notify, no action-gate change.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib.agent_durable_memory import DurableJsonlMemoryProvider, get_durable_provider
from scripts.lib.agent_memory_admission import admit_candidate
from scripts.lib.agent_memory_governance import (
    MEMORY_TYPE_CASE_SUMMARY,
    MEMORY_TYPE_RESEARCH_REFERENCE,
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    admit_status,
    is_forbidden_authoritative,
)
from scripts.lib.hermes_case_summary import mint_case_summary_from_attached_research


def _make_plan(store, plan_id="plan_cs_a"):
    return store.create_plan(
        situation_type="S6_CONCENTRATION_OR_DISPOSITION",
        symbols=["SCHD"],
        title="SCHD concentration",
        summary="research requested",
        options=[{"id": "hold", "label": "Hold"}, {"id": "trim", "label": "Trim"}],
        recommendation="Hold pending research",
        evidence_refs=[{"domain": "holdings_detail", "as_of": "2026-08-28"}],
        revisit_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        owner_agent="alex",
        plan_id=plan_id,
        extra={"hermes_research_id": "res_cs_a"},
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
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
        "result_id": "rr_cs_a",
        "research_id": "res_cs_a",
        "plan_id": "plan_cs_a",
        "symbol": "SCHD",
        "status": "completed",
        "summary": "SCHD concentration research as of 2026-08-28. Hold with thesis.",
        "sources": ["https://example.test/schd"],
        "as_of": "2026-08-28T12:00:00+00:00",
        "completed_ts": "2026-08-28T12:00:00+00:00",
        "answers": [
            {"status": "answered", "summary": "Drift is thesis-compatible."},
            {"status": "answered", "summary": "No invalidation printed."},
        ],
    }
    base.update(kw)
    return base


def test_valid_attached_result_mints_one_active_case_summary(env):
    store, root = env
    _make_plan(store)
    from scripts.lib.hermes_research_loop import on_hermes_completed
    out = on_hermes_completed(
        {"plan_id": "plan_cs_a", "research_id": "res_cs_a", "symbol": "SCHD"},
        _valid_result(),
        resynth=False,
        notify=False,
    )
    assert out.get("ok") is True
    assert out.get("notified") in (False, None)
    cs = out.get("case_summary") or {}
    assert cs.get("ok") is True
    mid = cs.get("memory_id")
    assert mid
    prov = get_durable_provider(root)
    rec = prov.get(mid)
    assert rec is not None
    assert rec["memory_type"] == MEMORY_TYPE_CASE_SUMMARY
    assert rec["status"] == STATUS_ACTIVE
    assert rec["authority_class"] == "NON_AUTHORITATIVE_CONTEXT"
    blob = " ".join(str(x) for x in (rec.get("source_refs") or []) + (rec.get("source_event_ids") or []))
    assert "plan_cs_a" in blob and "rr_cs_a" in blob and "res_cs_a" in blob
    assert rec.get("plan_ids") == ["plan_cs_a"]
    receipt = cs.get("receipt") or {}
    assert receipt.get("memory_type") == MEMORY_TYPE_CASE_SUMMARY
    assert receipt.get("promotable") is True
    assert not is_forbidden_authoritative(rec.get("subject"))
    assert not is_forbidden_authoritative(rec.get("content"))
    n = sum(1 for r in prov._store.values() if r.get("memory_type") == MEMORY_TYPE_CASE_SUMMARY)
    assert n == 1


def test_same_plan_result_does_not_mint_second(env):
    store, root = env
    _make_plan(store)
    from scripts.lib.hermes_research_loop import on_hermes_completed
    req = {"plan_id": "plan_cs_a", "research_id": "res_cs_a", "symbol": "SCHD"}
    a = on_hermes_completed(req, _valid_result(), resynth=False, notify=False)
    b = on_hermes_completed(req, _valid_result(), resynth=False, notify=False)
    assert (b.get("case_summary") or {}).get("reason") == "idempotent"
    assert (b.get("case_summary") or {}).get("memory_id") == (a.get("case_summary") or {}).get("memory_id")
    prov = get_durable_provider(root)
    n = sum(1 for r in prov._store.values() if r.get("memory_type") == MEMORY_TYPE_CASE_SUMMARY)
    assert n == 1


def test_failed_result_does_not_mint_case_summary(env):
    store, root = env
    _make_plan(store)
    from scripts.lib.hermes_research_loop import on_hermes_completed
    out = on_hermes_completed(
        {"plan_id": "plan_cs_a", "research_id": "res_cs_a", "symbol": "SCHD"},
        _valid_result(summary="", status="failed"),
        resynth=False,
        notify=False,
    )
    assert out.get("ok") is True
    assert not (out.get("case_summary") or {}).get("ok")
    prov = get_durable_provider(root)
    assert sum(1 for r in prov._store.values() if r.get("memory_type") == MEMORY_TYPE_CASE_SUMMARY) == 0


def test_forbidden_subject_rejects_and_writes_nothing(env):
    _store, root = env
    p = DurableJsonlMemoryProvider(path=root / "data/cio/aif_memory.jsonl")
    rec = admit_candidate(
        {
            "memory_type": MEMORY_TYPE_CASE_SUMMARY,
            "subject": "current price of SCHD",
            "content": "cash holdings and stop state",
            "source_refs": ["plan_cs_a", "res_cs_a", "rr_cs_a"],
            "source_kind": "HERMES_VALID_COMPLETE",
        },
        provider=p,
        admitted_by="test",
    )
    assert rec["accepted"] is False
    assert rec["forbidden_truth_scan"] == "reject"
    assert sum(1 for r in p._store.values() if r.get("memory_type") == MEMORY_TYPE_CASE_SUMMARY) == 0


def test_price_laden_research_rewrites_to_safe_subject(env):
    store, root = env
    plan = _make_plan(store)
    from scripts.lib.cio_plans import CIOPlanStore
    # Pretend Step 1 already joined.
    CIOPlanStore().update_plan("plan_cs_a", **{"hermes_result_id": "rr_cs_a", "research_id": "res_cs_a"})
    plan = CIOPlanStore().get_plan("plan_cs_a")
    result = _valid_result(
        summary="SCHD current price 35.14 holdings 10000 shares cash 500k stop 33.38",
    )
    from scripts.lib.research_quality import critique
    out = mint_case_summary_from_attached_research(plan, result, critique=critique(result))
    assert out.get("ok") is True, out
    rec = get_durable_provider(root).get(out["memory_id"])
    assert rec is not None
    assert rec["subject"].startswith("research_case:")
    assert not is_forbidden_authoritative(rec["subject"])
    assert not is_forbidden_authoritative(rec["content"])
    assert "35.14" not in rec["content"]
    assert "10000" not in rec["content"]


def test_memory_writer_throw_does_not_fail_worker(env, monkeypatch):
    store, _root = env
    _make_plan(store)

    def boom(*a, **k):
        raise RuntimeError("memory_down")

    monkeypatch.setattr(
        "scripts.lib.hermes_case_summary.mint_case_summary_from_attached_research",
        boom,
    )
    monkeypatch.setattr(
        "lib.hermes_case_summary.mint_case_summary_from_attached_research",
        boom,
        raising=False,
    )
    from scripts.lib.hermes_research_loop import on_hermes_completed
    out = on_hermes_completed(
        {"plan_id": "plan_cs_a", "research_id": "res_cs_a", "symbol": "SCHD"},
        _valid_result(),
        resynth=False,
        notify=False,
    )
    assert out.get("ok") is True
    assert out.get("case_summary_error")
    from scripts.lib.cio_plans import CIOPlanStore
    assert CIOPlanStore().get_plan("plan_cs_a")["hermes_result_id"] == "rr_cs_a"


def test_research_reference_still_not_active():
    assert admit_status(MEMORY_TYPE_RESEARCH_REFERENCE, provenance_ok=True, subject="research observation SCHD") == STATUS_CANDIDATE
    assert admit_status(MEMORY_TYPE_CASE_SUMMARY, provenance_ok=True, subject="research_case:SCHD") == STATUS_ACTIVE


def test_hook_does_not_notify_or_flip_material(env, monkeypatch):
    store, _ = env
    _make_plan(store)
    notified = []

    def _no_notify(plan, **kwargs):
        notified.append(plan)
        return True

    monkeypatch.setattr("scripts.lib.cio_plan_enrichment.maybe_notify_plan", _no_notify)
    monkeypatch.setattr("lib.cio_plan_enrichment.maybe_notify_plan", _no_notify, raising=False)

    def _identity_enrich(plan, **kwargs):
        return {"plan": plan, "ok": True}

    monkeypatch.setattr("scripts.lib.cio_plan_enrichment.enrich_plan", _identity_enrich)
    monkeypatch.setattr("lib.cio_plan_enrichment.enrich_plan", _identity_enrich, raising=False)

    from scripts.lib.hermes_research_loop import on_hermes_completed
    out = on_hermes_completed(
        {"plan_id": "plan_cs_a", "research_id": "res_cs_a", "symbol": "SCHD"},
        _valid_result(),
        resynth=True,
        notify=False,
    )
    assert out.get("ok") is True
    assert out.get("material_changed") is False
    assert out.get("notified") in (False, None)
    assert notified == []
