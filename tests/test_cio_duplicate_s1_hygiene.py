"""Duplicate S1 hygiene — keep newest per symbol, expire revisit-overdue only.

Operator judgment 2026-08-29: *"Do not mass-cancel. Dry: keep newest open per
symbol; expire revisit-overdue dups only."*

The two constraints are the point. A name must keep its lifecycle plan, and a
duplicate that is not yet stale is redundant but not wrong — expiring it would
be a judgment about the plan rather than about the backlog.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.lib.cio_duplicate_s1_hygiene import (
    REASON,
    expire_duplicate_s1,
    select_duplicate_s1,
)

NOW = datetime(2026, 8, 29, 5, 0, tzinfo=timezone.utc)
S1 = "S1_POSITION_LIFECYCLE"


def _plan(pid, sym, days_old, revisit_days):
    return {
        "plan_id": pid, "situation_type": S1, "symbols": [sym], "status": "draft",
        "created_ts": (NOW - timedelta(days=days_old)).isoformat(),
        "revisit_at": (NOW + timedelta(days=revisit_days)).isoformat(),
    }


class _Store:
    def __init__(self, plans):
        self.plans = plans
        self.updates = []

    def list_open_plans(self, *, situation_type=None, limit=0):
        return [p for p in self.plans
                if not situation_type or p.get("situation_type") == situation_type]

    def update_plan(self, plan_id, **kw):
        self.updates.append((plan_id, kw))


PLANS = [
    _plan("p_new", "XLI", 0, +1),      # newest, still fresh
    _plan("p_old1", "XLI", 5, -3),     # duplicate, overdue
    _plan("p_old2", "XLI", 9, -7),     # duplicate, overdue
    _plan("p_fresh_dup", "XLI", 2, +2),  # duplicate, NOT overdue
    _plan("p_solo", "SCHD", 4, -2),    # only plan for its symbol
]


def test_newest_per_symbol_is_always_kept():
    out = select_duplicate_s1(_Store(PLANS), now=NOW)
    assert out["kept_newest_per_symbol"]["XLI"] == "p_new"
    assert "p_new" not in {r["plan_id"] for r in out["expire"]}


def test_only_revisit_overdue_duplicates_expire():
    out = select_duplicate_s1(_Store(PLANS), now=NOW)
    assert {r["plan_id"] for r in out["expire"]} == {"p_old1", "p_old2"}


def test_a_duplicate_that_is_not_overdue_is_left_alone():
    out = select_duplicate_s1(_Store(PLANS), now=NOW)
    assert "p_fresh_dup" in {r["plan_id"] for r in out["retained_not_overdue"]}
    assert out["retained_not_overdue_n"] == 1


def test_a_lone_plan_is_never_touched_even_when_overdue():
    """SCHD has one plan. Overdue or not, it is the symbol's only coverage."""
    out = select_duplicate_s1(_Store(PLANS), now=NOW)
    assert "p_solo" not in {r["plan_id"] for r in out["expire"]}
    assert out["kept_newest_per_symbol"]["SCHD"] == "p_solo"


def test_dry_by_default_writes_nothing():
    store = _Store(PLANS)
    out = expire_duplicate_s1(store, now=NOW, apply=False)
    assert out["would_expire"] == 2
    assert out["expired"] == 0
    assert store.updates == []
    assert out["notify"] is False


def test_apply_cancels_and_never_deletes():
    store = _Store(PLANS)
    out = expire_duplicate_s1(store, now=NOW, apply=True)
    assert out["expired"] == 2
    assert out["deletes_history"] is False
    for _pid, kw in store.updates:
        assert kw["status"] == "cancelled"
        assert kw["status_reason"] == REASON
        assert "delete" not in kw


def test_a_plan_with_no_revisit_at_is_not_expired():
    """No revisit date means no evidence it is stale."""
    plans = [_plan("a", "ZZZX", 0, +1), {**_plan("b", "ZZZX", 5, -1), "revisit_at": None}]
    out = select_duplicate_s1(_Store(plans), now=NOW)
    assert out["expire"] == []
    assert out["retained_not_overdue_n"] == 1
