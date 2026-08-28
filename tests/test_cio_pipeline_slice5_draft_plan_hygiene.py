"""Slice 5: expire stale empty drafts; keep recent material S6."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.lib.cio_draft_plan_hygiene import expire_stale_empty_drafts, is_stale_empty_draft
from scripts.lib.cio_plans import CIOPlanStore


def _store(tmp_path: Path) -> CIOPlanStore:
    return CIOPlanStore(
        event_path=tmp_path / "cio_plans.jsonl",
        projection_path=tmp_path / "cio_plans_projection.json",
    )


def _opts():
    return [{"id": "hold", "label": "Hold"}, {"id": "watch", "label": "Watch"}]


def test_recent_material_s6_kept(tmp_path):
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    store.create_plan(
        situation_type="S6_CONCENTRATION_OR_DISPOSITION",
        symbols=["SCHD"],
        title="SCHD concentration",
        options=_opts(),
        recommendation="Hold pending review",
        evidence_refs=[{"domain": "holdings_detail"}],
        revisit_at=(now - timedelta(days=3)).isoformat(),
        owner_agent="alex",
        extra={"material": True},
    )
    rec = expire_stale_empty_drafts(store, apply=True, now=now)
    assert rec["expired"] == 0
    assert rec["would_expire"] == 0
    plans = list(store._plans.values())
    assert plans[0]["status"] == "draft"


def test_stale_empty_s1_draft_expires(tmp_path):
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    p = store.create_plan(
        situation_type="S1_POSITION_LIFECYCLE",
        symbols=["XYZ"],
        title="stale s1",
        options=_opts(),
        recommendation="Watch",
        evidence_refs=[{"domain": "holdings_detail"}],
        revisit_at=(now - timedelta(days=10)).isoformat(),
        owner_agent="alex",
    )
    assert is_stale_empty_draft(p, now=now)
    rec = expire_stale_empty_drafts(store, apply=True, now=now)
    assert rec["would_expire"] == 1
    assert rec["expired"] == 1
    assert store.get_plan(p["plan_id"])["status"] == "cancelled"
    # jsonl history is append-only, not deleted
    text = Path(store.event_path).read_text()
    assert "PLAN_CREATED" in text
    assert "PLAN_STATUS_CHANGED" in text


def test_draft_with_hermes_result_kept(tmp_path):
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    store.create_plan(
        situation_type="S1_POSITION_LIFECYCLE",
        symbols=["NOC"],
        title="researched",
        options=_opts(),
        recommendation="Hold",
        evidence_refs=[{"domain": "holdings_detail"}],
        revisit_at=(now - timedelta(days=10)).isoformat(),
        owner_agent="alex",
        extra={"hermes_result_id": "rr_keep"},
    )
    rec = expire_stale_empty_drafts(store, apply=True, now=now)
    assert rec["would_expire"] == 0
    assert list(store._plans.values())[0]["status"] == "draft"


def test_dry_run_does_not_write(tmp_path):
    store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    store.create_plan(
        situation_type="S1_POSITION_LIFECYCLE",
        symbols=["AAA"],
        title="stale",
        options=_opts(),
        recommendation="Watch",
        evidence_refs=[{"domain": "holdings_detail"}],
        revisit_at=(now - timedelta(days=2)).isoformat(),
        owner_agent="alex",
    )
    rec = expire_stale_empty_drafts(store, apply=False, now=now)
    assert rec["would_expire"] == 1
    assert rec["expired"] == 0
    assert list(store._plans.values())[0]["status"] == "draft"
