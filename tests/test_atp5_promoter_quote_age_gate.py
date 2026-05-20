#!/usr/bin/env python3
"""Tests for ATP-5 promoter quote-age gate."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_gap_report(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_promoter_quote_age_gate_gap.py"), doraise=True)

    def test_02_promoter(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/incubator_proposal_promoter.py"), doraise=True)

    def test_03_policy(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/pre_promotion_readiness_policy.py"), doraise=True)


class TestQuoteAgeGate(unittest.TestCase):
    def test_04_hard_expire_blocks(self):
        from pre_promotion_readiness_policy import evaluate_pre_promotion_readiness
        r = evaluate_pre_promotion_readiness({
            "symbol": "TEST", "strategy_id": "recovery_watch",
            "proposed_entry": 10, "proposed_stop": 9, "proposed_target1": 12,
            "scan_age_hours": 200,
        })
        self.assertTrue(any("extremely_stale" in b for b in r["blockers"]))

    def test_05_unknown_quote_blocks(self):
        from pre_promotion_readiness_policy import evaluate_pre_promotion_readiness
        r = evaluate_pre_promotion_readiness({
            "symbol": "TEST", "strategy_id": "swing_trade",
            "proposed_entry": 10, "proposed_stop": 9, "proposed_target1": 12,
            # No scan_age_hours, no quote_checked_at
        })
        self.assertTrue(any("quote_never_checked" in b for b in r["blockers"]))

    def test_06_fresh_quote_allows(self):
        from pre_promotion_readiness_policy import evaluate_pre_promotion_readiness
        r = evaluate_pre_promotion_readiness({
            "symbol": "TEST", "strategy_id": "swing_trade",
            "proposed_entry": 10, "proposed_stop": 9, "proposed_target1": 12,
            "scan_age_hours": 2,
        })
        self.assertFalse(any("quote" in b for b in r["blockers"]))

    def test_07_hdsn_style_blocked(self):
        from pre_promotion_readiness_policy import evaluate_pre_promotion_readiness
        r = evaluate_pre_promotion_readiness({
            "symbol": "HDSN", "strategy_id": "recovery_watch",
            "proposed_entry": 5, "proposed_stop": 4.5, "proposed_target1": 6,
            "scan_age_hours": 310,
        })
        self.assertTrue(len(r["blockers"]) > 0)
        self.assertFalse(r["promote_ready"])

    def test_08_gate_version_updated(self):
        from pre_promotion_readiness_policy import evaluate_pre_promotion_readiness
        r = evaluate_pre_promotion_readiness({
            "symbol": "TEST", "strategy_id": "swing_trade",
            "proposed_entry": 10, "proposed_stop": 9, "proposed_target1": 12,
            "scan_age_hours": 1,
        })
        self.assertIn("v2", r["gate_version"])

    def test_09_promoter_passes_scan_age(self):
        src = (PROJECT_ROOT / "scripts/incubator_proposal_promoter.py").read_text()
        self.assertIn("scan_age_hours", src)


class TestSafety(unittest.TestCase):
    def test_10_no_trades(self):
        src = (PROJECT_ROOT / "scripts/report_promoter_quote_age_gate_gap.py").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)

    def test_11_no_approval(self):
        src = (PROJECT_ROOT / "scripts/pre_promotion_readiness_policy.py").read_text()
        self.assertNotIn("approve_proposal", src)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
