#!/usr/bin/env python3
"""Unit tests for Phase 8B lifecycle outcome scoring."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestPhase8BLifecycleOutcomes(unittest.TestCase):

    def test_01_schema_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/create_phase8_lifecycle_outcome_schema.py"), doraise=True)

    def test_02_backfill_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/backfill_phase8_paper_trade_lifecycle_outcomes.py"), doraise=True)

    def test_03_scorecards_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/generate_phase8_strategy_scorecards.py"), doraise=True)

    def test_04_outcome_label_logic(self):
        from backfill_phase8_paper_trade_lifecycle_outcomes import determine_outcome_label
        self.assertEqual(determine_outcome_label({"status": "open"}), "open")
        self.assertEqual(determine_outcome_label({"status": "cancelled"}), "cancelled")
        self.assertEqual(determine_outcome_label({"status": "closed", "exit_reason": "target_hit", "pnl": 50}), "target_hit")
        self.assertEqual(determine_outcome_label({"status": "closed", "exit_reason": "stop_hit", "pnl": -20}), "stopped")
        self.assertEqual(determine_outcome_label({"status": "closed", "exit_reason": "manual", "pnl": 30}), "win")
        self.assertEqual(determine_outcome_label({"status": "closed", "exit_reason": "manual", "pnl": -15}), "loss")
        self.assertEqual(determine_outcome_label({"status": "closed", "exit_reason": "manual", "pnl": 0}), "breakeven")

    def test_05_no_source_table_mutation(self):
        """Backfill script has no UPDATE/DELETE on paper_trades or paper_trade_proposals."""
        script = (PROJECT_ROOT / "scripts/backfill_phase8_paper_trade_lifecycle_outcomes.py").read_text()
        self.assertNotIn("UPDATE paper_trades", script)
        self.assertNotIn("DELETE FROM paper_trades", script)
        self.assertNotIn("UPDATE paper_trade_proposals", script)

    def test_06_scorecards_human_review_only(self):
        """Strategy scorecards always use human_review_only."""
        script = (PROJECT_ROOT / "scripts/generate_phase8_strategy_scorecards.py").read_text()
        self.assertIn("human_review_only", script)
        self.assertNotIn("auto_apply", script)

    def test_07_no_order_submission(self):
        """No Alpaca order submission in Phase 8B scripts."""
        for f in ["backfill_phase8_paper_trade_lifecycle_outcomes.py",
                  "generate_phase8_strategy_scorecards.py",
                  "create_phase8_lifecycle_outcome_schema.py"]:
            script = (PROJECT_ROOT / "scripts" / f).read_text()
            self.assertNotIn("submit_paper", script)
            self.assertNotIn("submit_order", script)

    def test_08_phase6_regression(self):
        from paper_trade_logger import validate_paper_proposal_live_market
        from datetime import datetime, timezone
        r = validate_paper_proposal_live_market("TEST", 100.0, 95.0, 110.0, 50,
            {"last_price": 100.5, "spread_pct": 0.1, "quote_timestamp": datetime.now(timezone.utc)})
        self.assertTrue(r["ok"])

    def test_09_phase7_regression(self):
        from simulate_paper_proposal_approval import simulate_proposal
        # Just verify it imports and the function exists
        self.assertTrue(callable(simulate_proposal))


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestPhase8BLifecycleOutcomes))
    sys.exit(0 if result.wasSuccessful() else 1)
