from __future__ import annotations

import scripts.api_v3_cio as api


def test_policy_provenance_endpoint_shape(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_operator_investment_policy", lambda: {
        "policy": {
            "version": "p1",
            "status": "POLICY_REQUIRED",
            "fields": {},
            "missing_fields": ["cash_target_range_pct"],
            "legacy_conflicts": [],
        }
    })
    out = api.get_policy_provenance_v1()
    assert out["ok"] is True
    assert out["cash_target_confirmed"] is False
    assert out["memory_behavior_influence"] == 0
    assert any(r["field"] == "cash_target_range_pct" for r in out["fields"])


def test_brain_snapshot_has_cockpit_keys(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_operator_investment_policy", lambda: {"policy": {"version": "p", "missing_fields": ["cash_target_range_pct"], "legacy_conflicts": []}})
    monkeypatch.setattr(api, "get_portfolio_state_v1", lambda: {"portfolio_state": {"version": "v", "truth_quality": "UNVERIFIED_INVESTABLE"}})
    monkeypatch.setattr(api, "get_market_context_state_v1", lambda: {"market_context": {"version": "m"}})
    monkeypatch.setattr(api, "get_seasonality_state_v1", lambda: {"seasonality": {"version": "s"}})
    monkeypatch.setattr(api, "get_portfolio_thesis_v1", lambda: {"published_thesis": {"thesis_version": "t"}, "candidate": {}, "candidate_delta": {"classification": "NO_NEW_INFO"}})
    monkeypatch.setattr(api, "get_capital_plan_v1", lambda: {"situation": {"blockers": ["POLICY_REQUIRED"], "material": False, "notification": {"eligible": False, "suppression_reason": "POLICY_REQUIRED"}}, "capital_plan": {"next_review": "ON_BLOCKER_RESOLUTION"}, "published": None})
    monkeypatch.setattr(api, "get_methodology_policy_v1", lambda: {"methodology_policy": {"version": "m"}, "canon": {}})
    monkeypatch.setattr(api, "get_learning_review_v1", lambda: {"latest_review": None, "outcomes": {}, "feedback": {}})
    monkeypatch.setattr(api, "get_memory_summary_v1", lambda: {"status": "OK", "total": 1, "counts": {}})
    monkeypatch.setattr(api, "get_cio_home", lambda: {"cio_now": {"decisions": [], "decision_count": 0, "open_plans_count": 0}, "opportunities": {"research_gaps": []}})
    snap = api.get_cio_brain_v1()
    ov = snap["operator_value"]
    for k in ("what_changed", "missing_policy", "uncertainty", "what_was_suppressed", "what_happens_next", "attention"):
        assert k in ov
    assert snap["memory_behavior_influence"] == 0
    src = (api.PROJECT_ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert "brain/policy-provenance" in src
