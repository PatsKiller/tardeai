#!/usr/bin/env python3
"""Unit tests for GOV-1 scheduled governance."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestGOV1Governance(unittest.TestCase):

    def test_01_facts_wrapper_exists(self):
        self.assertTrue((PROJECT_ROOT / "scripts/run_scheduled_system_facts.sh").exists())

    def test_02_a1a_wrapper_exists(self):
        self.assertTrue((PROJECT_ROOT / "scripts/run_scheduled_a1a_check.sh").exists())

    def test_03_rollback_exists(self):
        self.assertTrue((PROJECT_ROOT / "scripts/rollback_gov1_governance_cron.sh").exists())

    def test_04_wrappers_check_alpaca(self):
        for f in ["run_scheduled_system_facts.sh", "run_scheduled_a1a_check.sh"]:
            script = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertIn("ALPACA_MODE", script)
            self.assertIn("paper", script)

    def test_05_wrappers_check_llm_disable(self):
        for f in ["run_scheduled_system_facts.sh", "run_scheduled_a1a_check.sh"]:
            script = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertIn("LLM_DISABLE_LIVE_EXECUTION", script)

    def test_06_wrappers_use_flock(self):
        for f in ["run_scheduled_system_facts.sh", "run_scheduled_a1a_check.sh"]:
            script = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertIn("flock", script)

    def test_07_wrappers_no_source_env(self):
        for f in ["run_scheduled_system_facts.sh", "run_scheduled_a1a_check.sh"]:
            script = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("source .env", script)
            self.assertNotIn("source $PROJ/.env", script)

    def test_08_a1a_checker_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/check_a1a_compliance.py"), doraise=True)

    def test_09_governance_report_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_governance_status.py"), doraise=True)

    def test_10_no_secrets_in_a1a(self):
        script = (PROJECT_ROOT / "scripts/check_a1a_compliance.py").read_text()
        self.assertNotIn("print(env", script)
        self.assertNotIn("API_KEY=", script)

    def test_11_rollback_targets_gov1_only(self):
        script = (PROJECT_ROOT / "scripts/rollback_gov1_governance_cron.sh").read_text()
        self.assertIn("GOV-1", script)
        self.assertNotIn("stale_proposal_sweeper", script)
        self.assertNotIn("sync-docs-to-drive", script)

    def test_12_phase6_regression(self):
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from paper_trade_logger import validate_paper_proposal_live_market
        from datetime import datetime, timezone
        r = validate_paper_proposal_live_market("TEST", 100.0, 95.0, 110.0, 50,
            {"last_price": 100.5, "spread_pct": 0.1, "quote_timestamp": datetime.now(timezone.utc)})
        self.assertTrue(r["ok"])


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestGOV1Governance))
    sys.exit(0 if result.wasSuccessful() else 1)
