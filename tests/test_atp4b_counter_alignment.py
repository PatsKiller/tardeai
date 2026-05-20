#!/usr/bin/env python3
"""Tests for ATP-4B counter alignment."""
import sys, unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestCompile(unittest.TestCase):
    def test_01_api(self):
        import py_compile
        py_compile.compile(str(PROJECT_ROOT / "scripts/api_v2.py"), doraise=True)


class TestCounterLogic(unittest.TestCase):
    def test_02_unknown_quote_increments_review(self):
        """UNKNOWN_QUOTE must increment both unknown_quote_count AND review_count."""
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        # Find the UNKNOWN_QUOTE block
        idx = src.index("verdict = 'UNKNOWN_QUOTE'")
        block = src[idx:idx+300]
        self.assertIn("unknown_quote_count += 1", block)
        self.assertIn("review_count += 1", block)

    def test_03_stale_quote_increments_review(self):
        """STALE_QUOTE must increment both stale_count AND review_count."""
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        idx = src.index("verdict = 'STALE_QUOTE'")
        block = src[idx:idx+300]
        self.assertIn("stale_count += 1", block)
        self.assertIn("review_count += 1", block)

    def test_04_unknown_quote_blocks_approval(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        idx = src.index("verdict = 'UNKNOWN_QUOTE'")
        block = src[idx:idx+300]
        self.assertIn("prop['approval_allowed'] = False", block)

    def test_05_pipeline_message_shows_unknown(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        self.assertIn("unknown quotes", src)


class TestSafety(unittest.TestCase):
    def test_06_no_trades(self):
        src = (PROJECT_ROOT / "scripts/api_v2.py").read_text()
        # The proposals handler should not contain trade creation
        start = src.index("def _paper_proposals_enriched")
        end = src.index("def _open_trade_monitor_api")
        handler = src[start:end]
        self.assertNotIn("create_order", handler)
        self.assertNotIn("submit_order", handler)


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__import__(__name__)))
