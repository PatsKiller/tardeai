"""CIO Desk observability projection is read-only, truthful, and fail-closed."""

from scripts.lib.cio_observability import build_observability


def _inputs():
    return {
        "home": {
            "ok": True,
            "as_of": "2026-09-30T12:00:00+00:00",
            "cio_now": {
                "decision_count": 4,
                "open_actions_count": 2,
                "open_plans_count": 3,
                "material_today_count": 1,
            },
            "evidence": {"source_sha": "abc"},
        },
        "brain": {
            "ok": True,
            "as_of": "2026-09-30T12:00:00+00:00",
            "operator_policy": {"status": "POLICY_REQUIRED", "required_field_count": 3,
                                 "confirmed_field_count": 1, "missing_fields": ["cash_min", "risk_limit"]},
            "learning": {"outcomes": {"matured": 0}},
            "learning_cockpit": {"outcomes_due": 1127, "lessons_n": 0},
            "memory": {"retrieval_receipts": 0},
            "memory_behavior_influence": 0,
            "_serving": {"pin_match": True, "process_started_at": "2026-09-30T11:00:00+00:00"},
            "proactive_cio": {},
        },
        "research_ops": {"ok": True, "as_of": "2026-09-30T12:00:00+00:00",
                          "queue": {"queued": 5, "by_status": {"running": 1}, "created_today": 10,
                                    "completed_today": 8, "failed_today": 2, "stale_or_superseded": 1}},
        "data_health": {"ok": True, "inventory": {}, "graph_flags": []},
    }


def test_projection_exposes_truthful_counts_and_blockers():
    out = build_observability(**_inputs(), now="2026-09-30T12:00:00+00:00")
    assert out["schema"] == "CIODeskObservability@v1"
    assert out["financial_action"] is False
    assert out["policy"]["missing_count"] == 2
    assert out["recommendation_funnel"][-1] == {"id": "influence", "label": "Memory Influence", "count": 0}
    assert any(f["issue_id"] == "CIO-LEARNING-001" for f in out["findings"])
    research = next(s for s in out["scorecards"] if s["id"] == "hermes_/_research")
    assert research["status"] == "DEGRADED"
    assert research["metrics"]["failed"] == 2


def test_missing_projection_fails_closed_without_mutation():
    out = build_observability(home=None, brain=None, research_ops=None, data_health=None,
                              now="2026-09-30T12:00:00+00:00")
    assert out["overall"]["status"] == "BLOCKED"
    assert all(row["status"] == "BLOCKED" for row in out["scorecards"])
    assert out["financial_action"] is False
