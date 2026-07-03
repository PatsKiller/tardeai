"""Proposal impact narrative for threshold history."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib.hermes_thresholds.proposal_impact import build_impact_narrative  # noqa: E402
from lib.hermes_thresholds.workflow import _enrich_decided_proposals  # noqa: E402


class TestProposalImpactNarrative(unittest.TestCase):
    def test_rejected_has_no_impact(self):
        r = build_impact_narrative(
            threshold_id="efficiency.tighten_threshold",
            status="rejected",
        )
        self.assertIn("rejected", r["narrative"].lower())

    def test_helped_efficiency_narrative(self):
        r = build_impact_narrative(
            threshold_id="efficiency.tighten_threshold",
            status="approved",
            evaluation={
                "verdict": "helped",
                "windows": {"after": {"days": 14}},
                "metrics": {
                    "resource_efficiency_score": {"delta": 0.042},
                    "hit_rate_promotions": {"delta": 0.032},
                },
            },
        )
        self.assertIn("Contributed to improvement", r["narrative"])
        self.assertIn("14d", r["narrative"])
        self.assertIn("efficiency score", r["narrative"])
        self.assertIn("promotion hit rate", r["narrative"])

    def test_enrich_attaches_narrative(self):
        decided = [{
            "id": "tp_abc",
            "threshold_id": "efficiency.tighten_threshold",
            "status": "approved",
            "decided_at": "2026-06-01T12:00:00+00:00",
            "current_value": 0.5,
            "proposed_value": 0.47,
        }]
        evaluations = [{
            "threshold_id": "efficiency.tighten_threshold",
            "proposal_id": "tp_abc",
            "approved_at": "2026-06-01T12:00:00+00:00",
            "verdict": "helped",
            "recommendation": "keep",
            "impact_score": 0.22,
            "windows": {"after": {"days": 14}},
            "metrics": {
                "resource_efficiency_score": {"before": 0.41, "after": 0.45, "delta": 0.04},
                "hit_rate_promotions": {"before": 0.28, "after": 0.31, "delta": 0.03},
            },
        }]
        out = _enrich_decided_proposals(decided, [], evaluations, min_eval_days=14)
        self.assertTrue(out[0].get("impact_narrative"))
        self.assertIn("14d", out[0]["impact_narrative"])
        self.assertEqual(out[0]["evaluation_outcome"]["verdict"], "helped")
        self.assertIn("impact_narrative", out[0]["evaluation_outcome"])


if __name__ == "__main__":
    unittest.main()