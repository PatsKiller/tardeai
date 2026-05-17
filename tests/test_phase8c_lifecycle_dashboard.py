#!/usr/bin/env python3
"""Unit tests for Phase 8C lifecycle dashboard reporting."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestPhase8CDashboard(unittest.TestCase):

    def test_01_report_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_phase8_dashboard_readiness.py"), doraise=True)

    def test_02_api_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)

    def test_03_no_mutation_in_report(self):
        script = (PROJECT_ROOT / "scripts/report_phase8_dashboard_readiness.py").read_text()
        self.assertNotIn("INSERT INTO", script)
        self.assertNotIn("UPDATE ", script)
        self.assertNotIn("DELETE FROM", script)
        self.assertNotIn("submit_order", script)
        self.assertNotIn("submit_paper", script)

    def test_04_api_endpoints_read_only(self):
        """Phase 8C endpoints in api_v2.py use SELECT only."""
        script = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        # Find the Phase 8C section
        start = script.find("Phase 8C Read-Only Lifecycle Endpoints")
        end = script.find("paper-proposals/reject", start)
        section = script[start:end] if start > 0 and end > start else ""
        self.assertGreater(len(section), 100, "Phase 8C section not found")
        self.assertNotIn("INSERT INTO", section)
        self.assertNotIn("UPDATE ", section)
        self.assertNotIn("DELETE FROM", section)

    def test_05_scorecards_human_review_only(self):
        """API returns all_human_review_only flag."""
        # Structural test — verify the code includes the check
        script = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("all_human_review_only", script)

    def test_06_phase7_regression(self):
        from simulate_paper_proposal_approval import simulate_proposal
        self.assertTrue(callable(simulate_proposal))

    def test_07_phase6_regression(self):
        from paper_trade_logger import validate_paper_proposal_live_market
        from datetime import datetime, timezone
        r = validate_paper_proposal_live_market("TEST", 100.0, 95.0, 110.0, 50,
            {"last_price": 100.5, "spread_pct": 0.1, "quote_timestamp": datetime.now(timezone.utc)})
        self.assertTrue(r["ok"])


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestPhase8CDashboard))
    sys.exit(0 if result.wasSuccessful() else 1)
