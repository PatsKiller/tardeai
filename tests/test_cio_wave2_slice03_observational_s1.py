"""Wave 2 slice 03: observational S1 for held-without-open-plan. Cap 5. No notify."""
from __future__ import annotations

from scripts.lib.cio_observational_s1 import (
    apply_observational_s1,
    collect_held_without_open_s1,
)
from scripts.lib.cio_plans import CIOPlanStore


def test_cusip_and_cash_skipped():
    dry = collect_held_without_open_s1(
        holdings={"holdings": [
            {"symbol": "CASH", "quantity": 100},
            {"symbol": "12507E201", "quantity": 10},
            {"symbol": "LDOS", "quantity": 1, "asset_type": "equity"},
        ]},
        plans=None,
        cap=5,
    )
    assert dry["held"] == ["LDOS"]
    assert dry["would_n"] == 1
    assert dry["would"][0]["symbol"] == "LDOS"
    assert dry["notify"] is False


def test_skip_if_open_s1_exists(tmp_path):
    store = CIOPlanStore(
        event_path=tmp_path / "cio_plans.jsonl",
        projection_path=tmp_path / "cio_plans_projection.json",
    )
    store.create_plan(
        situation_type="S1_POSITION_LIFECYCLE",
        symbols=["RTX"],
        title="existing S1",
        options=[{"id": "keep", "label": "keep"}],
        recommendation="already open",
        evidence_refs=[{"domain": "holdings", "source": "test"}],
        revisit_at="2099-01-01T00:00:00+00:00",
        owner_agent="alex",
        status="draft",
    )
    dry = collect_held_without_open_s1(
        holdings={"holdings": [
            {"symbol": "RTX", "quantity": 1, "asset_type": "equity"},
            {"symbol": "SCHG", "quantity": 1, "asset_type": "equity"},
        ]},
        plans=store,
        cap=5,
    )
    assert "RTX" in dry["skipped_open_s1"]
    assert [r["symbol"] for r in dry["would"]] == ["SCHG"]


def test_cap_five():
    holds = [{"symbol": f"AAA{i}", "quantity": 1, "asset_type": "equity"} for i in range(8)]
    # AAA0.. must look like tickers; use real-shaped 4-letter
    holds = [{"symbol": s, "quantity": 1, "asset_type": "equity"}
             for s in ("PFLT", "SCHG", "RTX", "LDOS", "DIV", "BAH", "CSWC", "XAR")]
    dry = collect_held_without_open_s1(holdings={"holdings": holds}, plans=None, cap=5)
    assert dry["would_n"] == 5
    assert [r["symbol"] for r in dry["would"]] == ["PFLT", "SCHG", "RTX", "LDOS", "DIV"]


def test_apply_writes_observational_drafts_no_notify(tmp_path):
    store = CIOPlanStore(
        event_path=tmp_path / "cio_plans.jsonl",
        projection_path=tmp_path / "cio_plans_projection.json",
    )
    dry = collect_held_without_open_s1(
        holdings={"holdings": [{"symbol": "LDOS", "quantity": 1, "asset_type": "equity"}]},
        plans=store,
        cap=5,
    )
    receipt = apply_observational_s1(dry, plans=store, apply=True)
    assert receipt["applied_n"] == 1
    assert receipt["notify"] is False
    plan = store.list_open_plans(situation_type="S1_POSITION_LIFECYCLE", symbol="LDOS", limit=1)[0]
    assert plan["status"] == "draft"
    assert plan.get("observational_only") is True
    # second pass skips
    dry2 = collect_held_without_open_s1(
        holdings={"holdings": [{"symbol": "LDOS", "quantity": 1, "asset_type": "equity"}]},
        plans=store,
        cap=5,
    )
    assert dry2["would_n"] == 0
    assert "LDOS" in dry2["skipped_open_s1"]
