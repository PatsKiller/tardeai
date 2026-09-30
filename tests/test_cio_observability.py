"""CIO Desk observability projection is read-only, truthful, and fail-closed."""

from scripts.lib.cio_observability import build_observability
from scripts.lib.data_store_inventory import writer_reader_graph
from scripts.api_v3_cio import classify_research_failure_message


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


def test_unverified_serving_envelope_is_explained():
    inputs = _inputs()
    inputs["brain"].pop("_serving")
    out = build_observability(**inputs, now="2026-09-30T12:00:00+00:00")
    platform = next(row for row in out["scorecards"] if row["id"] == "platform_/_pin")
    assert platform["status"] == "BLOCKED"
    assert platform["blocker"] == "serving freshness envelope unavailable"


def test_shared_spine_flags_have_root_cause_finding():
    inputs = _inputs()
    inputs["data_health"]["graph_flags"] = [
        {"store_id": "cio.product.current", "flag": "STALE_READER", "filenames": ["legacy.json"]},
        {"store_id": "cio.product.current", "flag": "DUPLICATE_CURRENT_PROJECTION_ALIASES"},
    ]
    out = build_observability(**inputs, now="2026-09-30T12:00:00+00:00")
    finding = next(row for row in out["findings"] if row["issue_id"] == "CIO-SPINE-001")
    assert "legacy.json" in finding["root_cause"]
    assert "duplicate current-projection aliases" in finding["root_cause"]


def test_registry_compatibility_aliases_are_not_runtime_failures():
    graph = writer_reader_graph()
    assert graph["flags"] == []
    assert any(row["store_id"] == "cio.product.current" for row in graph["compatibility_aliases"])


def test_research_failure_classes_preserve_safety_and_data_root_causes():
    assert classify_research_failure_message("model_pi_guard:sk-management") == "MODEL_PI_GUARD_REFUSAL"
    assert classify_research_failure_message("Skipped: in symbol_profiles but 1-char — ambiguous") == "INVALID_SYMBOL"
    assert classify_research_failure_message("LLM error: COST_CONFIGURATION_INVALID: global daily USD cap required") == "LLM_GLOBAL_DAILY_USD_CAP_MISSING"


def test_controlled_research_refusals_do_not_fake_provider_degradation():
    inputs = _inputs()
    inputs["research_ops"]["global_cap_status"] = "CONFIGURED"
    inputs["research_ops"]["failure_classes_today"] = {
        "INVALID_SYMBOL": 5,
        "MODEL_PI_GUARD_REFUSAL": 2,
    }
    inputs["research_ops"]["queue"]["failed_today"] = 7
    inputs["research_ops"]["queue"]["stale_or_superseded"] = 0
    out = build_observability(**inputs, now="2026-09-30T12:00:00+00:00")
    research = next(s for s in out["scorecards"] if s["id"] == "hermes_/_research")
    assert research["status"] == "WORKING"
    assert research["metrics"]["failed"] == 7
    assert research["metrics"]["operational_failures"] == 0
