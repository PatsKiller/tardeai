"""Hermes maturity hardening — scorecard, evidence gates, counterfactuals, do-no-harm, governance."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib.hermes_thresholds.evidence_gates import (  # noqa: E402
    check_hermes_action_allowed,
    evaluate_evidence_gates,
    enrich_proposal_evidence_gates,
)
from lib.hermes_thresholds.counterfactual_evidence import build_counterfactual_evidence  # noqa: E402
from lib.hermes_thresholds.do_no_harm import build_do_no_harm_report  # noqa: E402
from lib.hermes_thresholds.governance import (  # noqa: E402
    HERMES_ADVISORY_ONLY,
    assert_hermes_cannot_modify_execution,
    hermes_governance_status,
)
from lib.hermes_thresholds.store import load_threshold_config  # noqa: E402
from lib.hermes_traceability.symbol_journey import build_symbol_journey  # noqa: E402


def _synthetic_series(n: int = 22) -> list[dict]:
    series = []
    for i in range(n):
        eff = 0.55 if i % 4 else 0.44
        hr = 0.30 if eff < 0.50 else 0.42
        series.append({
            "day": f"2026-06-{i + 1:02d}",
            "resource_efficiency_score": eff,
            "hit_rate_promotions": hr,
            "maturity_composite_score": 58 if hr < 0.35 else 72,
            "active_alert_count": 1 if eff < 0.5 else 0,
            "symbols_in_bus": 400 + i,
        })
    return series


class TestEvidenceGates(unittest.TestCase):
    def test_insufficient_sample_blocks_learned(self):
        cfg = load_threshold_config()
        gates = evaluate_evidence_gates(
            sample_size=5,
            lookback_days=30,
            regime_count=1,
            confidence="low",
            cfg=cfg,
            threshold_id="efficiency.tighten_threshold",
        )
        self.assertFalse(gates["can_be_called_learned"])
        self.assertIn(gates["allowed_action"], ("observe_only", "propose_only"))
        self.assertIsNotNone(gates["blocked_reason"])

    def test_sufficient_sample_allows_proposal_with_operator_approval(self):
        cfg = load_threshold_config()
        gates = evaluate_evidence_gates(
            sample_size=20,
            lookback_days=30,
            regime_count=2,
            confidence="high",
            cfg=cfg,
            review_mode=True,
        )
        self.assertTrue(gates["can_be_called_learned"])
        self.assertEqual(gates["allowed_action"], "operator_approval_required")

    def test_enrich_proposal_attaches_gates(self):
        cfg = load_threshold_config()
        proposal = {
            "threshold_id": "efficiency.tighten_threshold",
            "direction": "tighten",
            "evidence": {
                "confidence": "high",
                "sample_days": 22,
                "regime_breakdown": {"total_days": 22, "high_vol_days": 3, "regime_stable": True},
            },
        }
        out = enrich_proposal_evidence_gates(proposal, cfg)
        self.assertIn("evidence_gates", out)
        self.assertIn("allowed_action", out)
        self.assertTrue(out.get("can_be_called_learned"))


class TestCounterfactualEvidence(unittest.TestCase):
    def test_counterfactual_evidence_required_fields(self):
        series = _synthetic_series()
        proposed = lambda s: float(s["resource_efficiency_score"]) < 0.48
        current = lambda s: float(s["resource_efficiency_score"]) < 0.50
        cf = build_counterfactual_evidence(
            series,
            proposed_trigger_fn=proposed,
            current_trigger_fn=current,
            window_days=14,
        )
        self.assertIn("top_examples_helped", cf)
        self.assertIn("top_examples_hurt", cf)
        self.assertIn("estimated_false_positive_impact", cf)
        self.assertIn("estimated_false_negative_impact", cf)
        self.assertIn("resource_cost_impact", cf)
        self.assertIn("expected_outcome_yield_impact", cf)


class TestDoNoHarm(unittest.TestCase):
    def test_recommends_revert_when_hit_rate_degrades(self):
        before = [{"hit_rate_promotions": 0.45, "resource_efficiency_score": 0.6, "symbols_in_bus": 400}]
        after = [{"hit_rate_promotions": 0.30, "resource_efficiency_score": 0.5, "symbols_in_bus": 500}]
        report = build_do_no_harm_report(before, after)
        self.assertEqual(report["recommendation"], "revert")
        self.assertIn("hit_rate_declined", report["degraded_signals"])

    def test_recommends_keep_when_improved(self):
        before = [{"hit_rate_promotions": 0.30, "resource_efficiency_score": 0.5}]
        after = [{"hit_rate_promotions": 0.42, "resource_efficiency_score": 0.58}]
        report = build_do_no_harm_report(before, after)
        self.assertEqual(report["recommendation"], "keep")


class TestSymbolJourney(unittest.TestCase):
    def test_symbol_journey_includes_required_fields(self):
        r = build_symbol_journey("TEST")
        self.assertTrue(r.get("ok") or r.get("reason"))
        if r.get("ok"):
            self.assertTrue(r.get("advisory_only"))
            self.assertIn("summary", r)
            self.assertIn("outcome_bus", r)
            self.assertIn("research_generated", r)
            self.assertIn("threshold_effects", r)
            self.assertIn("latest_hermes_recommendation", r)
            self.assertIn("timeline", r)


class TestAdvisoryOnlyGovernance(unittest.TestCase):
    def test_hermes_advisory_only_flag(self):
        self.assertTrue(HERMES_ADVISORY_ONLY)
        status = hermes_governance_status()
        self.assertTrue(status["advisory_only"])
        self.assertFalse(status["broker_writes_allowed"])
        self.assertFalse(status["oco_modification_allowed"])

    def test_cannot_modify_execution_gates(self):
        for surface in ("live_broker_writes", "oco_readiness", "2fa_approval", "schwab_transport"):
            r = assert_hermes_cannot_modify_execution(surface)
            self.assertFalse(r["allowed"])

    def test_broker_write_action_blocked(self):
        r = check_hermes_action_allowed("broker_write")
        self.assertFalse(r["allowed"])

    def test_scope_budget_requires_operator(self):
        r = check_hermes_action_allowed("scope_budget_change")
        self.assertTrue(r["allowed"])
        self.assertTrue(r.get("requires_operator_approval"))


class TestLearningScorecard(unittest.TestCase):
    def test_scorecard_builds_and_persists(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_outcome_bus import scorecard as sc_mod
            old_path = sc_mod.SCORECARD_PATH
            try:
                sc_mod.SCORECARD_PATH = Path(td) / "hermes_learning_scorecard.json"
                out = sc_mod.build_learning_scorecard(persist=True)
                self.assertEqual(out["version"], "hermes-learning-scorecard-v1")
                self.assertTrue(out["advisory_only"])
                self.assertTrue(sc_mod.SCORECARD_PATH.exists())
                loaded = json.loads(sc_mod.SCORECARD_PATH.read_text())
                self.assertIn("signals_reviewed", loaded)
                self.assertIn("maturity_score_by_subsystem", loaded)
            finally:
                sc_mod.SCORECARD_PATH = old_path


if __name__ == "__main__":
    unittest.main()