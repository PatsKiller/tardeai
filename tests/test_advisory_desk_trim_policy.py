"""Phase 4 — TRIM policy: label policy/rule/housekeeping; remnants never book-sold.

READ_ONLY_ADVISORY. These tests assert that a concentration TRIM, a gain TRIM,
and a remnant (sub-threshold weight OR sub-$500) are never presented as the
same call, and that a remnant can never surface as an actionable TRIM/EXIT.
"""
from __future__ import annotations

import unittest

from lib.data_broker.advisory_desk import (
    AdvisoryVerdict,
    _derive_holding_opinion,
)


def _opinion(*, symbol: str, mv: float, pct: float, gain: float, total: float = 1_250_000.0) -> dict:
    return _derive_holding_opinion(
        {
            "symbol": symbol,
            "market_value": mv,
            "portfolio_pct": pct,
            "gain_loss_pct": gain,
            "cost_basis": 1000.0,
            "bucket": "",
        },
        total,
        risk_positions={},
        tax_lots={},
        portfolio_heat_pct=None,
    )


class TestTrimKinds(unittest.TestCase):
    def test_concentration_trim_is_policy(self) -> None:
        o = _opinion(symbol="SCHD", mv=210_000, pct=16.8, gain=8.0)
        self.assertEqual(o["verdict"], AdvisoryVerdict.TRIM)
        self.assertEqual(o["trim_kind"], "policy")
        self.assertFalse(o["housekeeping_flag"])

    def test_gain_trim_is_rule(self) -> None:
        o = _opinion(symbol="V", mv=95_000, pct=7.6, gain=30.0)
        self.assertEqual(o["verdict"], AdvisoryVerdict.TRIM)
        self.assertEqual(o["trim_kind"], "rule")
        self.assertFalse(o["housekeeping_flag"])

    def test_sub_dollar_remnant_is_housekeeping_not_trim(self) -> None:
        # A tiny remnant that also has a large gain must NOT become a book TRIM.
        o = _opinion(symbol="SPCX", mv=400.0, pct=0.4, gain=30.0)
        self.assertEqual(o["verdict"], AdvisoryVerdict.HOLD)
        self.assertEqual(o["trim_kind"], "housekeeping")
        self.assertEqual(o["housekeeping_reason"], "close_out_remnant")
        self.assertTrue(o["housekeeping_flag"])

    def test_sub_weight_remnant_with_loss_is_housekeeping_not_trim(self) -> None:
        # Sub-1% weight above $500 with a material loss is housekeeping, not TRIM.
        o = _opinion(symbol="AMANX", mv=2_000.0, pct=0.4, gain=-20.0)
        self.assertEqual(o["verdict"], AdvisoryVerdict.HOLD)
        self.assertEqual(o["trim_kind"], "housekeeping")
        self.assertEqual(o["housekeeping_reason"], "sub_threshold_weight")
        self.assertTrue(o["housekeeping_flag"])


class TestSynthesisFailClosedOnConflict(unittest.TestCase):
    def _synth(self, rows: list[dict]) -> dict:
        from lib.advisory import advisory_opinion_engine as aoe
        cfg = {"routing": {"lane_preference": [], "bridge": {}}}
        return aoe.generate_desk_synthesis(rows, config=cfg, force=True)

    def test_conflicted_actionable_gets_fail_closed_prefix(self) -> None:
        out = self._synth([
            {
                "symbol": "SCHD",
                "row_class": "holding",
                "verdict": "TRIM",
                "market_value": 210_000,
                "rationale": "concentration",
                "verdict_suppressed": True,
                "evidence_bundle": {"evidence_count": 3, "evidence_gaps": []},
            },
        ])
        self.assertTrue(out.get("data_conflict"))
        self.assertIn("SCHD", out.get("conflicted_symbols") or [])
        self.assertIn("DATA CONFLICT", out.get("text") or "")
        self.assertIn("SCHD", out.get("text") or "")

    def test_unconflicted_actionable_has_no_prefix(self) -> None:
        out = self._synth([
            {
                "symbol": "V",
                "row_class": "holding",
                "verdict": "TRIM",
                "market_value": 95_000,
                "rationale": "large gain",
                "evidence_bundle": {"evidence_count": 3, "evidence_gaps": []},
            },
        ])
        self.assertFalse(out.get("data_conflict"))
        self.assertEqual(out.get("conflicted_symbols") or [], [])
        self.assertNotIn("DATA CONFLICT", out.get("text") or "")


if __name__ == "__main__":
    unittest.main()
