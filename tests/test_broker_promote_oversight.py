#!/usr/bin/env python3
"""Tests for broker promote AI oversight gates."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import broker_promote_oversight as bpo


class TestBrokerPromoteOversight(unittest.TestCase):
    def test_blocks_pending_agents(self):
        snap = {
            "agents": {"required": list(bpo.REQUIRED_AGENTS), "pending": ["maria", "risk_agent"], "reviews": []},
            "local_llm": {"status": "missing"},
            "cloud_review": {"status": "not_run"},
            "lanes_available": {"grok": True, "chatgpt": True},
        }
        with patch.object(bpo, "get_oversight_snapshot", return_value=snap):
            ev = bpo.evaluate_oversight(1)
        self.assertEqual(ev["status"], "BLOCK")
        self.assertFalse(ev["allowed"])
        self.assertTrue(any("incomplete" in v for v in ev["violations"]))

    def test_blocks_agent_block_vote(self):
        snap = {
            "agents": {
                "required": list(bpo.REQUIRED_AGENTS),
                "pending": [],
                "reviews": [{"agent": "risk_agent", "vote": "BLOCK", "status": "reviewed"}],
            },
            "local_llm": {"status": "complete"},
            "cloud_review": {"status": "agree", "consensus": {"verdict": "AGREE", "lanes_ok": 2}},
            "lanes_available": {},
        }
        with patch.object(bpo, "get_oversight_snapshot", return_value=snap):
            ev = bpo.evaluate_oversight(1)
        self.assertEqual(ev["status"], "BLOCK")
        self.assertTrue(any("BLOCK" in v for v in ev["violations"]))

    def test_blocks_cloud_disagree(self):
        snap = {
            "agents": {"required": list(bpo.REQUIRED_AGENTS), "pending": [], "reviews": []},
            "local_llm": {"status": "complete"},
            "cloud_review": {"status": "disagree", "consensus": {"verdict": "DISAGREE", "lanes_ok": 2}},
            "lanes_available": {},
        }
        with patch.object(bpo, "get_oversight_snapshot", return_value=snap):
            ev = bpo.evaluate_oversight(1)
        self.assertEqual(ev["status"], "BLOCK")
        self.assertTrue(any("DISAGREE" in v for v in ev["violations"]))

    def test_warns_when_cloud_not_run(self):
        snap = {
            "agents": {"required": list(bpo.REQUIRED_AGENTS), "pending": [], "reviews": [
                {"agent": "maria", "vote": "APPROVE_TEST", "status": "reviewed"},
                {"agent": "risk_agent", "vote": "APPROVE_TEST", "status": "reviewed"},
                {"agent": "steph", "vote": "APPROVE_TEST", "status": "reviewed"},
            ]},
            "local_llm": {"status": "complete"},
            "cloud_review": {"status": "not_run"},
            "lanes_available": {"grok": True, "chatgpt": False},
        }
        with patch.object(bpo, "get_oversight_snapshot", return_value=snap):
            ev = bpo.evaluate_oversight(1)
        self.assertEqual(ev["status"], "WARN")
        self.assertTrue(ev["allowed"])
        self.assertTrue(any("Cloud oversight" in w for w in ev["warnings"]))

    def test_merge_downgrades_to_block(self):
        sizing = {"status": "PASS", "allowed": True, "violations": []}
        oversight = {"status": "BLOCK", "allowed": False, "violations": ["Agent reviews incomplete"]}
        merged = bpo.merge_evaluation_with_oversight(sizing, oversight)
        self.assertEqual(merged["status"], "BLOCK")
        self.assertFalse(merged["allowed"])
        self.assertIn("oversight", merged)

    def test_merge_warn_on_pass_sizing(self):
        sizing = {"status": "PASS", "allowed": True, "violations": []}
        oversight = {"status": "WARN", "allowed": True, "warnings": ["Cloud not run"]}
        merged = bpo.merge_evaluation_with_oversight(sizing, oversight)
        self.assertEqual(merged["status"], "WARN")
        self.assertTrue(merged["allowed"])

    def test_diligence_plan_has_six_stages(self):
        snap = {
            "agents": {"required": list(bpo.REQUIRED_AGENTS), "pending": ["maria"], "reviews": []},
            "local_llm": {"status": "queued"},
            "cloud_review": {"status": "not_run"},
            "lanes_available": {"grok": True, "chatgpt": True},
        }
        intel_row = {"intel_readiness": 80, "critic_verdict": "CONFIRM"}
        intel_dd = {"ok": True, "violations": [], "warnings": ["Thin coverage"], "analyst_coverage": "thin"}
        oversight = {"status": "BLOCK", "allowed": False, "violations": ["Agent reviews incomplete"], "promote_ready": False}
        stages = bpo.build_promote_diligence_stages(
            1, snap=snap, intel_row=intel_row, intel_dd=intel_dd, oversight=oversight,
        )
        self.assertEqual(len(stages), 6)
        self.assertEqual(stages[0]["id"], "enrich")
        self.assertEqual(stages[1]["status"], "PENDING")
        self.assertEqual(stages[5]["id"], "broker")

    def test_next_action_from_stages(self):
        stages = [
            {"label": "Enrich", "status": "PASS"},
            {"label": "Agents", "status": "PENDING", "action": "Queue agent reviews"},
        ]
        self.assertEqual(bpo._next_action_from_stages(stages), "Queue agent reviews")

    def test_warns_when_cloud_running(self):
        snap = {
            "agents": {"required": list(bpo.REQUIRED_AGENTS), "pending": [], "reviews": []},
            "local_llm": {"status": "complete"},
            "cloud_review": {"status": "running", "auto_queued": True},
            "lanes_available": {"grok": True, "chatgpt": True},
        }
        with patch.object(bpo, "get_oversight_snapshot", return_value=snap):
            ev = bpo.evaluate_oversight(1)
        self.assertEqual(ev["status"], "WARN")
        self.assertTrue(any("running" in w.lower() for w in ev["warnings"]))

    def test_needs_cloud_when_thesis_ready(self):
        with patch.object(bpo, "AUTO_CLOUD_OVERSIGHT", True), \
             patch.object(bpo, "_fetch_cached_cloud_review", return_value=None), \
             patch.object(bpo, "_is_cloud_inflight", return_value=False), \
             patch.object(bpo, "_lane_availability", return_value={"grok": True, "chatgpt": False}), \
             patch.object(bpo, "_fetch_local_llm", return_value={"status": "complete", "thesis": "Buy CRMT on momentum"}):
            self.assertTrue(bpo.needs_cloud_oversight(282))

    def test_skips_cloud_when_cached(self):
        with patch.object(bpo, "AUTO_CLOUD_OVERSIGHT", True), \
             patch.object(bpo, "_fetch_cached_cloud_review", return_value={"status": "agree"}):
            self.assertFalse(bpo.needs_cloud_oversight(282))

    def test_intel_diligence_avoids_oversight_recursion(self):
        """evaluate_intel_diligence must not re-enter evaluate_oversight via get_intel_packet."""
        import broker_proposal_intel as bpi

        with patch.object(bpi, "get_intel_packet") as mock_pkt:
            mock_pkt.return_value = {
                "ok": True,
                "catalyst": {"text": "earnings", "verified": True, "critic_verdict": "CONFIRM"},
                "analyst": {"quality": {"warnings": [], "coverage": "adequate"}},
                "intel_readiness": 92.0,
            }
            bpo.evaluate_intel_diligence(1)
        mock_pkt.assert_called_once_with(1, include_oversight=False)


if __name__ == "__main__":
    unittest.main()