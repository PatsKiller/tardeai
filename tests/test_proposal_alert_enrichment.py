#!/usr/bin/env python3
"""Tests for proposal Telegram alert enrichment (card-parity risk surface)."""
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestHighRiskSurface(unittest.TestCase):

    def test_extreme_rvol_unverified_catalyst(self):
        from proposal_alert_enrichment import assess_high_risk_surface
        out = assess_high_risk_surface(
            {"rvol": 14, "gap_pct": 2.8},
            {"catalyst": {"verified": False, "rvol": 14}, "technicals": {"rvol": 14}},
        )
        self.assertTrue(out["high_risk"])
        self.assertIn("MEME", out["high_risk_label"])
        self.assertIn("RVOL 14", out["high_risk_reasons"])
        self.assertIn("unverified catalyst", out["high_risk_reasons"])

    def test_meme_keyword_in_catalyst(self):
        from proposal_alert_enrichment import assess_high_risk_surface
        out = assess_high_risk_surface(
            {},
            {"catalyst": {"text": "Reddit WSB squeeze chatter", "verified": True}},
        )
        self.assertTrue(out["high_risk"])
        self.assertIn("meme-driven", out["high_risk_reasons"])

    def test_normal_dividend_not_flagged(self):
        from proposal_alert_enrichment import assess_high_risk_surface
        out = assess_high_risk_surface(
            {"rvol": 1.2, "catalyst_verified": True},
            {"catalyst": {"text": "Dividend increase", "verified": True}, "technicals": {"rvol": 1.2}},
        )
        self.assertFalse(out["high_risk"])


class TestTelegramFormat(unittest.TestCase):

    def test_message_includes_risk_and_gates(self):
        from telegram_proposal_alert_policy import build_proposal_alert_packet, format_telegram_message
        pkt = build_proposal_alert_packet({
            "id": 2294, "symbol": "AVXX", "strategy_id": "dividend_growth_compounder",
            "status": "PENDING", "proposed_account": "tradeai_automated",
            "proposed_entry": 4.8, "proposed_stop": 4.31, "proposed_target1": 9.23,
            "proposed_rr": 9.04, "proposed_shares": 306, "rvol": 14,
            "operator_verdict": "BLOCKED",
            "approval_blockers": [{"reason": "spread too wide"}],
            "execution_readiness": {"readiness_state": "BLOCKED"},
        })
        pkt.update({
            "high_risk_label": "MEME / HIGH-RISK SPECULATION",
            "high_risk_reasons": "RVOL 14× · unverified catalyst",
            "oversight_summary": "oversight BLOCK · 3 gates · agents pending: maria",
            "company_description": "Defiance Daily Target 2x Long AVAV ETF",
            "rvol": 14.0,
        })
        msg = format_telegram_message(pkt)
        self.assertIn("MEME / HIGH-RISK", msg)
        self.assertIn("RVOL 14", msg)
        self.assertIn("Gates:", msg)
        self.assertIn("Defiance", msg)
        self.assertNotIn("Approve", msg)  # keyboard tested separately

    def test_keyboard_no_approve_when_blocked(self):
        from telegram_proposal_alert_policy import build_proposal_inline_keyboard
        kb = build_proposal_inline_keyboard({"proposal_id": 99, "approval_allowed": False})
        flat = str(kb)
        self.assertNotIn("ptapprove", flat)


if __name__ == "__main__":
    unittest.main()