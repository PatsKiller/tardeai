#!/usr/bin/env python3
"""Unit tests for Phase 6E scheduled stale proposal sweeper.

Standalone runner:
    .venv/bin/python tests/test_phase6e_scheduled_stale_sweeper.py
"""
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestScheduledStaleSweeper(unittest.TestCase):

    # 1. Wrapper defaults to dry-run
    def test_01_wrapper_defaults_dry_run(self):
        script = (PROJECT_ROOT / "scripts/run_scheduled_stale_proposal_sweeper.sh").read_text()
        self.assertIn('MODE="${1:---dry-run}"', script)

    # 2. Wrapper checks ALPACA_MODE
    def test_02_wrapper_checks_alpaca_mode(self):
        script = (PROJECT_ROOT / "scripts/run_scheduled_stale_proposal_sweeper.sh").read_text()
        self.assertIn('ALPACA_MODE', script)
        self.assertIn('"paper"', script)

    # 3. Wrapper checks LLM_DISABLE_LIVE_EXECUTION
    def test_03_wrapper_checks_llm_disable(self):
        script = (PROJECT_ROOT / "scripts/run_scheduled_stale_proposal_sweeper.sh").read_text()
        self.assertIn('LLM_DISABLE_LIVE_EXECUTION', script)

    # 4. Wrapper uses flock
    def test_04_wrapper_uses_flock(self):
        script = (PROJECT_ROOT / "scripts/run_scheduled_stale_proposal_sweeper.sh").read_text()
        self.assertIn('/tmp/tradeai_stale_proposal_sweeper.lock', script)

    # 5. Rollback dry-run does not alter cron (structural)
    def test_05_rollback_dry_run_safe(self):
        script = (PROJECT_ROOT / "scripts/rollback_phase6e_stale_sweeper_cron.sh").read_text()
        # dry-run section should not call 'crontab -' (write)
        lines = script.split('\n')
        in_dry_run = False
        for line in lines:
            if '--dry-run)' in line:
                in_dry_run = True
            elif in_dry_run and ';;' in line:
                break
            elif in_dry_run:
                self.assertNotIn('| crontab -', line,
                    "dry-run should not pipe to crontab")

    # 6. Rollback removes only Phase 6E entries
    def test_06_rollback_targets_correct_pattern(self):
        script = (PROJECT_ROOT / "scripts/rollback_phase6e_stale_sweeper_cron.sh").read_text()
        self.assertIn('run_scheduled_stale_proposal_sweeper', script)
        self.assertNotIn('cleanup_stale_proposals', script)

    # 7. No delete/trade/order in wrapper
    def test_07_wrapper_no_dangerous_commands(self):
        script = (PROJECT_ROOT / "scripts/run_scheduled_stale_proposal_sweeper.sh").read_text()
        self.assertNotIn('DELETE FROM', script)
        self.assertNotIn('submit_paper', script)
        self.assertNotIn('approve_proposal', script)
        self.assertNotIn('submit_order', script)

    # 8. Apply mode calls sweeper with --apply
    def test_08_apply_invokes_sweeper_apply(self):
        script = (PROJECT_ROOT / "scripts/run_scheduled_stale_proposal_sweeper.sh").read_text()
        self.assertIn('--apply)', script)
        self.assertIn('sweep_stale_paper_proposals.py" --apply', script)

    # 9. Report-only mode calls report script
    def test_09_report_only_calls_report(self):
        script = (PROJECT_ROOT / "scripts/run_scheduled_stale_proposal_sweeper.sh").read_text()
        self.assertIn('--report-only)', script)
        self.assertIn('report_phase6_stale_proposals.py', script)

    # 10. Holdings guard present
    def test_10_holdings_guard(self):
        script = (PROJECT_ROOT / "scripts/run_scheduled_stale_proposal_sweeper.sh").read_text()
        self.assertIn('holdings.json', script)
        self.assertIn('file_is_intact', script)

    # 11. Phase 6A-D regression
    def test_11_phase6a_regression(self):
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from paper_trade_logger import validate_paper_proposal_live_market
        from datetime import datetime, timezone
        r = validate_paper_proposal_live_market(
            "TEST", 100.0, 95.0, 110.0, 50,
            {"last_price": 100.5, "spread_pct": 0.1,
             "quote_timestamp": datetime.now(timezone.utc)})
        self.assertTrue(r["ok"])

    def test_12_phase6d_regression(self):
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from phase6_proposal_staleness_policy import classify_proposal_staleness
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        r = classify_proposal_staleness(
            {"status": "PENDING", "strategy_id": "gap_and_go",
             "created_at": now - timedelta(minutes=90)}, now)
        self.assertTrue(r["stale"])


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromTestCase(TestScheduledStaleSweeper))
    sys.exit(0 if result.wasSuccessful() else 1)
