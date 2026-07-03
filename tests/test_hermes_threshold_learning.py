"""Unit tests for Hermes adaptive threshold learning (Phase 1)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib.hermes_thresholds.store import (  # noqa: E402
    get_active_value,
    load_threshold_config,
    merge_learned_into_reactions,
    save_active_thresholds,
    save_proposals,
    static_defaults,
)
from lib.hermes_thresholds.threshold_learner import (  # noqa: E402
    _propose_efficiency,
    _propose_stop_quality,
    run_learning_cycle,
)
from lib.hermes_thresholds.workflow import (  # noqa: E402
    approve_proposal,
    reject_proposal,
    rollback_thresholds,
    threshold_status,
)


def _synthetic_series(n: int = 22) -> list[dict]:
    series = []
    for i in range(n):
        eff = 0.55 if i % 4 else 0.44
        hr = 0.30 if eff < 0.50 else 0.42
        delta = 0.10 if i % 5 == 0 else 0.16
        align = 0.45 if delta < 0.13 else 0.62
        series.append({
            "day": f"2026-06-{i + 1:02d}",
            "resource_efficiency_score": eff,
            "hit_rate_promotions": hr,
            "maturity_composite_score": 58 if hr < 0.35 else 72,
            "avg_realized_r_trades_90d": 0.05 if hr < 0.35 else 0.18,
            "stop_hot_cold_trail_delta": delta,
            "aligned_pct": align,
            "maturity_stop_quality_score": 55 if align < 0.5 else 70,
        })
    return series


class TestThresholdStore(unittest.TestCase):
    def test_static_defaults_has_phase1_thresholds(self):
        defs = static_defaults()
        self.assertIn("efficiency.tighten_threshold", defs)
        self.assertIn("stop_quality.divergence_delta_pp", defs)

    def test_merge_learned_into_reactions(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_thresholds import store as mod
            old = mod.ACTIVE_PATH
            try:
                mod.ACTIVE_PATH = Path(td) / "thresholds.json"
                save_active_thresholds({
                    "version": "thresholds-v1",
                    "thresholds": {
                        "efficiency.tighten_threshold": {
                            "value": 0.47,
                            "approved_at": "2026-07-03T00:00:00+00:00",
                        },
                    },
                    "history": [],
                })
                rc = merge_learned_into_reactions({"efficiency": {"tighten_threshold": 0.50}})
                self.assertEqual(rc["efficiency"]["tighten_threshold"], 0.47)
                self.assertIn("efficiency.tighten_threshold", rc.get("_learned_thresholds_applied", []))
            finally:
                mod.ACTIVE_PATH = old


class TestScoringV2(unittest.TestCase):
    def test_efficiency_composite_has_contributions(self):
        from lib.hermes_thresholds.scoring import score_efficiency_candidate
        meta = score_efficiency_candidate(_synthetic_series(), 0.48, load_threshold_config())
        self.assertIn("metric_contributions", meta)
        self.assertGreater(meta["score"], 0)

    def test_asymmetric_loosen_stricter(self):
        from lib.hermes_thresholds.scoring import passes_asymmetric_bar
        from lib.hermes_thresholds.store import load_threshold_config
        cfg = load_threshold_config()
        self.assertTrue(passes_asymmetric_bar("tighten", 0.003, "medium", cfg))
        self.assertFalse(passes_asymmetric_bar("loosen", 0.003, "medium", cfg))
        self.assertTrue(passes_asymmetric_bar("loosen", 0.006, "high", cfg))


class TestThresholdLearner(unittest.TestCase):
    def test_efficiency_proposal_within_step(self):
        from lib.hermes_thresholds.store import load_threshold_config
        spec = static_defaults()["efficiency.tighten_threshold"]
        cfg = load_threshold_config()
        proposal = _propose_efficiency(_synthetic_series(), spec, 0.50, cfg)
        if proposal:
            self.assertLessEqual(abs(proposal["proposed_value"] - proposal["current_value"]), spec["max_step"] + 0.001)
            self.assertIn("reasoning", proposal)
            self.assertIn("expected_impact", proposal)
            self.assertIn("confidence", proposal.get("evidence", {}))

    def test_stop_quality_proposal_respects_band(self):
        from lib.hermes_thresholds.store import load_threshold_config
        spec = static_defaults()["stop_quality.divergence_delta_pp"]
        proposal = _propose_stop_quality(_synthetic_series(), spec, 0.13, load_threshold_config())
        if proposal:
            band = spec["safe_band"]
            self.assertGreaterEqual(proposal["proposed_value"], band["min"])
            self.assertLessEqual(proposal["proposed_value"], band["max"])

    def test_learning_cycle_insufficient_history(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_outcome_bus import bus as bus_mod
            old_hist = bus_mod.HISTORY_DIR
            old_bus = bus_mod.OUTCOME_BUS_PATH
            try:
                bus_mod.HISTORY_DIR = Path(td) / "history"
                bus_mod.OUTCOME_BUS_PATH = Path(td) / "bus.json"
                bus_mod.HISTORY_DIR.mkdir()
                result = run_learning_cycle(apply_proposals=False)
                self.assertFalse(result["ok"])
                self.assertEqual(result["reason"], "insufficient_history")
            finally:
                bus_mod.HISTORY_DIR = old_hist
                bus_mod.OUTCOME_BUS_PATH = old_bus


class TestThresholdStatusFields(unittest.TestCase):
    def test_pending_summary_with_proposals(self):
        from lib.hermes_thresholds.workflow import _pending_summary_text

        pending = [
            {
                "threshold_id": "efficiency.tighten_threshold",
                "current_value": 0.50,
                "proposed_value": 0.47,
            },
            {
                "threshold_id": "stop_quality.divergence_delta_pp",
                "current_value": 0.13,
                "proposed_value": 0.11,
            },
        ]
        summary = _pending_summary_text(pending)
        self.assertIn("2 proposals pending review", summary)
        self.assertIn("Efficiency -0.03", summary)
        self.assertIn("Stop Quality Divergence -2pp", summary)


class TestThresholdApproveRejectSafety(unittest.TestCase):
    def test_already_processed_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_thresholds import store as mod
            old_prop = mod.PROPOSALS_PATH
            try:
                mod.PROPOSALS_PATH = Path(td) / "proposals.json"
                save_proposals({
                    "version": "proposals-v1",
                    "pending": [],
                    "decided": [{
                        "id": "tp_done123",
                        "threshold_id": "efficiency.tighten_threshold",
                        "status": "rejected",
                    }],
                })
                result = reject_proposal("tp_done123", reason="again")
                self.assertFalse(result["ok"])
                self.assertEqual(result["reason"], "already_processed")
            finally:
                mod.PROPOSALS_PATH = old_prop

    def test_review_mode_blocks_without_force_apply(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_thresholds import store as mod
            old_active = mod.ACTIVE_PATH
            old_prop = mod.PROPOSALS_PATH
            old_cfg = mod.CFG_PATH
            try:
                mod.ACTIVE_PATH = Path(td) / "active.json"
                mod.PROPOSALS_PATH = Path(td) / "proposals.json"
                cfg_path = Path(td) / "hermes_thresholds.yaml"
                cfg_path.write_text(
                    "learning:\n  enabled: true\n  review_mode: true\n"
                    "thresholds:\n  efficiency.tighten_threshold:\n"
                    "    static_default: 0.50\n    safe_band: {min: 0.42, max: 0.58}\n"
                    "    max_step: 0.03\n    path: [efficiency, tighten_threshold]\n",
                    encoding="utf-8",
                )
                mod.CFG_PATH = cfg_path
                pid = "tp_review01"
                save_proposals({
                    "version": "proposals-v1",
                    "pending": [{
                        "id": pid,
                        "threshold_id": "efficiency.tighten_threshold",
                        "proposed_value": 0.47,
                        "current_value": 0.50,
                        "reasoning": "test",
                        "status": "pending",
                    }],
                    "decided": [],
                })
                logged = approve_proposal(pid, approved_by="test", force_apply=False)
                self.assertTrue(logged["ok"])
                self.assertFalse(logged["applied"])
                self.assertEqual(get_active_value("efficiency.tighten_threshold"), 0.50)
                save_proposals({
                    "version": "proposals-v1",
                    "pending": [{
                        "id": "tp_review02",
                        "threshold_id": "efficiency.tighten_threshold",
                        "proposed_value": 0.47,
                        "current_value": 0.50,
                        "reasoning": "test2",
                        "status": "pending",
                    }],
                    "decided": [],
                })
                applied = approve_proposal("tp_review02", approved_by="test", force_apply=True)
                self.assertTrue(applied["ok"])
                self.assertTrue(applied["applied"])
                self.assertEqual(get_active_value("efficiency.tighten_threshold"), 0.47)
            finally:
                mod.ACTIVE_PATH = old_active
                mod.PROPOSALS_PATH = old_prop
                mod.CFG_PATH = old_cfg


class TestThresholdWorkflow(unittest.TestCase):
    def test_approve_reject_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_thresholds import store as mod
            old_active = mod.ACTIVE_PATH
            old_prop = mod.PROPOSALS_PATH
            old_audit = mod.AUDIT_PATH
            try:
                mod.ACTIVE_PATH = Path(td) / "active.json"
                mod.PROPOSALS_PATH = Path(td) / "proposals.json"
                mod.AUDIT_PATH = Path(td) / "audit.jsonl"

                pid = "tp_test12345"
                save_proposals({
                    "version": "proposals-v1",
                    "pending": [{
                        "id": pid,
                        "threshold_id": "efficiency.tighten_threshold",
                        "proposed_value": 0.47,
                        "current_value": 0.50,
                        "reasoning": "test",
                    }],
                    "decided": [],
                })

                approved = approve_proposal(pid, approved_by="test")
                self.assertTrue(approved["ok"])
                self.assertEqual(approved["to"], 0.47)
                self.assertEqual(get_active_value("efficiency.tighten_threshold"), 0.47)

                status = threshold_status()
                self.assertEqual(status["pending_count"], 0)
                self.assertTrue(status["thresholds"][0]["is_learned"])
                self.assertIn("history_days", status)
                self.assertIn("learning_ready", status)
                self.assertIn("pending_summary", status)
                self.assertEqual(status["pending_summary"], "No pending adjustments")
                self.assertIn("cli_commands", status)

                rolled = rollback_thresholds(approved_by="test")
                self.assertTrue(rolled["ok"])
                self.assertEqual(get_active_value("efficiency.tighten_threshold"), 0.50)

                save_proposals({
                    "version": "proposals-v1",
                    "pending": [{"id": "tp_reject1", "threshold_id": "efficiency.tighten_threshold",
                                 "proposed_value": 0.45, "current_value": 0.50, "reasoning": "x"}],
                    "decided": [],
                })
                rejected = reject_proposal("tp_reject1", reason="test_reject")
                self.assertTrue(rejected["ok"])
            finally:
                mod.ACTIVE_PATH = old_active
                mod.PROPOSALS_PATH = old_prop
                mod.AUDIT_PATH = old_audit


class TestEvaluationEngine(unittest.TestCase):
    def test_evaluate_synthetic_change(self):
        from lib.hermes_thresholds.evaluation_engine import evaluate_change
        from lib.hermes_thresholds.store import load_threshold_config
        series = []
        for i in range(30):
            day = f"2026-06-{i + 1:02d}"
            after = i >= 15
            series.append({
                "day": day,
                "hit_rate_promotions": 0.42 if after else 0.35,
                "maturity_composite_score": 75 if after else 65,
                "resource_efficiency_score": 0.62,
                "avg_realized_r_trades_90d": 0.15 if after else 0.08,
                "stop_hot_cold_trail_delta": 0.15,
                "aligned_pct": 0.6,
                "maturity_stop_quality_score": 70,
            })
        change = {
            "threshold_id": "efficiency.tighten_threshold",
            "at": "2026-06-15T12:00:00+00:00",
            "from": 0.50,
            "to": 0.47,
            "action": "approved",
        }
        ev = evaluate_change(change, series, load_threshold_config())
        self.assertIsNotNone(ev)
        self.assertIn(ev["verdict"], ("helped", "neutral", "hurt", "insufficient_data"))
        self.assertIn(ev["recommendation"], ("keep", "monitor", "revert", "needs_more_data"))

    def test_evaluation_cycle_persists(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_thresholds import evaluation_store as es
            from lib.hermes_thresholds import store as st
            old_eval = es.EVALUATIONS_PATH
            old_active = st.ACTIVE_PATH
            try:
                es.EVALUATIONS_PATH = Path(td) / "evals.json"
                st.ACTIVE_PATH = Path(td) / "active.json"
                save_active_thresholds({
                    "version": "thresholds-v1",
                    "thresholds": {},
                    "history": [{
                        "threshold_id": "efficiency.tighten_threshold",
                        "at": "2026-05-01T00:00:00+00:00",
                        "from": 0.50,
                        "to": 0.47,
                        "action": "approved",
                    }],
                })
                from lib.hermes_thresholds.evaluation_engine import run_evaluation_cycle
                result = run_evaluation_cycle(lookback_days=60)
                self.assertTrue(result["ok"])
            finally:
                es.EVALUATIONS_PATH = old_eval
                st.ACTIVE_PATH = old_active


class TestGovernorIntegration(unittest.TestCase):
    def test_reactions_config_merges_learned(self):
        with tempfile.TemporaryDirectory() as td:
            from lib.hermes_thresholds import store as tmod
            from lib.hermes_scope_governor import reactions as rmod
            old = tmod.ACTIVE_PATH
            try:
                tmod.ACTIVE_PATH = Path(td) / "thresholds.json"
                save_active_thresholds({
                    "version": "thresholds-v1",
                    "thresholds": {
                        "stop_quality.divergence_delta_pp": {"value": 0.15, "approved_at": "2026-07-03"},
                    },
                    "history": [],
                })
                cfg = rmod.load_reactions_config({})
                self.assertEqual(cfg["stop_quality"]["divergence_delta_pp"], 0.15)
            finally:
                tmod.ACTIVE_PATH = old


if __name__ == "__main__":
    unittest.main()