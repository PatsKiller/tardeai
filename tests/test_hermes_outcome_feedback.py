"""Unit tests for Outcome & Feedback Agent and outcome_bus coordination."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib.hermes_outcome_bus.bus import (
    OUTCOME_BUS_VERSION,
    governor_feedback_index,
    load_outcome_bus_trend,
    research_tag_multipliers,
    write_outcome_bus,
)
from lib.hermes_outcome_bus.metrics import (
    build_stop_correlations,
    calculate_resource_efficiency_score,
    compute_resource_efficiency_score,
)
from lib.hermes_outcome_bus.alert_enrichment import enrich_alert, enrich_alerts
from lib.hermes_outcome_bus.alert_notifications import dispatch_alert_notifications
from lib.hermes_outcome_bus.alerts import build_maturity_status, build_maturity_trend, evaluate_alerts
from lib.hermes_scope_governor.outcome_bus import apply_bus_to_edge_scores, bus_tier_override
from lib.hermes_scope_governor.reactions import build_bus_reaction_plan
from hermes_outcome_feedback_agent import (
    build_feedback_to_governor,
    build_feedback_to_research,
    _tag_quality_multiplier,
    _bad_dominant_tag,
    _symbol_poor_outcomes,
    _resolve_symbol_gate,
)


class TestTagMultiplier(unittest.TestCase):
    def test_negative_lift_downranks(self):
        cfg = {"tag_gates": {"negative_lift_downrank": 0.0, "downrank_multiplier": 0.6, "floor_multiplier": 0.3}}
        self.assertEqual(_tag_quality_multiplier(-0.29, True, cfg), 0.6)

    def test_positive_lift_boosts(self):
        cfg = {"tag_gates": {"positive_lift_boost": 0.02, "boost_multiplier": 1.15, "ceiling_multiplier": 1.25}}
        self.assertEqual(_tag_quality_multiplier(0.042, False, cfg), 1.15)


class TestGateRules(unittest.TestCase):
    def test_promote_blocked_on_bad_tag(self):
        self.assertEqual(
            _resolve_symbol_gate("promote_eligible", {"lift": -0.29, "tag_flagged": True}),
            "promote_blocked_bad_tag",
        )

    def test_tag_only_demotion_requires_poor_symbol(self):
        gates = {"min_graded_samples": 3, "promote_hit_rate": 0.5}
        good_symbol = {"n": 5, "outcome_hits": 4, "misses": 1, "gate": "neutral", "lift": -0.2, "tag_flagged": True}
        bad_symbol = {"n": 5, "outcome_hits": 1, "misses": 4, "gate": "demote_pressure", "lift": -0.2, "tag_flagged": True}
        self.assertFalse(_symbol_poor_outcomes(good_symbol, gates))
        self.assertTrue(_symbol_poor_outcomes(bad_symbol, gates))


class TestFeedbackBuilders(unittest.TestCase):
    def test_governor_pause_on_severe_miss(self):
        by_symbol = {
            "BAD": {"n": 5, "gate": "pause_eligible", "outcome_hits": 0, "misses": 4},
            "GOOD": {"n": 4, "gate": "promote_eligible", "outcome_hits": 3, "misses": 1, "lift": 0.04},
        }
        cfg = {"outcome_gates": {"min_graded_samples": 3, "pause_miss_rate": 0.75, "demote_miss_rate": 0.6,
                                 "promote_hit_rate": 0.5, "demote_score_penalty": -20, "promote_score_boost": 8}}
        fb = build_feedback_to_governor(by_symbol, cfg)
        actions = {x["symbol"]: x["action"] for x in fb}
        self.assertEqual(actions["BAD"], "pause")
        self.assertEqual(actions["GOOD"], "promote_eligible")
        self.assertEqual(fb[0]["edge_penalty"], -20)

    def test_no_tag_only_demotion_without_poor_symbol(self):
        by_symbol = {
            "OK": {"n": 5, "gate": "neutral", "outcome_hits": 4, "misses": 1, "lift": -0.29, "tag_flagged": True},
        }
        cfg = {"outcome_gates": {"min_graded_samples": 3, "promote_hit_rate": 0.5, "demote_score_penalty": -20}}
        fb = build_feedback_to_governor(by_symbol, cfg)
        self.assertEqual(len(fb), 0)

    def test_combined_tag_and_symbol_demotion(self):
        by_symbol = {
            "BAD": {"n": 4, "gate": "demote_pressure", "outcome_hits": 1, "misses": 3,
                    "lift": -0.29, "tag_flagged": True, "dominant_tag": "general_research"},
        }
        cfg = {"outcome_gates": {"min_graded_samples": 3, "promote_hit_rate": 0.5,
                                 "demote_miss_rate": 0.6, "demote_score_penalty": -20}}
        fb = build_feedback_to_governor(by_symbol, cfg)
        self.assertEqual(len(fb), 1)
        self.assertEqual(fb[0]["action"], "demote_pressure")

    def test_research_downrank_negative_tag(self):
        by_tag = {
            "general_research": {"n": 500, "lift": -0.292, "flagged": True, "quality_multiplier": 0.6},
            "momentum_scalp": {"n": 872, "lift": 0.042, "flagged": False, "quality_multiplier": 1.15},
        }
        cfg = {"tag_gates": {"min_samples_downrank": 15, "min_samples_boost": 15,
                             "negative_lift_downrank": 0.0, "positive_lift_boost": 0.02}}
        fb = build_feedback_to_research(by_tag, cfg)
        tags = {x["tag"]: x["action"] for x in fb}
        self.assertEqual(tags["general_research"], "downrank")
        self.assertEqual(tags["momentum_scalp"], "boost")


class TestBusReadWrite(unittest.TestCase):
    def test_write_and_index(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "outcome_bus.json"
            payload = {
                "run_id": "ofb_test",
                "global": {"hit_rate_promotions": 0.41},
                "by_symbol": {},
                "by_tag": {"momentum_scalp": {"quality_multiplier": 1.15, "lift": 0.042}},
                "feedback_to_governor": [
                    {"symbol": "XYZ", "action": "demote_pressure", "priority": 2, "edge_penalty": -20},
                    {"symbol": "XYZ", "action": "pause", "priority": 1, "edge_penalty": -20},
                ],
                "feedback_to_research": [
                    {"tag": "momentum_scalp", "action": "boost", "quality_multiplier": 1.15},
                ],
            }
            from lib.hermes_outcome_bus import bus as bus_mod
            old = bus_mod.OUTCOME_BUS_PATH
            try:
                bus_mod.OUTCOME_BUS_PATH = path
                write_outcome_bus(payload, apply=True)
                idx = governor_feedback_index(bus_mod.read_outcome_bus())
                self.assertEqual(idx["XYZ"]["action"], "pause")
                mult = research_tag_multipliers(bus_mod.read_outcome_bus())
                self.assertEqual(mult["momentum_scalp"], 1.15)
            finally:
                bus_mod.OUTCOME_BUS_PATH = old


class TestResourceEfficiencyScore(unittest.TestCase):
    def test_v1_formula_bounded(self):
        score, _ = calculate_resource_efficiency_score(0.372, 1299, 25, api_calls_7d=12)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_canonical_schema(self):
        global_m = {
            "hit_rate_promotions": 0.42,
            "throughput_research_rows_7d": 1000,
            "throughput_external_calls_7d": 50,
        }
        resource = {"live_universe": 200, "write_reduction_vs_baseline_pct": 0.55}
        cfg = {"resource_efficiency": {"pre_governor_live_universe": 4171}}
        out = compute_resource_efficiency_score(
            global_m, resource, cfg,
            positive_outcomes_7d=25,
            universe_size_change_pct=0.03,
            prior_score_7d=0.55,
        )
        self.assertEqual(out["score"], out["resource_efficiency_score"])
        self.assertIn("components", out)
        self.assertIn("hit_rate_promotions", out["components"])
        self.assertEqual(out["calculation_version"], "v1.1")
        self.assertIn("api_overhead_factor", out["components"])
        self.assertIn(out["trend_7d"], ("improving", "stable", "declining"))

    def test_stop_correlations_hot_vs_cold(self):
        by_tier = {
            "hot": {"trail_activation_rate": 0.55, "aligned_pct": 0.7, "sample_n": 10},
            "warm": {"trail_activation_rate": 0.45, "sample_n": 5},
            "cold": {"trail_activation_rate": 0.35, "aligned_pct": 0.5, "sample_n": 8},
        }
        corr = build_stop_correlations(by_tier)
        self.assertTrue(any("trail" in c.get("metric", "") for c in corr))


class TestOutcomeBusTrend(unittest.TestCase):
    def test_daily_dedup_and_series(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_outcome_bus import bus as bus_mod
            old_bus = bus_mod.OUTCOME_BUS_PATH
            old_hist = bus_mod.HISTORY_DIR
            try:
                hist = Path(td) / "history"
                hist.mkdir()
                bus_mod.HISTORY_DIR = hist
                bus_mod.OUTCOME_BUS_PATH = Path(td) / "outcome_bus.json"

                early = {
                    "version": OUTCOME_BUS_VERSION,
                    "run_id": "ofb_early",
                    "generated_at": "2026-07-01T03:25:00+00:00",
                    "global": {"hit_rate_promotions": 0.31},
                    "by_symbol": {"AAA": {"gate": "neutral"}},
                    "feedback_to_governor": [],
                }
                late = {
                    "version": OUTCOME_BUS_VERSION,
                    "run_id": "ofb_late",
                    "generated_at": "2026-07-01T03:40:00+00:00",
                    "global": {"hit_rate_promotions": 0.37},
                    "by_symbol": {"AAA": {"gate": "neutral"}, "BBB": {"gate": "demote_pressure"}},
                    "feedback_to_governor": [{"symbol": "BBB", "action": "demote_pressure"}],
                }
                (hist / "outcome_bus_2026-07-01T0325_ofb_early.json").write_text(json.dumps(early))
                (hist / "outcome_bus_2026-07-01T0340_ofb_late.json").write_text(json.dumps(late))
                write_outcome_bus({
                    "run_id": "ofb_now",
                    "generated_at": "2026-07-02T03:25:00+00:00",
                    "global": {"hit_rate_promotions": 0.372},
                    "by_symbol": {"AAA": {"gate": "neutral"}},
                    "feedback_to_governor": [],
                }, apply=True)

                trend = load_outcome_bus_trend(days=30)
                self.assertGreaterEqual(trend["count"], 2)
                days = [s["day"] for s in trend["series"]]
                self.assertIn("2026-07-01", days)
                self.assertIn("2026-07-02", days)
                july1 = next(s for s in trend["series"] if s["day"] == "2026-07-01")
                self.assertEqual(july1["hit_rate_promotions"], 0.37)
                self.assertEqual(july1["symbols_in_bus"], 2)
                self.assertEqual(july1["governor_feedback_count"], 1)
            finally:
                bus_mod.OUTCOME_BUS_PATH = old_bus
                bus_mod.HISTORY_DIR = old_hist


class TestTrendAlerts(unittest.TestCase):
    def _cfg(self):
        return {
            "alerts": {
                "hit_rate_decline_pp": 0.08,
                "hit_rate_window_days": 7,
                "efficiency_score_floor": 0.55,
                "efficiency_consecutive_days": 3,
                "scope_growth_pct": 0.15,
                "stop_hot_cold_delta_pp": 0.15,
                "stop_divergence_consecutive_days": 3,
            },
            "maturity": {"outcome_hit_rate_min": 0.35, "scope_efficiency_min": 0.55},
        }

    def test_hit_rate_declining_alert(self):
        trend = {
            "series": [
                {"day": "2026-07-01", "hit_rate_promotions": 0.45, "symbols_in_bus": 100},
                {"day": "2026-07-02", "hit_rate_promotions": 0.44, "symbols_in_bus": 102},
                {"day": "2026-07-03", "hit_rate_promotions": 0.36, "symbols_in_bus": 103},
            ]
        }
        alerts = evaluate_alerts({}, trend, self._cfg())
        ids = [a["id"] for a in alerts["active"]]
        self.assertIn("hit_rate_declining", ids)

    def test_efficiency_declining_alert(self):
        trend = {
            "series": [
                {"day": f"2026-07-0{i}", "resource_efficiency_score": 0.52}
                for i in range(1, 5)
            ]
        }
        alerts = evaluate_alerts({}, trend, self._cfg())
        ids = [a["id"] for a in alerts["active"]]
        self.assertIn("efficiency_declining", ids)

    def test_scope_creep_alert(self):
        trend = {
            "series": [
                {"day": "2026-06-20", "hit_rate_promotions": 0.40, "symbols_in_bus": 100},
                {"day": "2026-07-03", "hit_rate_promotions": 0.39, "symbols_in_bus": 120},
            ]
        }
        alerts = evaluate_alerts({}, trend, self._cfg())
        ids = [a["id"] for a in alerts["active"]]
        self.assertIn("scope_creep", ids)

    def test_stop_quality_divergence_alert(self):
        trend = {
            "series": [
                {"day": f"2026-07-0{i}", "stop_hot_cold_trail_delta": 0.10}
                for i in range(1, 5)
            ]
        }
        alerts = evaluate_alerts({}, trend, self._cfg())
        ids = [a["id"] for a in alerts["active"]]
        self.assertIn("stop_quality_divergence", ids)

    def test_maturity_status_shape(self):
        bus = {
            "global": {"hit_rate_promotions": 0.42, "graded_claims_90d": 120},
            "by_symbol": {"AAA": {}},
            "resource_efficiency": {"score": 0.65, "live_universe": 200},
            "stop_quality": {"by_tier": {"hot": {"trail_activation_rate": 0.55}, "cold": {"trail_activation_rate": 0.35}},
                           "aligned_pct": 0.62, "sample_n": 12},
            "feedback_to_governor": [{"symbol": "X"}],
            "feedback_to_research": [{"tag": "t", "action": "downrank"}],
        }
        alerts = {"active": [], "active_count": 0}
        maturity = build_maturity_status(bus, {"series": []}, alerts, self._cfg())
        self.assertEqual(maturity.get("version"), "maturity-v2")
        self.assertIn(maturity["tier"], ("nascent", "developing", "mature", "optimized"))
        self.assertIn(maturity["overall_status"], ("maturing", "mature", "at_risk"))
        self.assertGreaterEqual(maturity["composite_score"], 0)
        self.assertLessEqual(maturity["composite_score"], 100)
        self.assertIn(maturity["trend"], ("improving", "stable", "declining"))
        comps = maturity.get("components") or {}
        self.assertIn("outcome_yield", comps)
        self.assertIn("scope_discipline", comps)
        self.assertIn("stop_quality", comps)
        self.assertIn("feedback_loop", comps)
        self.assertIn("research_actionability", comps)

    def test_maturity_trend_series(self):
        trend = build_maturity_trend({
            "series": [
                {"day": "2026-07-01", "maturity_composite_score": 58, "maturity_tier": "developing"},
                {"day": "2026-07-02", "maturity_composite_score": 62, "maturity_tier": "developing"},
                {"day": "2026-07-03", "maturity_composite_score": 72, "maturity_tier": "mature"},
            ]
        })
        self.assertEqual(trend["count"], 3)
        self.assertEqual(trend["trend"], "improving")
        self.assertEqual(trend["current_tier"], "mature")
        self.assertEqual(trend["current_score"], 72)

    def test_alerts_active_count(self):
        alerts = evaluate_alerts({}, {"series": [
            {"day": "2026-07-01", "resource_efficiency_score": 0.50},
            {"day": "2026-07-02", "resource_efficiency_score": 0.48},
            {"day": "2026-07-03", "resource_efficiency_score": 0.47},
        ]}, self._cfg())
        self.assertGreater(alerts["active_count"], 0)


class TestAlertEnrichment(unittest.TestCase):
    def test_hit_rate_enrichment_has_contributors(self):
        bus = {
            "by_symbol": {
                "BAD": {"outcome_hits": 0, "misses": 5, "n": 5, "gate": "pause_eligible", "lift": -0.2},
                "GOOD": {"outcome_hits": 4, "misses": 1, "n": 5, "gate": "promote_eligible", "lift": 0.04},
            },
            "by_tag": {"general_research": {"lift": -0.29, "n": 100, "precision": 0.4}},
        }
        alert = {
            "id": "hit_rate_declining",
            "severity": "warning",
            "detail": "test",
            "metrics": {"window_days": 7},
        }
        enriched = enrich_alert(alert, bus, {})
        self.assertEqual(enriched["label"], "Hit rate declining")
        self.assertGreaterEqual(len(enriched["contributors"]["symbols"]), 1)
        self.assertEqual(enriched["contributors"]["symbols"][0]["symbol"], "BAD")
        self.assertIn("drilldown", enriched)
        self.assertIn("symbol_links", enriched["drilldown"])

    def test_enrich_alerts_batch(self):
        alerts = {"active": [{"id": "efficiency_declining", "severity": "warning", "metrics": {"streak_days": 3}}]}
        bus = {"by_symbol": {"X": {"gate": "demote_pressure", "misses": 3, "outcome_hits": 0, "n": 3}},
               "resource_efficiency": {"score": 0.48}}
        out = enrich_alerts(alerts, bus, {})
        self.assertEqual(out["active_count"], 1)
        self.assertIn("contributors", out["active"][0])


class TestAlertNotifications(unittest.TestCase):
    def test_cooldown_suppresses_repeat(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_outcome_bus import alert_notifications as mod
            old_state = mod.STATE_PATH
            old_audit = mod.AUDIT_PATH
            try:
                mod.STATE_PATH = Path(td) / "state.json"
                mod.AUDIT_PATH = Path(td) / "audit.jsonl"
                mod.STATE_PATH.write_text(json.dumps({
                    "last_sent": {"efficiency_declining": "2026-07-03T12:00:00+00:00"}
                }))
                cfg = {
                    "enabled": True,
                    "min_severity": "warning",
                    "cooldown_hours": 24,
                    "alert_types": {"efficiency_declining": True},
                    "channels": {"telegram": {"enabled": False}},
                }
                alerts = {"active": [{
                    "id": "efficiency_declining",
                    "severity": "warning",
                    "label": "Efficiency below threshold",
                    "detail": "score low",
                    "contributors": {"symbols": [], "tags": []},
                }]}
                r = dispatch_alert_notifications(alerts, cfg=cfg, dry_run=False)
                self.assertEqual(r["suppressed"], 1)
                self.assertEqual(r["sent"], 0)
            finally:
                mod.STATE_PATH = old_state
                mod.AUDIT_PATH = old_audit

    def test_type_disabled_skips(self):
        cfg = {
            "enabled": True,
            "min_severity": "warning",
            "alert_types": {"scope_creep": False},
            "channels": {"telegram": {"enabled": False}},
        }
        alerts = {"active": [{"id": "scope_creep", "severity": "warning", "detail": "x"}]}
        r = dispatch_alert_notifications(alerts, cfg=cfg, dry_run=True)
        self.assertEqual(r["sent"], 0)
        self.assertEqual(r["results"][0]["status"], "skipped")


class TestBusReactions(unittest.TestCase):
    def test_stop_quality_divergence_tightens(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_outcome_bus import bus as bus_mod
            old_bus = bus_mod.OUTCOME_BUS_PATH
            old_hist = bus_mod.HISTORY_DIR
            try:
                hist = Path(td) / "history"
                hist.mkdir()
                bus_mod.HISTORY_DIR = hist
                bus_mod.OUTCOME_BUS_PATH = Path(td) / "bus.json"
                for i, day in enumerate(["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"], 1):
                    snap = {
                        "version": OUTCOME_BUS_VERSION,
                        "generated_at": f"{day}T03:25:00+00:00",
                        "resource_efficiency": {"score": 0.65},
                        "stop_quality": {
                            "by_tier": {"hot": {"trail_activation_rate": 0.40}, "cold": {"trail_activation_rate": 0.30}},
                            "correlations": [{
                                "metric": "trail_activation_rate",
                                "hot_vs_cold_trail_activation_delta": 0.10,
                            }],
                        },
                        "by_tag": {},
                        "alerts": {"active": []},
                    }
                    (hist / f"outcome_bus_{day.replace('-', '')}_ofb_{i}.json").write_text(json.dumps(snap))
                bus_mod.OUTCOME_BUS_PATH.write_text(json.dumps(snap))
                cfg = {"bus_reactions": {
                    "enabled": True,
                    "stop_quality_reactions": {
                        "enabled": True,
                        "divergence_delta_pp": 0.13,
                        "divergence_consecutive_days": 4,
                    },
                }}
                plan = build_bus_reaction_plan(cfg, run_id="sg_test")
                self.assertGreater(plan.hot_min_score_delta, 0)
                self.assertGreater(plan.warm_cold_edge_penalty, 0)
                self.assertTrue(any(r.get("id") == "stop_quality_divergence" for r in plan.reactions))
            finally:
                bus_mod.OUTCOME_BUS_PATH = old_bus
                bus_mod.HISTORY_DIR = old_hist

    def test_review_mode_skips_runtime_write(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_outcome_bus import bus as bus_mod
            from lib.hermes_scope_governor import reactions as rx_mod
            old_bus = bus_mod.OUTCOME_BUS_PATH
            old_runtime = rx_mod.REACTIONS_RUNTIME_PATH
            try:
                bus_mod.OUTCOME_BUS_PATH = Path(td) / "bus.json"
                rx_mod.REACTIONS_RUNTIME_PATH = Path(td) / "runtime.json"
                bus_mod.OUTCOME_BUS_PATH.write_text(json.dumps({
                    "version": OUTCOME_BUS_VERSION,
                    "generated_at": "2026-07-03T03:25:00+00:00",
                    "alerts": {"active": [{"id": "scope_creep"}]},
                    "resource_efficiency": {"score": 0.65},
                    "stop_quality": {"by_tier": {}},
                    "by_tag": {},
                }))
                cfg = {"bus_reactions": {"enabled": True, "scope_creep_promotion_cap_reduction": 5}}
                plan = build_bus_reaction_plan(cfg, run_id="sg_test", review_mode=True)
                self.assertTrue(plan.review_mode)
                self.assertTrue(any(r.get("id") == "scope_creep_cap_reduction" for r in plan.reactions))
                path = rx_mod.write_reactions_runtime(plan, apply=True)
                self.assertIsNone(path)
                self.assertFalse(rx_mod.REACTIONS_RUNTIME_PATH.exists())
            finally:
                bus_mod.OUTCOME_BUS_PATH = old_bus
                rx_mod.REACTIONS_RUNTIME_PATH = old_runtime

    def test_reaction_includes_bus_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_outcome_bus import bus as bus_mod
            old = bus_mod.OUTCOME_BUS_PATH
            try:
                bus_mod.OUTCOME_BUS_PATH = Path(td) / "bus.json"
                bus_mod.OUTCOME_BUS_PATH.write_text(json.dumps({
                    "version": OUTCOME_BUS_VERSION,
                    "generated_at": "2026-07-03T03:25:00+00:00",
                    "global": {"hit_rate_promotions": 0.38},
                    "alerts": {"active": [{"id": "scope_creep"}]},
                    "resource_efficiency": {"score": 0.65, "live_universe": 120},
                    "stop_quality": {"by_tier": {}},
                    "by_tag": {},
                }))
                plan = build_bus_reaction_plan({"bus_reactions": {"enabled": True}}, run_id="sg_test")
                self.assertTrue(plan.bus_metrics.get("resource_efficiency_score") is not None)
                if plan.reactions:
                    self.assertIn("metrics", plan.reactions[0])
            finally:
                bus_mod.OUTCOME_BUS_PATH = old

    def test_r_left_worsening_reaction(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_outcome_bus import bus as bus_mod
            old_bus = bus_mod.OUTCOME_BUS_PATH
            old_hist = bus_mod.HISTORY_DIR
            try:
                hist = Path(td) / "history"
                hist.mkdir()
                bus_mod.HISTORY_DIR = hist
                bus_mod.OUTCOME_BUS_PATH = Path(td) / "bus.json"
                r_vals = [0.20, 0.22, 0.25, 0.28, 0.32, 0.36]
                for i, day in enumerate(["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05", "2026-07-06"], 0):
                    snap = {
                        "version": OUTCOME_BUS_VERSION,
                        "generated_at": f"{day}T03:25:00+00:00",
                        "resource_efficiency": {"score": 0.65},
                        "stop_quality": {
                            "r_left_on_table_avg": r_vals[i],
                            "by_tier": {"hot": {"trail_activation_rate": 0.5}, "cold": {"trail_activation_rate": 0.4}},
                            "correlations": [{"metric": "trail_activation_rate", "hot_vs_cold_trail_activation_delta": 0.10}],
                        },
                        "by_tag": {},
                        "alerts": {"active": []},
                    }
                    (hist / f"outcome_bus_{day.replace('-', '')}.json").write_text(json.dumps(snap))
                bus_mod.OUTCOME_BUS_PATH.write_text(json.dumps(snap))
                plan = build_bus_reaction_plan({"bus_reactions": {"enabled": True}}, run_id="sg_test")
                ids = [r.get("id") for r in plan.reactions]
                self.assertIn("stop_quality_r_left_worsening", ids)
            finally:
                bus_mod.OUTCOME_BUS_PATH = old_bus
                bus_mod.HISTORY_DIR = old_hist

    def test_scope_creep_reduces_promotion_cap(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_outcome_bus import bus as bus_mod
            old = bus_mod.OUTCOME_BUS_PATH
            try:
                bus_mod.OUTCOME_BUS_PATH = Path(td) / "bus.json"
                bus_mod.OUTCOME_BUS_PATH.write_text(json.dumps({
                    "version": OUTCOME_BUS_VERSION,
                    "generated_at": "2026-07-03T03:25:00+00:00",
                    "alerts": {"active": [{"id": "scope_creep"}]},
                    "resource_efficiency": {"score": 0.65},
                    "stop_quality": {"by_tier": {}},
                    "by_tag": {},
                }))
                cfg = {"bus_reactions": {"enabled": True, "scope_creep_promotion_cap_reduction": 5}}
                plan = build_bus_reaction_plan(cfg, run_id="sg_test")
                self.assertEqual(plan.max_outcome_promotions_delta, -5)
                self.assertTrue(any(r.get("id") == "scope_creep_cap_reduction" for r in plan.reactions))
            finally:
                bus_mod.OUTCOME_BUS_PATH = old


class TestGovernorBusIntegration(unittest.TestCase):
    def test_apply_bus_penalty_and_boost(self):
        cfg = {"scoring": {"outcome_gates": {"demote_score_penalty": 20, "promote_score_boost": 8}}}
        scores = {"BAD": 70.0, "GOOD": 60.0}
        details = {"BAD": {"reasons": []}, "GOOD": {"reasons": []}}
        from lib.hermes_outcome_bus import bus as bus_mod
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bus.json"
            path.write_text(json.dumps({
                "version": OUTCOME_BUS_VERSION,
                "feedback_to_governor": [
                    {"symbol": "BAD", "action": "demote_pressure", "edge_penalty": -20},
                    {"symbol": "GOOD", "action": "promote_eligible", "edge_boost": 8},
                ],
            }))
            old = bus_mod.OUTCOME_BUS_PATH
            try:
                bus_mod.OUTCOME_BUS_PATH = path
                new_scores, _ = apply_bus_to_edge_scores(scores, details, cfg)
                self.assertEqual(new_scores["BAD"], 50.0)
                self.assertEqual(new_scores["GOOD"], 68.0)
            finally:
                bus_mod.OUTCOME_BUS_PATH = old

    def test_bus_pause_override(self):
        cfg = {"scoring": {"outcome_gates": {"min_graded_samples": 3}}}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bus.json"
            path.write_text(json.dumps({
                "version": OUTCOME_BUS_VERSION,
                "feedback_to_governor": [
                    {"symbol": "BAD", "action": "pause", "evidence": {"n": 5}},
                ],
            }))
            from lib.hermes_outcome_bus import bus as bus_mod
            old = bus_mod.OUTCOME_BUS_PATH
            try:
                bus_mod.OUTCOME_BUS_PATH = path
                override = bus_tier_override("BAD", "S1", "S2", cfg)
                self.assertIsNotNone(override)
                self.assertEqual(override[0], "S3")
            finally:
                bus_mod.OUTCOME_BUS_PATH = old


if __name__ == "__main__":
    unittest.main()