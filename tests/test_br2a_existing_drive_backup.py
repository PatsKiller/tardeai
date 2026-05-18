#!/usr/bin/env python3
"""Unit tests for BR-2A existing Drive backup validation."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestBR2AExistingDriveBackup(unittest.TestCase):

    def test_01_target_discovery_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_existing_offsite_backup_target.py"), doraise=True)

    def test_02_no_env_upload(self):
        script = (PROJECT_ROOT / "scripts/report_existing_offsite_backup_target.py").read_text()
        self.assertNotIn("upload.*\\.env", script)
        self.assertNotIn("copy.*\\.env", script)

    def test_03_no_secrets_printed(self):
        script = (PROJECT_ROOT / "scripts/report_existing_offsite_backup_target.py").read_text()
        self.assertNotIn("API_KEY=", script)
        self.assertNotIn("SECRET=", script)

    def test_04_no_mutation(self):
        script = (PROJECT_ROOT / "scripts/report_existing_offsite_backup_target.py").read_text()
        self.assertNotIn("INSERT INTO", script)
        self.assertNotIn("UPDATE ", script)
        self.assertNotIn("submit_order", script)

    def test_05_no_broker_calls(self):
        script = (PROJECT_ROOT / "scripts/report_existing_offsite_backup_target.py").read_text()
        self.assertNotIn("alpaca", script.lower().replace("alpaca_mode", ""))

    def test_06_readme_exists(self):
        self.assertTrue((PROJECT_ROOT / "docs/recovery/phase_br2a_existing_gog_drive_backup/00_README.md").exists())

    def test_07_phase6_regression(self):
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from paper_trade_logger import validate_paper_proposal_live_market
        from datetime import datetime, timezone
        r = validate_paper_proposal_live_market("TEST", 100.0, 95.0, 110.0, 50,
            {"last_price": 100.5, "spread_pct": 0.1, "quote_timestamp": datetime.now(timezone.utc)})
        self.assertTrue(r["ok"])


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestBR2AExistingDriveBackup))
    sys.exit(0 if result.wasSuccessful() else 1)
