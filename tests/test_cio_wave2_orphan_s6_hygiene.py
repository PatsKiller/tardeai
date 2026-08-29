"""Operator-authorised orphan-S6 hygiene (follow-up to slice 16).

An S6_CONCENTRATION_OR_DISPOSITION plan asks a question that presupposes a
position. Slice 16 surfaced three open S6 plans with no such subject: CASH
(category error), QCOM (not owned) and dust SRNE (the SCHG mistake again).

Cancel, never delete. Dry by default. notify false.
"""
from __future__ import annotations

from scripts.lib.cio_orphan_s6_hygiene import (
    CASH_SLEEVE,
    DUST_RESIDUAL,
    NOT_HELD,
    S6,
    cancel_orphan_s6,
    orphan_reason,
    select_orphan_s6,
)

HOLDINGS = {"holdings": [
    {"symbol": "SCHD", "market_value": 365694.75},
    {"symbol": "BND", "market_value": 55.91},
    {"symbol": "SRNE", "market_value": 0.90},          # dust
    {"symbol": "SCHG", "market_value": 8.09},          # dust
    {"symbol": "CASH", "is_cash": True, "market_value": 585917.80},
]}

HELD = {"SCHD", "BND"}
DUST = {"SRNE", "SCHG"}
CASH = {"CASH", "USD", "SPAXX", "VMFXX", "FDRXX", "TEST"}


def _reason(symbols):
    return orphan_reason(symbols, held_non_dust=HELD, dust=DUST, cash_symbols=CASH)


def test_a_real_held_subject_is_not_orphaned():
    assert _reason(["SCHD"]) is None
    assert _reason(["BND"]) is None


def test_cash_qcom_and_dust_are_each_classified_distinctly():
    assert _reason(["CASH"]) == CASH_SLEEVE
    assert _reason(["QCOM"]) == NOT_HELD
    assert _reason(["SRNE"]) == DUST_RESIDUAL
    assert _reason(["SCHG"]) == DUST_RESIDUAL


def test_one_bad_leg_does_not_orphan_a_multi_symbol_plan():
    """A plan naming a real hold keeps its subject even beside a dust leg."""
    assert _reason(["SCHD", "SRNE"]) is None
    assert _reason(["SRNE", "QCOM"]) == NOT_HELD


def test_empty_symbols_is_its_own_reason():
    assert _reason([]) == "no_symbols"


class _Store:
    def __init__(self, plans):
        self.plans = plans
        self.updates: list[tuple] = []

    def list_open_plans(self, *, situation_type=None, limit=0):
        return [p for p in self.plans
                if not situation_type or p.get("situation_type") == situation_type]

    def update_plan(self, plan_id, **kw):
        self.updates.append((plan_id, kw))


PLANS = [
    {"plan_id": "p_cash", "situation_type": S6, "symbols": ["CASH"], "status": "draft"},
    {"plan_id": "p_qcom", "situation_type": S6, "symbols": ["QCOM"], "status": "draft"},
    {"plan_id": "p_srne", "situation_type": S6, "symbols": ["SRNE"], "status": "proposed"},
    {"plan_id": "p_schd", "situation_type": S6, "symbols": ["SCHD"], "status": "draft"},
    {"plan_id": "p_s1", "situation_type": "S1_POSITION_LIFECYCLE",
     "symbols": ["SRNE"], "status": "draft"},
]


def test_only_orphaned_s6_is_selected():
    rows = select_orphan_s6(_Store(PLANS), holdings=HOLDINGS)
    assert {r["plan_id"] for r in rows} == {"p_cash", "p_qcom", "p_srne"}


def test_a_dust_s1_is_left_alone():
    """Scope is S6. Slice 12c already keeps S1 off dust; do not double-govern."""
    rows = select_orphan_s6(_Store(PLANS), holdings=HOLDINGS)
    assert "p_s1" not in {r["plan_id"] for r in rows}


def test_dry_by_default_writes_nothing():
    store = _Store(PLANS)
    out = cancel_orphan_s6(store, holdings=HOLDINGS, apply=False)
    assert out["would_cancel"] == 3
    assert out["cancelled"] == 0
    assert store.updates == []
    assert out["notify"] is False
    assert out["financial_action"] is False


def test_apply_cancels_and_never_deletes():
    store = _Store(PLANS)
    out = cancel_orphan_s6(store, holdings=HOLDINGS, apply=True)
    assert out["cancelled"] == 3
    assert out["deletes_history"] is False
    assert len(store.updates) == 3
    for _pid, kw in store.updates:
        assert kw["status"] == "cancelled"
        assert kw["status_reason"].startswith("s6_subject_not_held_non_dust:")
        assert kw["actor_id"] == "cio_orphan_s6_hygiene"
        assert "delete" not in kw


def test_reason_is_carried_into_the_cancel_status_reason():
    store = _Store(PLANS)
    cancel_orphan_s6(store, holdings=HOLDINGS, apply=True)
    reasons = {pid: kw["status_reason"] for pid, kw in store.updates}
    assert reasons["p_cash"].endswith(CASH_SLEEVE)
    assert reasons["p_qcom"].endswith(NOT_HELD)
    assert reasons["p_srne"].endswith(DUST_RESIDUAL)


def test_counts_by_reason_and_symbol():
    out = cancel_orphan_s6(_Store(PLANS), holdings=HOLDINGS, apply=False)
    assert out["by_reason"] == {CASH_SLEEVE: 1, NOT_HELD: 1, DUST_RESIDUAL: 1}
    assert out["by_symbol"] == {"CASH": 1, "QCOM": 1, "SRNE": 1}
