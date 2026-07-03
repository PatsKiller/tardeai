"""Unit tests for Hermes watchlist lifecycle (Phase 1 + Phase 2 health)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib.hermes_scope_governor.models import ScopeDecision  # noqa: E402
from lib.hermes_scope_governor.watchlist_health import (  # noqa: E402
    compute_health_components,
    compute_watchlist_health_score,
    passes_promotion_health_gate,
    health_trend_delta,
)
from lib.hermes_scope_governor.watchlist_lifecycle import (  # noqa: E402
    apply_manual_override,
    compute_conviction,
    load_lifecycle_config,
    resolve_stage,
    build_lifecycle_snapshot,
)


class TestWatchlistLifecycleScoring(unittest.TestCase):
    def test_conviction_gate_adjustments(self):
        cfg = load_lifecycle_config()
        base = compute_conviction(70.0, "neutral", None, cfg)
        promo = compute_conviction(70.0, "promote_eligible", None, cfg)
        demote = compute_conviction(70.0, "demote_pressure", None, cfg)
        self.assertGreater(promo, base)
        self.assertLess(demote, base)

    def test_resolve_promoted_for_s1(self):
        cfg = load_lifecycle_config()
        stage, reason = resolve_stage(
            "S1", "S1", None, "neutral", 72.0, 70.0, None, 30, None, None, cfg,
        )
        self.assertEqual(stage, "promoted")
        self.assertIn("hot_tier", reason)

    def test_resolve_demoted_on_pressure(self):
        cfg = load_lifecycle_config()
        stage, _ = resolve_stage(
            "S2", "S2", None, "demote_pressure", 45.0, 55.0, None, 20, None, None, cfg,
        )
        self.assertEqual(stage, "demoted")

    def test_resolve_watch_on_health_band(self):
        cfg = load_lifecycle_config()
        stage, reason = resolve_stage(
            "S2", "S2", None, "neutral", 55.0, 52.0, None, 20, None, None, cfg,
        )
        self.assertEqual(stage, "watch")
        self.assertIn("health_watch_band", reason)

    def test_resolve_watch_on_trend_decline(self):
        cfg = load_lifecycle_config()
        stage, reason = resolve_stage(
            "S2", "S2", None, "neutral", 65.0, 68.0, -12.0, 20, None, None, cfg,
        )
        self.assertEqual(stage, "watch")
        self.assertIn("health_declining", reason)

    def test_resolve_pending_promote(self):
        cfg = load_lifecycle_config()
        pending = {"action": "promote", "to_tier": "S1", "reason": "outcome_edge>=65"}
        stage, reason = resolve_stage(
            "S2", "S1", pending, "promote_eligible", 68.0, 70.0, None, 10, None, None, cfg,
        )
        self.assertEqual(stage, "promoted")
        self.assertIn("pending", reason)

    def test_manual_override_blacklist(self):
        cfg = load_lifecycle_config()
        stage, reason = resolve_stage(
            "S3", "S3", None, "pause_eligible", 30.0, 30.0, None, 5, "blacklisted", None, cfg,
        )
        self.assertEqual(stage, "blacklisted")
        self.assertIn("manual_override", reason)


class TestWatchlistHealthScoring(unittest.TestCase):
    def test_health_score_with_confidence_discount(self):
        cfg = load_lifecycle_config()
        components = {
            "outcome_performance": 80.0,
            "promotion_success_rate": 70.0,
            "tag_lift_consistency": 60.0,
            "stop_quality": 65.0,
            "regime_alignment": 55.0,
            "research_efficiency": 50.0,
            "edge_blend": 72.0,
        }
        raw, final, tier = compute_watchlist_health_score(components, graded_n=2, cfg=cfg)
        self.assertEqual(tier, "sparse_data")
        self.assertLess(final, raw)

    def test_promotion_health_gate_blocks_weak(self):
        cfg = load_lifecycle_config()
        ok, reason = passes_promotion_health_gate(58.0, "full", 5, cfg)
        self.assertFalse(ok)
        self.assertIn("health=", reason)
        ok2, _ = passes_promotion_health_gate(65.0, "full", 5, cfg)
        self.assertTrue(ok2)

    def test_health_trend_delta(self):
        hist = [{"health_score": 70}, {"health_score": 65}, {"health_score": 58}]
        delta = health_trend_delta(hist, days=2)
        self.assertEqual(delta, -12.0)

    def test_compute_health_components_defaults(self):
        cfg = load_lifecycle_config()
        sig = SimpleNamespace(
            outcome_hits=2, outcome_misses=1, outcome_neutral=0,
            avg_realized_r=0.4, atr_pct=3.0, research_actioned_rate=None,
        )
        comps = compute_health_components("AAA", sig, {"edge_score": 68}, None, None, {}, "trend_up", cfg)
        self.assertIn("outcome_performance", comps)
        self.assertGreater(comps["outcome_performance"], 40)


class TestWatchlistLifecycleSnapshot(unittest.TestCase):
    def test_build_snapshot_pending_transitions(self):
        cfg = load_lifecycle_config()
        have = {
            "AAA": {"tier": "S2", "first_seen": "2026-06-01T00:00:00+00:00"},
            "BBB": {"tier": "S1", "first_seen": "2026-05-01T00:00:00+00:00"},
        }
        want = {"AAA": ("S1", "outcome_edge>=65"), "BBB": ("S1", "active_watchlist")}
        post = {"AAA": "S1", "BBB": "S1"}
        decisions = [
            ScopeDecision("AAA", "S2", "S1", "promote", "outcome_edge>=65", 68.0, "hot", "every_30m_market_hours", {"outcome_gate": "promote_eligible"}),
        ]
        health_map = {
            "AAA": {
                "health_score": 68.0, "health_score_raw": 72.0, "confidence_tier": "full",
                "graded_n": 5, "display_score": 69.0,
                "health_components": {"outcome_performance": 70},
            },
            "BBB": {
                "health_score": 75.0, "confidence_tier": "full", "graded_n": 8,
                "display_score": 74.0, "health_components": {},
            },
        }
        snap = build_lifecycle_snapshot(
            "sg_test", {}, {"AAA": 68.0, "BBB": 72.0},
            {"AAA": {"outcome_gate": "promote_eligible"}, "BBB": {"outcome_gate": "neutral"}},
            have, want, decisions, post, {}, cfg,
            health_map=health_map,
            blocked_promotions=[{"symbol": "ZZZ", "reason": "health=50<62"}],
        )
        self.assertEqual(snap["pending_count"], 1)
        self.assertEqual(snap["blocked_promotion_count"], 1)
        self.assertIn("AAA", snap["symbols"])
        self.assertEqual(snap["symbols"]["AAA"]["lifecycle_stage"], "promoted")
        self.assertEqual(snap["symbols"]["AAA"]["health_score"], 68.0)
        self.assertTrue(snap["symbols"]["BBB"]["lifecycle_stage"] in ("promoted", "monitoring"))


class TestWatchlistLifecycleOverride(unittest.TestCase):
    def test_apply_override_persists(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_scope_governor import watchlist_lifecycle as mod
            old_path = mod.LIFECYCLE_PATH
            old_audit = mod.AUDIT_PATH
            try:
                mod.LIFECYCLE_PATH = Path(td) / "lifecycle.json"
                mod.AUDIT_PATH = Path(td) / "audit.jsonl"
                mod.save_lifecycle_state({
                    "version": "watchlist-lifecycle-v1",
                    "symbols": {"ZZZ": {"symbol": "ZZZ", "lifecycle_stage": "monitoring"}},
                    "overrides": {},
                })
                result = apply_manual_override("ZZZ", "blacklisted", "operator flagged noise", by="test")
                self.assertTrue(result["ok"])
                state = mod.load_lifecycle_state()
                self.assertEqual(state["overrides"]["ZZZ"]["stage"], "blacklisted")
            finally:
                mod.LIFECYCLE_PATH = old_path
                mod.AUDIT_PATH = old_audit


if __name__ == "__main__":
    unittest.main()