#!/usr/bin/env python3
"""Tests for PP-UX-2 Proposal Trust Audit."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestQuoteTrust(unittest.TestCase):
    """Verify quote trust classification."""

    def test_01_finviz_display_only(self):
        from proposal_quote_trust import classify_quote_trust
        r = classify_quote_trust({"execution_readiness": {"quote_provider": "finviz"}})
        self.assertEqual(r["quote_trust_status"], "DISPLAY_ONLY")
        self.assertFalse(r["is_execution_eligible"])
        self.assertIn("display-only", r["display_only_reason"])

    def test_02_yfinance_display_only(self):
        from proposal_quote_trust import classify_quote_trust
        r = classify_quote_trust({"execution_readiness": {"quote_provider": "yfinance"}})
        self.assertEqual(r["quote_trust_status"], "DISPLAY_ONLY")
        self.assertFalse(r["is_execution_eligible"])

    def test_03_alpaca_with_bid_ask_eligible(self):
        from proposal_quote_trust import classify_quote_trust
        r = classify_quote_trust({"execution_readiness": {
            "quote_provider": "alpaca", "bid": 1.50, "ask": 1.51,
            "quote_age_seconds": 30, "quote_is_delayed": False,
            "quote_execution_eligible": True
        }})
        self.assertTrue(r["is_execution_eligible"])
        self.assertEqual(r["quote_trust_status"], "EXECUTION_ELIGIBLE")

    def test_04_stale_quote(self):
        from proposal_quote_trust import classify_quote_trust
        r = classify_quote_trust({
            "execution_readiness": {
                "quote_provider": "alpaca", "bid": 1.50, "ask": 1.51,
                "quote_age_seconds": 5000, "quote_is_delayed": False,
                "quote_execution_eligible": True
            },
            "strategy_timeframe_class": "MEDIUM_SWING"
        })
        self.assertEqual(r["quote_trust_status"], "STALE")

    def test_05_missing_bid_ask(self):
        from proposal_quote_trust import classify_quote_trust
        r = classify_quote_trust({"execution_readiness": {
            "quote_provider": "alpaca", "quote_age_seconds": 30,
            "quote_is_delayed": False
        }})
        self.assertFalse(r["is_execution_eligible"])

    def test_06_no_execution_readiness(self):
        from proposal_quote_trust import classify_quote_trust
        r = classify_quote_trust({})
        self.assertEqual(r["quote_trust_status"], "NOT_CHECKED")

    def test_07_no_nan_in_result(self):
        from proposal_quote_trust import classify_quote_trust
        import math
        r = classify_quote_trust({"execution_readiness": {"quote_provider": "alpaca"}})
        for k, v in r.items():
            if isinstance(v, float):
                self.assertFalse(math.isnan(v), f"{k} is NaN")


class TestAuditScripts(unittest.TestCase):
    """Verify audit scripts compile and are read-only."""

    def test_08_strategy_fit_audit_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_proposal_strategy_fit_audit.py"), doraise=True)

    def test_09_technical_backtest_audit_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_proposal_technical_backtest_audit.py"), doraise=True)

    def test_10_quote_trust_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/proposal_quote_trust.py"), doraise=True)

    def test_11_api_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)

    def test_12_strategy_fit_no_db_writes(self):
        src = (PROJECT_ROOT / "scripts/report_proposal_strategy_fit_audit.py").read_text()
        self.assertNotIn("INSERT INTO", src)
        self.assertNotIn("UPDATE ", src)
        self.assertNotIn("DELETE FROM", src)

    def test_13_technical_audit_no_trade_creation(self):
        src = (PROJECT_ROOT / "scripts/report_proposal_technical_backtest_audit.py").read_text()
        self.assertNotIn("INSERT INTO", src)
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)


class TestFrontendTrustAudit(unittest.TestCase):
    """Verify frontend contains Trust Audit elements."""

    def test_14_frontend_build_exists(self):
        dist = PROJECT_ROOT / "apps/command-center-v2/dist/assets"
        pp_files = list(dist.glob("PaperProposals-*.js"))
        self.assertTrue(len(pp_files) > 0)

    def test_15_frontend_has_trust_audit(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertIn("trust_audit", src)
        self.assertIn("Trust Audit", src)

    def test_16_frontend_has_quote_trust(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertIn("quote_trust", src)
        self.assertIn("Exec Eligible", src)
        self.assertIn("display_only_reason", src)

    def test_17_frontend_has_strategy_fit(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertIn("strategy_fit", src)
        self.assertIn("mismatch_warning", src)
        self.assertIn("strategy_evaluations", src)

    def test_18_frontend_has_technical_backtest(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertIn("technical_backtest", src)
        self.assertIn("fib_status", src)
        self.assertIn("orb_status", src)
        self.assertIn("backtest_quality", src)


class TestSafety(unittest.TestCase):
    """Verify safety constraints."""

    def test_19_no_order_submission(self):
        for f in ["proposal_quote_trust.py", "report_proposal_strategy_fit_audit.py",
                   "report_proposal_technical_backtest_audit.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_20_no_strategy_activation(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertNotIn("activate_strategy", src)
        self.assertNotIn("enable_live", src)

    def test_21_existing_ppux1_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "tests/test_pp_ux1_paper_proposals_decision_packet.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"PP-UX-1 tests failed:\n{r.stderr}")


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
