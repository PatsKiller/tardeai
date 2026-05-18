#!/usr/bin/env python3
"""Unit tests for Phase 9B maturity control board."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestPhase9BMaturityBoard(unittest.TestCase):

    def test_01_policy_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/maturity_control_policy.py"), doraise=True)

    def test_02_board_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_maturity_control_board.py"), doraise=True)

    def test_03_gates_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_phase_readiness_gates.py"), doraise=True)

    def test_04_live_trading_blocked(self):
        from maturity_control_policy import classify_live_readiness
        r = classify_live_readiness({"alpaca_mode": "paper", "a5_complete": True,
            "backup_readiness": 5, "closed_trades": 50, "win_rate": 0.4})
        self.assertEqual(r["status"], "blocked")
        self.assertFalse(r["decision_allowed"])

    def test_05_phase8d_blocked_without_a5(self):
        from maturity_control_policy import classify_strategy_decision_readiness
        r = classify_strategy_decision_readiness({"a5_complete": False, "strategies_decision_ready": 0, "closed_trades": 5})
        self.assertEqual(r["status"], "blocked")
        self.assertIn("A-5", r["blockers"][0])

    def test_06_agent_learning_blocked_weak(self):
        from maturity_control_policy import classify_agent_learning_readiness
        r = classify_agent_learning_readiness({"evidence_quality": "weak"})
        self.assertEqual(r["status"], "blocked")
        self.assertFalse(r["auto_learning_allowed"])

    def test_07_backup_blocked_no_offsite(self):
        from maturity_control_policy import classify_backup_readiness
        r = classify_backup_readiness({"backup_score": 5, "offsite_configured": False})
        self.assertEqual(r["status"], "blocked")

    def test_08_no_mutation_in_board(self):
        script = (PROJECT_ROOT / "scripts/report_maturity_control_board.py").read_text()
        self.assertNotIn("INSERT INTO", script)
        self.assertNotIn("UPDATE ", script)
        self.assertNotIn("submit_order", script)

    def test_09_no_mutation_in_gates(self):
        script = (PROJECT_ROOT / "scripts/report_phase_readiness_gates.py").read_text()
        self.assertNotIn("INSERT INTO", script)
        self.assertNotIn("submit_order", script)

    def test_10_always_human_review(self):
        from maturity_control_policy import classify_strategy_decision_readiness
        r = classify_strategy_decision_readiness({"a5_complete": True, "strategies_decision_ready": 5, "closed_trades": 50})
        self.assertEqual(r["recommendation_status"], "human_review_only")

    def test_11_phase6_regression(self):
        from paper_trade_logger import validate_paper_proposal_live_market
        from datetime import datetime, timezone
        r = validate_paper_proposal_live_market("TEST", 100.0, 95.0, 110.0, 50,
            {"last_price": 100.5, "spread_pct": 0.1, "quote_timestamp": datetime.now(timezone.utc)})
        self.assertTrue(r["ok"])


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestPhase9BMaturityBoard))
    sys.exit(0 if result.wasSuccessful() else 1)
