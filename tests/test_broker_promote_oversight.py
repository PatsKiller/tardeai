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


if __name__ == "__main__":
    unittest.main()