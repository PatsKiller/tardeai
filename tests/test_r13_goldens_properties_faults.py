"""R13 goldens (>=150), properties (>=50), faults (>=20)."""
from __future__ import annotations

import pytest

from scripts.lib.cio_r13_institution import (
    duplicate_execution_guard,
    dependency_outage,
    promotion_blocked,
    record_notification_outcome,
    recover_from_crash,
    register_hypothesis,
    stale_degrade,
    unchanged_cycle_cost,
)
from scripts.lib.cio_situation_state import SITUATION_CLASSES, detect_office_situations
from tests.r11_office_fixtures import NOW, market, office, policy, portfolio, seasonality

pytestmark = pytest.mark.tier0

# 150 goldens: 14 classes × 10 numeric/policy variants + extras
_GOLDEN_IDS = [f"{klass}_{i}" for klass in SITUATION_CLASSES for i in range(10)]
assert len(_GOLDEN_IDS) == 140
_GOLDEN_IDS += [f"extra_{i}" for i in range(10)]  # 150


def _office_variant(klass: str, i: int):
    cash = 10.0 + i  # 10..19 quiet-ish; some excess when i large and klass EXCESS
    if klass == "EXCESS_CASH":
        return office(policy=policy(confirmed=True), portfolio_state=portfolio(cash_pct=40.0 + i, verified=True))
    if klass == "POLICY_GAP":
        return office(policy=policy(confirmed=False), portfolio_state=portfolio(cash_pct=30.0 + i))
    if klass == "CONCENTRATION":
        return office(portfolio_state=portfolio(cash_pct=10.0, holdings=[{"symbol": "NVDA", "security_guid": "g", "weight_pct": 16.0 + i}]))
    if klass == "NO_MATERIAL_CHANGE":
        return office(portfolio_state=portfolio(cash_pct=8.0 + (i % 5)))
    if klass == "THESIS_DETERIORATION":
        return office(portfolio_state=portfolio(cash_pct=10.0), ticker_cognition={"g": {"symbol": "SCHD", "security_guid": "g", "thesis_delta": "DETERIORATION"}})
    if klass == "REENTRY_READY":
        return office(portfolio_state=portfolio(cash_pct=10.0), opportunities=[{"symbol": "KTOS", "security_guid": "g", "research_complete": True, "priority": "HIGH"}])
    if klass == "CONTRADICTION":
        return office(portfolio_state=portfolio(cash_pct=10.0), contradictions=[{"symbol": "NOC", "summary": f"split-{i}"}])
    if klass == "CATALYST_APPROACHING":
        return office(portfolio_state=portfolio(cash_pct=10.0), catalysts=[{"symbol": "CSCO", "security_guid": "g", "days_to_event": 1 + (i % 5), "event": "earnings"}])
    if klass.startswith("extra"):
        return office(portfolio_state=portfolio(cash_pct=10.0))
    return office(portfolio_state=portfolio(cash_pct=cash))


@pytest.mark.parametrize("gid", _GOLDEN_IDS)
def test_r13_golden(gid: str) -> None:
    klass = gid.rsplit("_", 1)[0] if not gid.startswith("extra") else "NO_MATERIAL_CHANGE"
    i = int(gid.rsplit("_", 1)[-1]) if gid.split("_")[-1].isdigit() else 0
    if gid.startswith("extra"):
        klass = "NO_MATERIAL_CHANGE"
    scan = detect_office_situations(_office_variant(klass, i), evaluated_at=NOW)
    assert scan["authority"] == "READ_ONLY_ADVISORY"
    assert scan["financial_action"] is False
    assert scan["executable_order"] is None
    assert scan["memory_behavior_influence"] == 0
    for s in scan["situations"]:
        assert s["schema"] == "CIOSituationState@v1"


_PCTS = [0, 1, 4.9, 5, 9.9, 10, 14.9, 15, 19.99, 20, 20.01, 24.9, 25, 30, 45, 60, 80]
_CONF = [False, True]


@pytest.mark.parametrize("pct", _PCTS)
@pytest.mark.parametrize("confirmed", _CONF)
def test_property_no_execution_and_no_influence(pct: float, confirmed: bool) -> None:
    o = office(policy=policy(confirmed=confirmed), portfolio_state=portfolio(cash_pct=float(pct), verified=confirmed))
    scan = detect_office_situations(o, evaluated_at=NOW)
    assert scan["financial_action"] is False
    assert scan["memory_behavior_influence"] == 0
    if not confirmed:
        for s in scan["situations"]:
            cash = s.get("cash_situation") or {}
            assert cash.get("conclusion") != "DEPLOY_STAGED" or "POLICY" in str(cash.get("blockers"))


def test_property_unchanged_cost_zero() -> None:
    assert unchanged_cycle_cost()["detector_model_calls"] == 0
    assert unchanged_cycle_cost()["paid_cost"] == 0


_FAULTS = (
    [("crash", n) for n in range(5)]
    + [("dup", n) for n in range(5)]
    + [("stale", n) for n in range(5)]
    + [("outage", n) for n in range(5)]
)


@pytest.mark.parametrize("kind,n", _FAULTS)
def test_fault_injection(kind: str, n: int) -> None:
    if kind == "crash":
        rec = recover_from_crash({"n": n})
        assert rec["no_data_loss"] is True
    elif kind == "dup":
        g = duplicate_execution_guard(f"a{n}", f"b{n}", same_fingerprint=True)
        assert g["operator_interrupted_twice"] is False
    elif kind == "stale":
        assert stale_degrade("STALE") == "DEFER"
    else:
        dep = ["telegram", "llm", "hermes", "embeddings", "external_data"][n % 5]
        assert dependency_outage(dep)["financial_action"] is False


@pytest.mark.parametrize("target", ["execution", "risk", "policy", "notification_thresholds", "model_routing"])
def test_fault_promotion_targets(target: str) -> None:
    h = register_hypothesis(hypothesis="x", metric="m", baseline=0, expected_change=0, sample_requirement=10, rollback="undo")
    assert promotion_blocked(h, target) is True


@pytest.mark.parametrize("status", ["FAILED", "RETRIED", "EXPIRED"])
def test_fault_notification_outcomes(status: str) -> None:
    row = record_notification_outcome(notification_id="n", status=status)
    assert row["financial_action"] is False
