"""Unit tests for Hermes Scope Governor v2 — outcome-aware edge scoring."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib.hermes_scope_governor.models import TIER_HEAT, heat_of
from lib.hermes_scope_governor.scoring import compute_edge_score, outcome_gate
from lib.hermes_scope_governor.models import SymbolSignals
from lib.hermes_scope_governor.universe import estimate_daily_computations


class TestHeatMapping(unittest.TestCase):
    def test_hot_warm_cold(self):
        self.assertEqual(heat_of("S0"), "hot")
        self.assertEqual(heat_of("S1"), "hot")
        self.assertEqual(heat_of("S2"), "warm")
        self.assertEqual(heat_of("S3"), "cold")
        self.assertEqual(TIER_HEAT["S1"], "hot")


class TestOutcomeGate(unittest.TestCase):
    def test_neutral_without_samples(self):
        sig = SymbolSignals(symbol="TEST")
        self.assertEqual(outcome_gate(sig, {"outcome_gates": {"min_graded_samples": 3}}), "neutral")

    def test_demote_pressure_on_miss_streak(self):
        sig = SymbolSignals(symbol="BAD", outcome_hits=0, outcome_misses=3, outcome_neutral=0)
        gate = outcome_gate(sig, {"outcome_gates": {"min_graded_samples": 3, "demote_miss_rate": 0.6, "pause_miss_rate": 0.75}})
        self.assertEqual(gate, "demote_pressure")

    def test_pause_on_severe_miss_streak(self):
        sig = SymbolSignals(symbol="BAD", outcome_hits=0, outcome_misses=4, outcome_neutral=0)
        gate = outcome_gate(sig, {"outcome_gates": {"min_graded_samples": 3, "pause_miss_rate": 0.75}})
        self.assertEqual(gate, "pause_eligible")

    def test_promote_eligible_on_hits(self):
        sig = SymbolSignals(symbol="GOOD", outcome_hits=3, outcome_misses=1, outcome_neutral=0, avg_realized_r=0.5)
        gate = outcome_gate(sig, {"outcome_gates": {"min_graded_samples": 3, "promote_hit_rate": 0.5}})
        self.assertEqual(gate, "promote_eligible")


class TestEdgeScoring(unittest.TestCase):
    def _cfg(self):
        return {
            "scoring": {
                "weights": {
                    "portfolio_relevance": 25,
                    "outcome_yield": 30,
                    "social_conviction": 15,
                    "technical_edge": 15,
                    "event_boost": 10,
                    "liquidity": 5,
                },
                "outcome_gates": {"demote_score_penalty": 20, "promote_score_boost": 8},
                "liquidity_filters": {"min_avg_volume": 200000, "max_atr_pct": 12},
            }
        }

    def test_holding_scores_higher_than_cold_unknown(self):
        holding = SymbolSignals(symbol="V", is_holding=True, hermes_composite=75)
        cold = SymbolSignals(symbol="ZZZ", hermes_composite=75)
        h = compute_edge_score(holding, self._cfg())
        c = compute_edge_score(cold, self._cfg())
        self.assertGreater(h.edge_score, c.edge_score)

    def test_outcome_yield_outranks_throughput(self):
        high_throughput = SymbolSignals(symbol="A", hermes_composite=85, outcome_hits=0, outcome_misses=4)
        proven_edge = SymbolSignals(symbol="B", hermes_composite=60, outcome_hits=4, outcome_misses=1, avg_realized_r=0.8)
        a = compute_edge_score(high_throughput, self._cfg())
        b = compute_edge_score(proven_edge, self._cfg())
        self.assertGreater(b.edge_score, a.edge_score)

    def test_event_boost_adds_points(self):
        base = SymbolSignals(symbol="X", hermes_composite=70)
        event = SymbolSignals(symbol="X", hermes_composite=70, has_fresh_catalyst=True)
        self.assertGreater(compute_edge_score(event, self._cfg()).edge_score,
                           compute_edge_score(base, self._cfg()).edge_score)


class TestResourceEstimate(unittest.TestCase):
    def test_tier_budget_math(self):
        est = estimate_daily_computations({"S0": 80, "S1": 200, "S2": 300, "S3": 3000})
        self.assertLess(est, 20_000)
        self.assertGreater(est, 5_000)


class TestConfigAndDocs(unittest.TestCase):
    def test_yaml_has_scoring_section(self):
        txt = (ROOT / "config" / "hermes_scope_governor.yaml").read_text()
        self.assertIn("outcome_yield:", txt)
        self.assertIn("outcome_gates:", txt)

    def test_docs_present(self):
        p = ROOT / "docs" / "hermes" / "HERMES_SCOPE_GOVERNOR.md"
        self.assertTrue(p.exists())
        self.assertIn("outcome yield outranks", p.read_text().lower())

    def test_api_route_registered(self):
        api = (ROOT / "scripts" / "api_v2.py").read_text()
        self.assertIn('"/api/v2/hermes/scope-governor"', api)
        self.assertIn("_hermes_scope_governor", api)


class TestGovernorHealth(unittest.TestCase):
    def test_stale_thresholds(self):
        from lib.hermes_scope_governor.health import (
            GOVERNOR_STALE_WARN_MIN,
            FEEDER_STALE_WARN_MIN,
        )
        self.assertGreater(GOVERNOR_STALE_WARN_MIN, 30)
        self.assertLess(FEEDER_STALE_WARN_MIN, 10)

    def test_health_module_imports(self):
        from lib.hermes_scope_governor.health import check_scope_governor_health
        findings = check_scope_governor_health(conn=None)
        self.assertIsInstance(findings, list)


if __name__ == "__main__":
    unittest.main()