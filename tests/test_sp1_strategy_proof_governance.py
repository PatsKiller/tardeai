#!/usr/bin/env python3
"""Unit tests for SP-1 strategy proof governance."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestSP1StrategyProof(unittest.TestCase):

    def test_01_policy_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/strategy_proof_policy.py"), doraise=True)

    def test_02_funnel_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_strategy_evidence_funnel.py"), doraise=True)

    def test_03_a5_readiness_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_a5_strategy_readiness.py"), doraise=True)

    def test_04_a5_incomplete_blocks(self):
        from strategy_proof_policy import classify_strategy_proof_status
        r = classify_strategy_proof_status({"proposal_count": 50, "closed_count": 30, "lifecycle_linkage_rate": 0.95}, a5_complete=False)
        self.assertEqual(r["proof_status"], "blocked_a5_incomplete")
        self.assertFalse(r["decision_allowed"])

    def test_05_closed_lt5_blocks(self):
        from strategy_proof_policy import classify_strategy_proof_status
        r = classify_strategy_proof_status({"proposal_count": 20, "closed_count": 3, "lifecycle_linkage_rate": 0.5}, a5_complete=True)
        self.assertIn(r["proof_status"], ("insufficient", "observing"))

    def test_06_closed_lt20_insufficient(self):
        from strategy_proof_policy import classify_strategy_proof_status
        r = classify_strategy_proof_status({"proposal_count": 30, "closed_count": 10, "lifecycle_linkage_rate": 0.9}, a5_complete=True)
        self.assertEqual(r["proof_status"], "preliminary")
        self.assertEqual(r["sample_quality"], "preliminary")

    def test_07_closed_20_29_review_only(self):
        from strategy_proof_policy import classify_strategy_proof_status
        r = classify_strategy_proof_status({"proposal_count": 40, "closed_count": 25, "lifecycle_linkage_rate": 0.9}, a5_complete=True)
        self.assertEqual(r["proof_status"], "review_ready")
        self.assertFalse(r["decision_allowed"])

    def test_08_closed_30_decision_ready(self):
        from strategy_proof_policy import classify_strategy_proof_status
        r = classify_strategy_proof_status({"proposal_count": 50, "closed_count": 35, "lifecycle_linkage_rate": 0.95}, a5_complete=True)
        self.assertEqual(r["proof_status"], "decision_ready")
        self.assertFalse(r["decision_allowed"])  # Still human_review_only

    def test_09_always_human_review_only(self):
        from strategy_proof_policy import classify_strategy_proof_status
        for closed in [0, 5, 20, 30, 50]:
            r = classify_strategy_proof_status({"proposal_count": 60, "closed_count": closed, "lifecycle_linkage_rate": 0.95}, a5_complete=True)
            self.assertEqual(r["recommendation_status"], "human_review_only")

    def test_10_decision_never_allowed(self):
        from strategy_proof_policy import is_decision_allowed
        self.assertFalse(is_decision_allowed({"closed_count": 100}, True))

    def test_11_no_mutation_in_funnel(self):
        script = (PROJECT_ROOT / "scripts/report_strategy_evidence_funnel.py").read_text()
        self.assertNotIn("INSERT INTO", script)
        self.assertNotIn("UPDATE ", script)
        self.assertNotIn("DELETE FROM", script)
        self.assertNotIn("submit_order", script)

    def test_12_no_mutation_in_a5(self):
        script = (PROJECT_ROOT / "scripts/report_a5_strategy_readiness.py").read_text()
        self.assertNotIn("INSERT INTO", script)
        self.assertNotIn("UPDATE ", script)
        self.assertNotIn("submit_order", script)

    def test_13_phase6_regression(self):
        from paper_trade_logger import validate_paper_proposal_live_market
        from datetime import datetime, timezone
        r = validate_paper_proposal_live_market("TEST", 100.0, 95.0, 110.0, 50,
            {"last_price": 100.5, "spread_pct": 0.1, "quote_timestamp": datetime.now(timezone.utc)})
        self.assertTrue(r["ok"])


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestSP1StrategyProof))
    sys.exit(0 if result.wasSuccessful() else 1)
