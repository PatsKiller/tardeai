"""Symbol journey traceability API."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib.hermes_traceability.symbol_journey import build_symbol_journey  # noqa: E402


class TestSymbolJourney(unittest.TestCase):
    def test_requires_symbol(self):
        r = build_symbol_journey("")
        self.assertFalse(r["ok"])

    def test_builds_structure(self):
        r = build_symbol_journey("TEST")
        self.assertTrue(r["ok"])
        self.assertEqual(r["symbol"], "TEST")
        self.assertIn("timeline", r)
        self.assertIn("summary", r)
        self.assertIn("trace_links", r)


if __name__ == "__main__":
    unittest.main()