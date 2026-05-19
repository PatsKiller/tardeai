#!/usr/bin/env python3
"""Tests for MISS-1 Missed Opportunity Audit."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestMissedOpportunityPolicy(unittest.TestCase):

    def test_01_policy_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/missed_opportunity_policy.py"), doraise=True)

    def test_02_dwsn_classifies_rebuild(self):
        from missed_opportunity_policy import classify_missed_opportunity
        r = classify_missed_opportunity(
            {"proposed_entry": 3.91, "proposed_stop": 3.71, "proposed_target1": 4.30, "proposed_rr": 1.95},
            {"quote_price": 4.46, "spread_pct": 14.8}
        )
        self.assertIn(r["status"], ("missed_price_moved", "rebuild_required"))

    def test_03_wide_spread_blocks(self):
        from missed_opportunity_policy import calculate_proposal_decay
        r = calculate_proposal_decay(
            {"proposed_entry": 10, "proposed_stop": 9, "proposed_target1": 12, "proposed_rr": 2.0},
            {"quote_price": 10.1, "spread_pct": 10.0}
        )
        self.assertFalse(r["actionable"])  # spread too wide

    def test_04_still_actionable(self):
        from missed_opportunity_policy import classify_missed_opportunity
        r = classify_missed_opportunity(
            {"proposed_entry": 10, "proposed_stop": 9, "proposed_target1": 13, "proposed_rr": 3.0},
            {"quote_price": 10.1, "spread_pct": 0.5}
        )
        self.assertEqual(r["status"], "still_actionable")

    def test_05_alert_sla_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_alert_sla_status.py"), doraise=True)

    def test_06_audit_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_missed_opportunity_audit.py"), doraise=True)

    def test_07_reports_read_only(self):
        for f in ["missed_opportunity_policy.py", "report_missed_opportunity_audit.py", "report_alert_sla_status.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)
            self.assertNotIn("activate_strategy", src)

    def test_08_human_review_only(self):
        from missed_opportunity_policy import classify_missed_opportunity
        r = classify_missed_opportunity({"proposed_entry": 10, "proposed_stop": 9, "proposed_target1": 12}, {})
        self.assertTrue(r["human_review_only"])

    def test_09_alert2_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
             "tests/test_alert2_telegram_callbacks.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"ALERT-2 tests failed:\n{r.stderr}")

    def test_10_q1_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
             "tests/test_q1_proactive_quote_refresh.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"Q-1 tests failed:\n{r.stderr}")


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
