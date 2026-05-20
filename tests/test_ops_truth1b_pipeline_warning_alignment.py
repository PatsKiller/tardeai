#!/usr/bin/env python3
"""Tests for OPS-TRUTH-1B pipeline warning alignment."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_api(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)


class TestPipelineLogic(unittest.TestCase):
    def test_02_never_run_counts_as_warning(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("never_run += 1", src)
        # never_run stages with cadence should be amber/warning
        idx = src.index("never_run += 1")
        block = src[idx:idx+200]
        self.assertIn("warnings += 1", block)

    def test_03_last_full_cycle_not_current_time(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertNotIn('now.strftime("%I:%M %p")', src)
        self.assertIn("latest_run_ts", src)
        self.assertIn("No runs recorded", src)

    def test_04_never_run_counter_in_summary(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn('"never_run":', src)

    def test_05_frontend_shows_warnings(self):
        src = (PROJECT_ROOT / "apps/command-center-v2/src/pages/PipelineHealthMaster.tsx").read_text()
        self.assertIn("warnings", src.lower())
        self.assertIn("never run", src.lower())


class TestSafety(unittest.TestCase):
    def test_06_no_trades(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        # Pipeline health handler should not create trades
        idx = src.index("pipeline-health-master")
        block = src[idx:idx+3000]
        self.assertNotIn("create_order", block)

    def test_07_frontend_builds(self):
        dist = PROJECT_ROOT / "apps/command-center-v2/dist/assets"
        self.assertTrue(list(dist.glob("index-*.js")))


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
