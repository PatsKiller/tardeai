#!/usr/bin/env python3
"""Unit tests for Phase 9A maturity hardening reports."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestPhase9AMaturityHardening(unittest.TestCase):

    def test_01_strategy_governance_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_strategy_sample_size_governance.py"), doraise=True)

    def test_02_agent_evidence_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_agent_learning_evidence_gate.py"), doraise=True)

    def test_03_data_fragility_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_data_source_fragility.py"), doraise=True)

    def test_04_no_mutation_in_governance(self):
        script = (PROJECT_ROOT / "scripts/report_strategy_sample_size_governance.py").read_text()
        self.assertNotIn("INSERT INTO", script)
        self.assertNotIn("UPDATE ", script)
        self.assertNotIn("DELETE FROM", script)
        self.assertNotIn("submit_order", script)

    def test_05_no_mutation_in_evidence(self):
        script = (PROJECT_ROOT / "scripts/report_agent_learning_evidence_gate.py").read_text()
        self.assertNotIn("INSERT INTO", script)
        self.assertNotIn("UPDATE ", script)
        self.assertNotIn("submit_order", script)

    def test_06_no_secrets_in_fragility(self):
        script = (PROJECT_ROOT / "scripts/report_data_source_fragility.py").read_text()
        self.assertNotIn("print(env", script)
        # Verify secrets are not printed in output — DB_PASSWORD in get_conn() is expected
        self.assertIn("without revealing value", script)
        self.assertNotIn("print(key)", script)
        self.assertNotIn("print(secret)", script)

    def test_07_no_order_submission(self):
        for f in ["report_strategy_sample_size_governance.py",
                  "report_agent_learning_evidence_gate.py",
                  "report_data_source_fragility.py"]:
            script = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("submit_paper", script)
            self.assertNotIn("approve_proposal", script)

    def test_08_phase7_regression(self):
        from simulate_paper_proposal_approval import simulate_proposal
        self.assertTrue(callable(simulate_proposal))

    def test_09_phase6_regression(self):
        from paper_trade_logger import validate_paper_proposal_live_market
        from datetime import datetime, timezone
        r = validate_paper_proposal_live_market("TEST", 100.0, 95.0, 110.0, 50,
            {"last_price": 100.5, "spread_pct": 0.1, "quote_timestamp": datetime.now(timezone.utc)})
        self.assertTrue(r["ok"])

    def test_10_auto_learning_blocked(self):
        """Agent evidence gate must block auto-learning."""
        script = (PROJECT_ROOT / "scripts/report_agent_learning_evidence_gate.py").read_text()
        self.assertIn("auto_learning_blocked", script)
        self.assertIn("True", script.split("auto_learning_blocked")[1][:20])


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestPhase9AMaturityHardening))
    sys.exit(0 if result.wasSuccessful() else 1)
