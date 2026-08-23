from __future__ import annotations

import scripts.api_v3_cio as api


def test_brain_snapshot_is_derived_advisory_and_surfaces_suppression(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_operator_investment_policy", lambda: {
        "policy": {"version": "policy@v1", "missing_fields": ["cash_target_range"], "legacy_conflicts": []}
    })
    monkeypatch.setattr(api, "get_portfolio_state_v1", lambda: {
        "portfolio_state": {"version": "portfolio@v1", "truth_quality": "UNVERIFIED_INVESTABLE"}
    })
    monkeypatch.setattr(api, "get_market_context_state_v1", lambda: {"market_context": {"version": "market@v1"}})
    monkeypatch.setattr(api, "get_seasonality_state_v1", lambda: {"seasonality": {"version": "seasonality@v1"}})
    monkeypatch.setattr(api, "get_portfolio_thesis_v1", lambda: {
        "published_thesis": {"thesis_version": "cio_portfolio@v2"},
        "candidate": {},
        "candidate_delta": {"classification": "NO_NEW_INFO"},
    })
    monkeypatch.setattr(api, "get_capital_plan_v1", lambda: {
        "situation": {
            "blockers": ["POLICY_REQUIRED"],
            "material": False,
            "notification": {"eligible": False, "suppression_reason": "POLICY_REQUIRED"},
        },
        "capital_plan": {"version": "capital@v1", "next_review": "ON_BLOCKER_RESOLUTION"},
        "published": None,
    })
    monkeypatch.setattr(api, "get_methodology_policy_v1", lambda: {
        "methodology_policy": {"version": "methodology@v1"}, "canon": {"catalog_total": 34}
    })
    monkeypatch.setattr(api, "get_learning_review_v1", lambda: {
        "latest_review": None, "outcomes": {"observation_window": "UNMEASURED_OBSERVATION_WINDOW"}
    })
    monkeypatch.setattr(api, "get_memory_summary_v1", lambda: {
        "status": "OK", "total": 284, "counts": {"CANDIDATE": 280}, "memory_behavior_influence": 0
    })
    monkeypatch.setattr(api, "get_cio_home", lambda: {
        "cio_now": {"decisions": [], "decision_count": 0, "open_plans_count": 2},
        "opportunities": {"research_gaps": [{"symbol": "NOC"}]},
    })

    snapshot = api.get_cio_brain_v1()

    assert snapshot["schema"] == "CIOBrainSnapshot@v1"
    assert snapshot["state"] == "BLOCKED"
    assert snapshot["proactive_cio"]["suppression_reason"] == "POLICY_REQUIRED"
    assert snapshot["versions"]["portfolio_thesis_version"] == "cio_portfolio@v2"
    assert snapshot["memory_behavior_influence"] == 0
    assert snapshot["memory"]["total"] == 284
    assert snapshot["financial_action"] is False
    assert snapshot["executable_order"] is None


def test_brain_snapshot_route_is_registered() -> None:
    source = (api.PROJECT_ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert 'if p == "brain":' in source
    assert "get_cio_brain_v1" in source
