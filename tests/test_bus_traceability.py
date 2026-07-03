"""Outcome bus traceability sections."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib.hermes_outcome_bus.bus_traceability import (  # noqa: E402
    build_bus_lineage,
    build_holdings_health_section,
    build_watchlist_health_section,
    enrich_bus_traceability,
    enrich_stop_quality_trends,
    make_snapshot_id,
)


class TestBusTraceability(unittest.TestCase):
    def test_snapshot_id(self):
        sid = make_snapshot_id("ofb_abc", "2026-07-03T12:00:00+00:00")
        self.assertIn("ofb_abc", sid or "")

    def test_watchlist_health_section(self):
        wl = {
            "enabled": True,
            "summary": {"watch": 2},
            "symbols": {
                "XYZ": {
                    "health_score": 62,
                    "confidence_tier": "partial",
                    "graded_n": 5,
                    "lifecycle_stage": "watch",
                    "scope_tier": "S2",
                    "health_components": {
                        "outcome_performance": 55,
                        "stop_quality": 70,
                    },
                },
            },
            "health_history": {"XYZ": [{"at": "2026-07-01", "health_score": 58, "stage": "monitoring"}]},
        }
        sec = build_watchlist_health_section(wl, run_id="ofb_x", snapshot_id="snap_1")
        self.assertEqual(sec["symbol_count"], 1)
        self.assertIn("XYZ", sec["symbols"])
        self.assertEqual(sec["symbols"]["XYZ"]["data_quality"], "partial")
        self.assertIn("components", sec["symbols"]["XYZ"])
        self.assertIn("lineage", sec["symbols"]["XYZ"])

    def test_holdings_health_section(self):
        hl = {
            "holdings": {
                "SCHD": {
                    "health_score": 74,
                    "lifecycle_stage": "healthy",
                    "health_components": {"stop_quality": 80},
                },
            },
            "history": {"SCHD": [{"at": "2026-07-02", "health_score": 72}]},
        }
        sq = {"trail_activation_rate": 0.42, "aligned_pct": 0.61, "by_tier": {}}
        sec = build_holdings_health_section(hl, sq, run_id="ofb_x", snapshot_id="snap_1")
        self.assertIn("SCHD", sec["symbols"])
        self.assertEqual(sec["symbols"]["SCHD"]["stop_quality"]["trail_activation_rate"], 0.42)

    def test_stop_quality_trends(self):
        series = [
            {"trail_activation_rate": 0.40, "aligned_pct": 0.55},
            {"trail_activation_rate": 0.42, "aligned_pct": 0.58},
            {"trail_activation_rate": 0.45, "aligned_pct": 0.60},
        ]
        out = enrich_stop_quality_trends({"trail_activation_rate": 0.45}, {"series": series})
        self.assertIn("trends", out)
        self.assertIn("window_7d", out["trends"])

    def test_enrich_bus_traceability(self):
        bus = {
            "run_id": "ofb_test",
            "generated_at": "2026-07-03T18:00:00+00:00",
            "global": {"hit_rate_promotions": 0.35},
            "by_symbol": {"AAA": {"gate": "neutral", "n": 3}},
            "stop_quality": {"trail_activation_rate": 0.4},
            "feedback_to_governor": [{"symbol": "AAA", "action": "neutral"}],
            "source_runs": {"upstream": ["grader"], "downstream": ["governor"]},
        }
        from lib.hermes_outcome_bus import lifecycle_slice as lc
        orig_wl = lc._load_watchlist_lifecycle
        orig_hl = lc._load_holdings_lifecycle
        try:
            lc._load_watchlist_lifecycle = lambda: {"symbols": {}, "summary": {}}
            lc._load_holdings_lifecycle = lambda: {"holdings": {}, "summary": {}}
            out = enrich_bus_traceability(bus, trend={"series": []})
            self.assertIn("lineage", out)
            self.assertIn("watchlist_health", out)
            self.assertIn("holdings_health", out)
            self.assertIn("threshold_proposals", out)
            self.assertIn("lifecycle", out)
            self.assertIn("lineage", out["by_symbol"]["AAA"])
            self.assertIn("source_refs", out["feedback_to_governor"][0])
        finally:
            lc._load_watchlist_lifecycle = orig_wl
            lc._load_holdings_lifecycle = orig_hl

    def test_bus_lineage_prior(self):
        bus = {"run_id": "ofb_new", "generated_at": "2026-07-04T00:00:00+00:00"}
        prior = {"run_id": "ofb_old", "lineage": {"snapshot_id": "snap_old"}}
        lin = build_bus_lineage(bus, prior)
        self.assertEqual(lin["prior_run_id"], "ofb_old")
        self.assertEqual(lin["prior_snapshot_id"], "snap_old")


if __name__ == "__main__":
    unittest.main()