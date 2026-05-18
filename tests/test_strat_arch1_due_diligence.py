#!/usr/bin/env python3
"""Tests for STRAT-ARCH-1 Strategy Architecture Due Diligence."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS = PROJECT_ROOT / "docs/strategy_architecture/phase_strat_arch1_due_diligence"


class TestDocumentation(unittest.TestCase):

    def test_01_quote_architecture_exists(self):
        self.assertTrue((DOCS / "01_quote_architecture.md").exists())

    def test_02_router_scoring_exists(self):
        self.assertTrue((DOCS / "02_router_scoring_architecture.md").exists())

    def test_03_taxonomy_exists(self):
        self.assertTrue((DOCS / "03_strategy_taxonomy.md").exists())

    def test_04_evidence_v2_exists(self):
        self.assertTrue((DOCS / "04_evidence_architecture_v2.md").exists())

    def test_05_finviz_architecture_exists(self):
        self.assertTrue((DOCS / "05_finviz_architecture.md").exists())

    def test_06_roadmap_exists(self):
        self.assertTrue((DOCS / "06_enhancement_roadmap.md").exists())


class TestDiagnostic(unittest.TestCase):

    def test_07_diagnostic_compiles(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/report_strategy_architecture_diagnostic.py"), doraise=True)

    def test_08_diagnostic_results_exist(self):
        self.assertTrue((DOCS / "strat_arch1_diagnostic_results.json").exists())

    def test_09_diagnostic_identifies_gaps(self):
        import json
        r = json.loads((DOCS / "strat_arch1_diagnostic_results.json").read_text())
        gaps = r.get("findings", {}).get("gaps_identified", {})
        self.assertGreater(len(gaps), 10)
        self.assertIn("R-5", gaps)
        self.assertIn("R-2", gaps)
        self.assertIn("Q-1", gaps)

    def test_10_roadmap_has_priorities(self):
        src = (DOCS / "06_enhancement_roadmap.md").read_text()
        self.assertIn("P0", src)
        self.assertIn("P1", src)
        self.assertIn("human_review_only", src)


class TestSafety(unittest.TestCase):

    def test_11_diagnostic_no_db_writes(self):
        src = (PROJECT_ROOT / "scripts/report_strategy_architecture_diagnostic.py").read_text()
        self.assertNotIn("INSERT INTO", src)
        self.assertNotIn("UPDATE ", src)
        self.assertNotIn("DELETE FROM", src)

    def test_12_no_strategy_activation(self):
        src = (PROJECT_ROOT / "scripts/report_strategy_architecture_diagnostic.py").read_text()
        self.assertNotIn("activate_strategy", src)

    def test_13_no_trade_creation(self):
        src = (PROJECT_ROOT / "scripts/report_strategy_architecture_diagnostic.py").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)

    def test_14_recommendations_human_review(self):
        src = (PROJECT_ROOT / "scripts/report_strategy_architecture_diagnostic.py").read_text()
        self.assertIn("human_review_only", src)

    def test_15_par1_regression_passes(self):
        import subprocess
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"), "-m", "unittest",
             "tests/test_par1_parallel_hardening_no_backup.py"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=60
        )
        self.assertEqual(r.returncode, 0, f"PAR-1 tests failed:\n{r.stderr}")


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if result.wasSuccessful() else 1)
