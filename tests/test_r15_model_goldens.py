"""100 model-routing goldens: recommend, never auto-edit registries."""
from __future__ import annotations

import pytest

from scripts.lib.cio_model_learning import (
    RoutingPromotionForbidden,
    apply_routing_candidate,
    model_selection_explanation,
    objective_score,
    record_performance,
    routing_candidate,
    shadow_evaluate,
    snapshot_registries,
)
from tests.r15_goldens import model_goldens

pytestmark = pytest.mark.tier0
CASES = model_goldens()
ROOT = None


def _rows(policy: str, n: int, score_hint: float, valid: float = 1.0) -> list[dict]:
    out = []
    for i in range(n):
        schema_valid = i < int(n * valid)
        row = record_performance(
            task_class="extraction",
            process_id="p",
            requested_policy=policy,
            executed_policy=policy,
            model_id="deepseek-v4-flash" if "FAST" in policy else "deepseek-v4-pro",
            prompt_version="v1",
            latency=1000,
            cost=0.01 if "FAST" in policy else 0.08,
            schema_valid=schema_valid,
            citation_valid=schema_valid,
            critique_verdict="PASS" if schema_valid else "FAIL",
            self_assessment="ignore me",
        )
        out.append(row)
    if score_hint < 0.85:
        for row in out:
            row["schema_valid"] = False
            row["citation_valid"] = False
            row["critique_verdict"] = "FAIL"
            row["objective_score"] = objective_score(row)
    return out


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_model_routing_golden(case: dict, tmp_path) -> None:
    assert case.get("expect_auto") is False
    cohort = case["task_class"]
    if case.get("ignore_self"):
        row = record_performance(
            task_class=cohort, process_id="p", requested_policy="FAST",
            executed_policy="FAST", model_id="deepseek-v4-flash", prompt_version="v1",
            self_assessment=case.get("self_assessment"),
        )
        assert row["self_assessment_ignored"] is True
        return
    if case.get("explain"):
        expl = model_selection_explanation(
            executed_policy=case.get("policy") or "FAST",
            requested_policy="FAST",
            task_class=cohort,
            history={"n": 5, "mean_cost": 0.01, "mean_score": 0.9},
        )
        assert expl["gui_cannot_self_promote"] is True
        assert expl["why_pro_not_needed"]
        return
    if case.get("expect_registry_write") is False and "n_flash" not in case:
        before = snapshot_registries(tmp_path)
        cand = routing_candidate(task_class=cohort, current_policy="FAST", rows=[], candidate_policy="PRO", min_samples=30)
        with pytest.raises(RoutingPromotionForbidden):
            apply_routing_candidate(tmp_path, cand)
        assert before == snapshot_registries(tmp_path)
        return
    if case.get("shadow"):
        fixtures = _rows("FAST", 40, 0.9) + _rows("PRO", 40, 0.95)
        cand = routing_candidate(task_class=cohort, current_policy="FAST", rows=fixtures, candidate_policy="PRO")
        shadow = shadow_evaluate(candidate=cand, fixtures=fixtures)
        assert shadow["live_notification"] is False
        assert shadow["paid_calls"] == 0
        assert shadow["used_historical_fixtures"] is True
        assert shadow["registry_written"] is False
        return
    flash_n = int(case.get("n_flash") or 0)
    pro_n = int(case.get("n_pro") or 0)
    if not flash_n:
        return
    policy_b = case.get("pro_policy") or "PRO"
    rows = _rows("FAST", flash_n, float(case.get("flash_score") or 0.9), float(case.get("flash_valid") or 1.0))
    rows += _rows(policy_b, pro_n, float(case.get("pro_score") or 0.9), float(case.get("pro_valid") or 1.0))
    if case.get("expect_status") == "CANDIDATE_ROUTE":
        for row in rows:
            if row.get("executed_policy") == policy_b:
                row["operator_feedback"] = "ACCEPTED"
                row["outcome_refs"] = ["o1"]
                row["objective_score"] = objective_score(row)
    cand = routing_candidate(task_class=cohort, current_policy="FAST", rows=rows, candidate_policy=policy_b)
    assert cand["automatic_promotion"] is False
    assert cand["registry_written"] is False
    assert cand["status"] == case["expect_status"]
    with pytest.raises(RoutingPromotionForbidden):
        apply_routing_candidate(tmp_path, cand)
