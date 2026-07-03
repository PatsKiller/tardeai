"""Tests for outcome bus lifecycle slice export."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib.hermes_outcome_bus.lifecycle_slice import (  # noqa: E402
    build_lifecycle_slice,
    enrich_bus_with_lifecycle,
    holdings_research_multiplier,
)


class TestLifecycleBusSlice(unittest.TestCase):
    def test_holdings_research_multiplier_by_stage(self):
        lc = {
            "holdings": {
                "review_mode": True,
                "symbols": {
                    "AAA": {"lifecycle_stage": "healthy", "monitoring": {"research_depth": "standard"}},
                    "BBB": {"lifecycle_stage": "watch", "monitoring": {"research_depth": "elevated"}},
                    "CCC": {"lifecycle_stage": "trim_candidate", "monitoring": {"research_depth": "full"}},
                },
            },
        }
        self.assertEqual(holdings_research_multiplier("AAA", lc), 1.0)
        self.assertGreater(holdings_research_multiplier("BBB", lc), 1.0)
        self.assertGreaterEqual(holdings_research_multiplier("CCC", lc), 1.45)

    def test_enrich_bus_attaches_lifecycle(self):
        bus = {"by_symbol": {"XYZ": {"gate": "neutral", "n": 5}}}
        lc = {
            "watchlist": {"symbols": {"XYZ": {"health_score": 68, "lifecycle_stage": "monitoring"}}},
            "holdings": {"symbols": {}},
        }
        from lib.hermes_outcome_bus import lifecycle_slice as mod
        orig = mod.build_lifecycle_slice
        try:
            mod.build_lifecycle_slice = lambda: lc
            out = enrich_bus_with_lifecycle(dict(bus))
            self.assertIn("lifecycle", out)
            self.assertIn("watchlist_lifecycle", out["by_symbol"]["XYZ"])
        finally:
            mod.build_lifecycle_slice = orig

    def test_build_slice_structure(self):
        snap = build_lifecycle_slice()
        self.assertIn("watchlist", snap)
        self.assertIn("holdings", snap)
        self.assertIn("symbol_count", snap["watchlist"])


if __name__ == "__main__":
    unittest.main()