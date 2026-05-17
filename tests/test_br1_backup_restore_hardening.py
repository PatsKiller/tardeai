#!/usr/bin/env python3
"""Unit tests for BR-1 backup restore hardening."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestBR1BackupRestore(unittest.TestCase):

    def test_01_readiness_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_backup_readiness.py"), doraise=True)

    def test_02_no_secrets_in_report(self):
        script = (PROJECT_ROOT / "scripts/report_backup_readiness.py").read_text()
        self.assertNotIn("print(env", script)
        self.assertNotIn("API_KEY=", script)
        self.assertNotIn("SECRET=", script)

    def test_03_no_mutation(self):
        script = (PROJECT_ROOT / "scripts/report_backup_readiness.py").read_text()
        self.assertNotIn("INSERT INTO", script)
        self.assertNotIn("UPDATE ", script)
        self.assertNotIn("DELETE FROM", script)
        self.assertNotIn("submit_order", script)

    def test_04_no_order_submission(self):
        script = (PROJECT_ROOT / "scripts/report_backup_readiness.py").read_text()
        self.assertNotIn("submit_paper", script)
        self.assertNotIn("approve_proposal", script)
        self.assertNotIn("create_trade", script)

    def test_05_rpo_rto_doc_exists(self):
        self.assertTrue((PROJECT_ROOT / "docs/recovery/phase_br1_offsite_backup_restore/br1_rpo_rto_policy.md").exists())

    def test_06_offsite_plan_exists(self):
        self.assertTrue((PROJECT_ROOT / "docs/recovery/phase_br1_offsite_backup_restore/br1_offsite_encrypted_backup_plan.md").exists())

    def test_07_restore_runbook_exists(self):
        self.assertTrue((PROJECT_ROOT / "docs/recovery/phase_br1_offsite_backup_restore/br1_db_restore_drill_runbook.md").exists())

    def test_08_phase6_regression(self):
        from paper_trade_logger import validate_paper_proposal_live_market
        from datetime import datetime, timezone
        r = validate_paper_proposal_live_market("TEST", 100.0, 95.0, 110.0, 50,
            {"last_price": 100.5, "spread_pct": 0.1, "quote_timestamp": datetime.now(timezone.utc)})
        self.assertTrue(r["ok"])


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestBR1BackupRestore))
    sys.exit(0 if result.wasSuccessful() else 1)
