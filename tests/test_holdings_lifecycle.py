"""Unit tests for Hermes holdings lifecycle."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib.hermes_holdings_lifecycle.holdings_lifecycle import (  # noqa: E402
    apply_confidence_discount,
    apply_manual_override,
    compute_health_score,
    resolve_stage,
    _component_scores,
    load_config,
)
from lib.hermes_thresholds.workflow import _enrich_decided_proposals  # noqa: E402


class TestHoldingsHealth(unittest.TestCase):
    def test_compute_health_weighted(self):
        cfg = load_config()
        components = {
            "stop_quality": 80.0,
            "outcome_consistency": 70.0,
            "realized_r": 60.0,
            "research_actionability": 75.0,
            "position_risk": 65.0,
        }
        score = compute_health_score(components, cfg, graded_n=5)
        self.assertGreaterEqual(score, 65.0)
        self.assertLessEqual(score, 100.0)

    def test_confidence_discount_sparse(self):
        cfg = load_config()
        final, tier = apply_confidence_discount(80.0, 1, cfg)
        self.assertEqual(tier, "sparse_data")
        self.assertLess(final, 80.0)

    def test_resolve_trim_on_low_health(self):
        cfg = load_config()
        stage, _ = resolve_stage(42.0, "neutral", None, None, False, cfg)
        self.assertEqual(stage, "trim_candidate")

    def test_resolve_healthy(self):
        cfg = load_config()
        stage, _ = resolve_stage(78.0, "promote_eligible", None, None, False, cfg)
        self.assertEqual(stage, "healthy")

    def test_components_demote_pressure(self):
        cfg = load_config()
        pos = {"gain_pct": -8.0, "pct_from_high": -20}
        bus_sym = {"gate": "demote_pressure", "n": 5, "misses": 3, "hits": 1}
        comps = _component_scores("TEST", pos, bus_sym, {"action": "demote_pressure"}, None, {}, cfg)
        score = compute_health_score(comps, cfg, graded_n=5)
        self.assertLess(score, 70.0)


class TestHoldingsOverride(unittest.TestCase):
    def test_manual_override(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_holdings_lifecycle import holdings_lifecycle as mod
            old_state = mod.STATE_PATH
            old_audit = mod.AUDIT_PATH
            try:
                mod.STATE_PATH = Path(td) / "state.json"
                mod.AUDIT_PATH = Path(td) / "audit.jsonl"
                mod.save_state({
                    "version": "holdings-lifecycle-v1",
                    "holdings": {"ABC": {"symbol": "ABC", "health_score": 80, "lifecycle_stage": "healthy"}},
                    "overrides": {},
                })
                result = apply_manual_override("ABC", "watch", "operator review", by="test")
                self.assertTrue(result["ok"])
                state = mod.load_holdings_lifecycle_state()
                self.assertEqual(state["overrides"]["ABC"]["stage"], "watch")
            finally:
                mod.STATE_PATH = old_state
                mod.AUDIT_PATH = old_audit


class TestProposalHistoryEnrichment(unittest.TestCase):
    def test_enrich_links_evaluation(self):
        decided = [{
            "id": "tp_abc123",
            "threshold_id": "efficiency.tighten_threshold",
            "status": "approved",
            "decided_at": "2026-07-01T12:00:00+00:00",
            "current_value": 0.5,
            "proposed_value": 0.47,
        }]
        history = [{
            "proposal_id": "tp_abc123",
            "at": "2026-07-01T12:00:00+00:00",
            "to": 0.47,
            "threshold_id": "efficiency.tighten_threshold",
        }]
        evaluations = [{
            "threshold_id": "efficiency.tighten_threshold",
            "approved_at": "2026-07-01",
            "verdict": "helped",
            "recommendation": "keep",
            "impact_score": 0.22,
        }]
        out = _enrich_decided_proposals(decided, history, evaluations)
        self.assertEqual(out[0]["applied_value"], 0.47)
        self.assertEqual(out[0]["evaluation_outcome"]["verdict"], "helped")


if __name__ == "__main__":
    unittest.main()