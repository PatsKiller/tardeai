#!/usr/bin/env python3
"""Tests for Q-1 Proactive Quote Refresh."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompilation(unittest.TestCase):
    def test_01_trust_policy_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/quote_provider_trust_policy.py"), doraise=True)

    def test_02_target_selector_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/select_quote_refresh_targets.py"), doraise=True)

    def test_03_refresh_script_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/run_proactive_quote_refresh.py"), doraise=True)

    def test_04_wrapper_exists(self):
        p = PROJECT_ROOT / "scripts/run_scheduled_quote_refresh.sh"
        self.assertTrue(p.exists())
        import os
        self.assertTrue(os.access(str(p), os.X_OK))

    def test_05_rollback_exists(self):
        p = PROJECT_ROOT / "scripts/rollback_q1_quote_refresh_cron.sh"
        self.assertTrue(p.exists())
        import os
        self.assertTrue(os.access(str(p), os.X_OK))


class TestProviderPolicy(unittest.TestCase):
    def test_06_finviz_display_only(self):
        from quote_provider_trust_policy import classify_quote_provider
        r = classify_quote_provider("finviz")
        self.assertEqual(r["trust_level"], "display_only")
        self.assertFalse(r["is_execution_eligible"])

    def test_07_yfinance_display_only(self):
        from quote_provider_trust_policy import classify_quote_provider
        r = classify_quote_provider("yfinance")
        self.assertEqual(r["trust_level"], "display_only")

    def test_08_unknown_provider(self):
        from quote_provider_trust_policy import classify_quote_provider
        r = classify_quote_provider("unknown_source")
        self.assertEqual(r["trust_level"], "unknown")

    def test_09_missing_bid_ask_not_eligible(self):
        from quote_provider_trust_policy import is_execution_eligible_quote
        r = is_execution_eligible_quote("alpaca", {"last_price": 10.0})
        self.assertFalse(r["eligible"])

    def test_10_stale_quote_blocked(self):
        from quote_provider_trust_policy import is_execution_eligible_quote
        r = is_execution_eligible_quote("alpaca", {"bid": 10, "ask": 10.1, "quote_age_seconds": 5000})
        self.assertFalse(r["eligible"])

    def test_11_wide_spread_blocked(self):
        from quote_provider_trust_policy import is_execution_eligible_quote
        r = is_execution_eligible_quote("alpaca", {"bid": 10, "ask": 10.1, "spread_pct": 15.0})
        self.assertFalse(r["eligible"])


class TestSafety(unittest.TestCase):
    def test_12_dry_run_default(self):
        src = (PROJECT_ROOT / "scripts/run_proactive_quote_refresh.py").read_text()
        self.assertIn("default=True", src)

    def test_13_apply_requires_flag(self):
        src = (PROJECT_ROOT / "scripts/run_proactive_quote_refresh.py").read_text()
        self.assertIn("--apply", src)

    def test_14_wrapper_no_source_env(self):
        src = (PROJECT_ROOT / "scripts/run_scheduled_quote_refresh.sh").read_text()
        self.assertNotIn("source .env", src)
        self.assertNotIn("source $PROJ/.env", src)

    def test_15_wrapper_checks_alpaca(self):
        src = (PROJECT_ROOT / "scripts/run_scheduled_quote_refresh.sh").read_text()
        self.assertIn("ALPACA_MODE", src)
        self.assertIn("paper", src)

    def test_16_wrapper_checks_llm(self):
        src = (PROJECT_ROOT / "scripts/run_scheduled_quote_refresh.sh").read_text()
        self.assertIn("LLM_DISABLE_LIVE_EXECUTION", src)

    def test_17_wrapper_uses_flock(self):
        src = (PROJECT_ROOT / "scripts/run_scheduled_quote_refresh.sh").read_text()
        self.assertIn("flock", src)

    def test_18_no_trade_creation(self):
        for f in ["quote_provider_trust_policy.py", "select_quote_refresh_targets.py", "run_proactive_quote_refresh.py"]:
            src = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("create_order", src)
            self.assertNotIn("submit_order", src)

    def test_19_rollback_targets_q1_only(self):
        src = (PROJECT_ROOT / "scripts/rollback_q1_quote_refresh_cron.sh").read_text()
        self.assertIn("Q-1", src)
        self.assertNotIn("GOV-1", src)
        self.assertNotIn("Phase 9C", src)

    def test_20_r2_tests_pass(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "tests/test_r2_family_liquidity_gating.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120
        )
        self.assertEqual(r.returncode, 0, f"R-2 tests failed:\n{r.stderr}")


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
