"""R12 iteration 25 — property-like invariants over cash pct grid."""
from __future__ import annotations

import pytest

from scripts.lib.cio_policy_provenance import audit_cash_posture_policy
from scripts.lib.cio_situation_state import detect_office_situations
from tests.r11_office_fixtures import NOW, office, policy, portfolio

pytestmark = pytest.mark.tier0


@pytest.mark.parametrize("pct", [0.0, 1.0, 5.0, 10.0, 14.9, 15.0, 19.9, 20.0, 20.01, 25.0, 44.9, 45.0, 80.0])
def test_unconfirmed_policy_never_deploy_staged(pct: float) -> None:
    o = office(policy=policy(confirmed=False), portfolio_state=portfolio(cash_pct=pct))
    scan = detect_office_situations(o, evaluated_at=NOW)
    for s in scan["situations"]:
        cash = s.get("cash_situation") or {}
        assert cash.get("conclusion") != "DEPLOY_STAGED"
        assert s.get("financial_action") is False
        assert s.get("executable_order") is None


@pytest.mark.parametrize("pct", [20.01, 25.0, 45.0])
def test_default_above_band_cannot_masquerade(pct: float) -> None:
    out = audit_cash_posture_policy(
        cash_total_usd=pct * 10000.0,
        portfolio_value_usd=1_000_000.0,
        live_band={"min_pct": 20.0, "max_pct": 25.0},
        live_status="ABOVE_BAND",
        policy={"status": "POLICY_REQUIRED", "fields": {}},
    )
    assert out["confirmed_by_operator"] if False else out["policy"]["confirmed_by_operator"] is False
    assert out["may_recommend_deployment"] is False
    assert out["memory_behavior_influence"] == 0
