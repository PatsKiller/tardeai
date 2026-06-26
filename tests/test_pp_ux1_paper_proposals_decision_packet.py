#!/usr/bin/env python3
"""Tests for PP-UX-1 Paper Proposals decision packet redesign."""
import sys, unittest, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestPPUX1APIEnrichment(unittest.TestCase):
    """Verify API enrichment adds strategy config metadata."""

    def test_01_strategy_config_loader_importable(self):
        from strategy_config_loader import load_strategy_config
        self.assertTrue(callable(load_strategy_config))

    def test_02_recovery_watch_yaml_has_purpose(self):
        from strategy_config_loader import load_strategy_config
        cfg = load_strategy_config('swing_breakout')
        self.assertIn('purpose', cfg)
        self.assertTrue(len(cfg['purpose']) > 10)

    def test_03_recovery_watch_yaml_has_entry_criteria(self):
        from strategy_config_loader import load_strategy_config
        cfg = load_strategy_config('swing_breakout')
        self.assertIn('entry_criteria', cfg)
        self.assertTrue(len(cfg['entry_criteria']) > 0)
        self.assertIn('description', cfg['entry_criteria'][0])

    def test_04_recovery_watch_yaml_has_risk(self):
        from strategy_config_loader import load_strategy_config
        cfg = load_strategy_config('swing_breakout')
        self.assertIn('risk', cfg)
        self.assertIn('risk_per_trade_pct', cfg['risk'])

    def test_05_all_strategies_have_purpose(self):
        from strategy_config_loader import load_all_strategy_configs
        configs = load_all_strategy_configs()
        self.assertTrue(len(configs) >= 10)
        for sid, cfg in configs.items():
            self.assertIn('purpose', cfg, f"{sid} missing purpose")

    def test_06_api_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)


class TestPPUX1FrontendBuild(unittest.TestCase):
    """Verify frontend builds and contains expected patterns."""

    def test_07_frontend_dist_exists(self):
        dist = PROJECT_ROOT / "apps/command-center-v2/dist/assets"
        pp_files = list(dist.glob("PaperProposals-*.js"))
        self.assertTrue(len(pp_files) > 0, "PaperProposals bundle not found")

    def test_08_frontend_has_sector_display(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertIn('Sector: Missing', src)
        self.assertIn('p.sector', src)
        self.assertIn('p.industry', src)

    def test_09_frontend_has_strategy_description(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertIn('strategy_description', src)
        self.assertIn('Strategy:', src)

    def test_10_frontend_has_entry_rationale(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertIn('entry_rationale', src)
        self.assertIn('stop_rationale', src)
        self.assertIn('target_rationale', src)

    def test_11_frontend_has_approval_blockers(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertIn('approval_blockers', src)

    def test_12_frontend_has_guided_workflow(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertIn('1. Refresh Price', src)
        self.assertIn('2. Check Execution', src)
        self.assertIn('3. AI Review', src)
        self.assertIn('4. Approve', src)

    def test_13_frontend_has_incubator_diagnostics(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertIn('incubator_diagnostics', src)
        self.assertIn('Why underfilled', src)

    def test_14_frontend_has_staleness_policy(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertIn('staleness_policy', src)
        self.assertIn('STALE', src)

    def test_15_frontend_has_evidence_tiles(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertIn('MetricTile', src)
        self.assertIn('Strategy Fit', src)
        self.assertIn('Execution', src)
        self.assertIn('Technical', src)
        self.assertIn('Catalyst', src)


class TestPPUX1Safety(unittest.TestCase):
    """Verify safety constraints are preserved."""

    def test_16_no_trade_creation_in_api_changes(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        # PP-UX-1 section should not contain INSERT/UPDATE/DELETE
        idx = src.find('PP-UX-1: Enrich with strategy YAML')
        end_idx = src.find('Session 25: Add screener_display_name', idx)
        if idx > 0 and end_idx > idx:
            section = src[idx:end_idx]
            self.assertNotIn('INSERT INTO', section)
            self.assertNotIn('UPDATE ', section)
            self.assertNotIn('DELETE FROM', section)

    def test_17_no_order_submission_in_frontend(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        # Must not contain direct alpaca/broker calls
        self.assertNotIn('alpaca.create_order', src)
        self.assertNotIn('broker.submit', src)

    def test_18_env_not_sourced(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        idx = src.find('PP-UX-1: Enrich with strategy YAML')
        end_idx = src.find('Session 25: Add screener_display_name', idx)
        if idx > 0 and end_idx > idx:
            section = src[idx:end_idx]
            self.assertNotIn('source .env', section)
            self.assertNotIn('dotenv', section)

    def test_19_no_strategy_activation_change(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PaperProposals.tsx").read_text()
        self.assertNotIn('activate_strategy', src)
        self.assertNotIn('enable_live', src)

    def test_20_existing_tests_pass(self):
        """Ensure prior governance tests still pass."""
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "tests/test_gov1_scheduled_governance.py",
             "tests/test_phase9b_maturity_control_board.py",
             "tests/test_phase9c_scheduled_maturity_board.py",
             "tests/test_sp1_strategy_proof_governance.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=60
        )
        self.assertEqual(r.returncode, 0, f"Regression tests failed:\n{r.stderr}")


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
