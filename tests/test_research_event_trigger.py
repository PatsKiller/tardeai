from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.lib.research_event_trigger import plan_research_trigger

NOW = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)


def test_due_intersection_requires_change_stale_or_trigger():
    quiet = plan_research_trigger(
        symbol="NOC", memberships=["HELD"], due=True, changed=False, stale=False, now=NOW,
    )
    assert quiet["triggered"] is False
    changed = plan_research_trigger(
        symbol="NOC", memberships=["HELD"], due=True, changed=True, stale=False, now=NOW,
    )
    assert changed["triggered"] is True


def test_atr_rvol_and_material_event_trigger():
    row = plan_research_trigger(
        symbol="NOC",
        memberships=["REENTRY"],
        due=True,
        changed=False,
        stale=False,
        current_market={"price": 112.5, "atr": 10, "rvol": 2.4},
        previous_market={"price": 100, "atr": 10},
        events=[{"id": "ce1", "type": "GUIDANCE", "severity": "HIGH"}],
        now=NOW,
    )
    assert row["triggered"] is True
    assert {reason["type"] for reason in row["trigger_reasons"]} == {"ATR_MOVE", "RVOL_SHOCK", "GUIDANCE"}


def test_nonmaterial_symbol_and_low_event_do_not_trigger():
    row = plan_research_trigger(
        symbol="COLD",
        memberships=["COLD"],
        due=True,
        changed=True,
        stale=True,
        events=[{"id": "ce1", "type": "EARNINGS", "severity": "LOW"}],
        now=NOW,
    )
    assert row["triggered"] is False


def test_dwell_dedup_suppresses_catalyst_storm(tmp_path):
    ledger = tmp_path / "triggers.jsonl"
    kwargs = dict(
        symbol="NOC",
        memberships=["HELD"],
        due=True,
        changed=False,
        stale=False,
        events=[{"id": "ce1", "type": "SEC", "severity": "MEDIUM"}],
        ledger_path=ledger,
        persist=True,
    )
    first = plan_research_trigger(**kwargs, now=NOW)
    second = plan_research_trigger(**kwargs, now=NOW + timedelta(hours=1))
    third = plan_research_trigger(**kwargs, now=NOW + timedelta(hours=7))
    assert first["triggered"] is True
    assert second["triggered"] is False
    assert second["suppression_reason"] == "DWELL_DUPLICATE"
    assert third["triggered"] is True


def test_need_data_and_invalidation_are_symmetric_triggers():
    need = plan_research_trigger(
        symbol="NOC", memberships=["HELD"], due=True, changed=False, stale=False,
        operator_need_data=True, now=NOW,
    )
    invalidated = plan_research_trigger(
        symbol="NOC", memberships=["HELD"], due=True, changed=False, stale=False,
        invalidation_triggered=True, now=NOW,
    )
    assert need["trigger_reasons"] == [{"type": "OPERATOR_NEED_DATA"}]
    assert invalidated["trigger_reasons"] == [{"type": "INVALIDATION_TRIGGER"}]
    assert need["triggered"] and invalidated["triggered"]
