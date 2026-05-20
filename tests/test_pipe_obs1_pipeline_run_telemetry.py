#!/usr/bin/env python3
"""Tests for PIPE-OBS-1 pipeline run telemetry."""
import subprocess, sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_telemetry(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/pipeline_run_telemetry.py"), doraise=True)

    def test_02_api(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)

    def test_03_wrapper_syntax(self):
        r = subprocess.run(["bash", "-n", str(PROJECT_ROOT / "scripts/run_with_pipeline_telemetry.sh")], capture_output=True)
        self.assertEqual(r.returncode, 0)


class TestAPIQuery(unittest.TestCase):
    def test_04_uses_pipeline_key(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        # The pipeline-health-master handler queries pipeline_runs with pipeline_key
        self.assertIn("pipeline_key=%s ORDER BY started_at", src)

    def test_05_uses_correct_columns(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        # Should use finished_at and duration_seconds (actual column names)
        self.assertIn("finished_at as completed_at", src)
        self.assertIn("duration_seconds as duration_sec", src)


class TestTelemetryWriter(unittest.TestCase):
    def test_06_record_function_exists(self):
        from pipeline_run_telemetry import record_stage_run
        self.assertTrue(callable(record_stage_run))

    def test_07_no_trades(self):
        src = (PROJECT_ROOT / "scripts/pipeline_run_telemetry.py").read_text()
        self.assertNotIn("create_order", src)
        self.assertNotIn("submit_order", src)


class TestSafety(unittest.TestCase):
    def test_08_wrapper_no_env_source_raw(self):
        """Wrapper sources .env safely through set -a pattern."""
        src = (PROJECT_ROOT / "scripts/run_with_pipeline_telemetry.sh").read_text()
        self.assertIn("set -a; source", src)

    def test_09_no_strategy_activation(self):
        src = (PROJECT_ROOT / "scripts/pipeline_run_telemetry.py").read_text()
        self.assertNotIn("activate_strategy", src)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
