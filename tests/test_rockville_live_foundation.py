#!/usr/bin/env python3
"""Rockville multi-symbol live foundation tests (no provider calls)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class TestLiveProjection(unittest.TestCase):
    def test_priority_is_live_multi_symbol(self):
        from lib.rockville.live_projection import build_live_cards, DEFAULT_PRIORITY_SYMBOLS
        out = build_live_cards()
        self.assertTrue(out.get("ok"))
        self.assertFalse(out.get("fixture_injected"))
        self.assertEqual(out.get("source"), "live_decision_packets")
        cards = out.get("cards") or []
        self.assertGreaterEqual(len(cards), 4)
        syms = {c["symbol"] for c in cards}
        for s in ("FTH", "NUAI", "AXTI", "SWBI"):
            self.assertIn(s, syms, msg=f"missing {s}")
        # no fixture flag
        for c in cards:
            self.assertFalse(c.get("fixture"))
            self.assertTrue(c.get("live") or c.get("missing_components"))

    def test_fth_identity_and_fail_closed(self):
        from lib.rockville.live_projection import build_live_symbol
        out = build_live_symbol("FTH")
        self.assertTrue(out.get("ok"))
        self.assertIn("Faeth", out.get("company") or "")
        self.assertNotIn("Fate Therapeutics", out.get("company") or "")
        dec = out.get("decision") or {}
        self.assertEqual(dec.get("primary_state"), "DETERMINISTIC_FAIL")
        self.assertFalse(dec.get("proposal_allowed"))
        self.assertFalse(dec.get("current_mechanics_visible"))
        self.assertIsNone(dec.get("current_mechanics"))
        stages = out.get("verification_stages") or dec.get("verification_stages") or {}
        self.assertEqual(stages.get("reconciliation_status"), "FAIL_CLOSED")
        # Quality stage should not be NOT_RUN when fail is quality-driven
        self.assertNotEqual(stages.get("quality_admission_status"), "NOT_RUN")

    def test_fail_symbols_fail_closed(self):
        from lib.rockville.live_projection import build_live_symbol
        for sym in ("FTH", "NUAI", "AXTI", "SWBI"):
            out = build_live_symbol(sym)
            if not out.get("ok"):
                self.skipTest(f"{sym} no packet")
            dec = out["decision"]
            st = dec["primary_state"]
            if st in ("DETERMINISTIC_FAIL", "BLOCKED", "STALE", "AVOID", "DATA_UNAVAILABLE"):
                self.assertFalse(dec["proposal_allowed"], sym)
                self.assertFalse(dec["current_mechanics_visible"], sym)
                vis = dec.get("visibility") or {}
                for k, v in vis.items():
                    self.assertFalse(v, msg=f"{sym} {k}")

    def test_held_symbol_present(self):
        from lib.rockville.live_projection import build_live_cards
        out = build_live_cards()
        held = [c for c in out.get("cards") or [] if c.get("held")]
        # PFLT is in default set and is held on this host
        self.assertTrue(any(c["symbol"] == "PFLT" for c in out.get("cards") or []) or held)

    def test_no_env_password_parser_in_live_module(self):
        src = (ROOT / "scripts/lib/rockville/live_projection.py").read_text()
        self.assertNotIn("DB_PASSWORD=", src)
        self.assertIn("db_adapter", src)
        api = (ROOT / "scripts/api_v3_watch_rockville.py").read_text()
        self.assertNotIn("DB_PASSWORD=", api)


class TestOperatorPresentationFailClosed(unittest.TestCase):
    def test_presentation_header(self):
        import operator_presentation as op
        import shadow_decision_service as svc
        rb = svc.readback("FTH")
        self.assertTrue(rb.get("ok"))
        pres = op.build(rb["packet"], None)
        self.assertEqual(pres["header_state"], "DETERMINISTIC FAIL")
        self.assertFalse(pres["display_current_mechanics"])
        for k, v in (pres.get("mechanics") or {}).items():
            self.assertIsNone(v)


class TestSanitizeMechanicsDomContract(unittest.TestCase):
    def test_pattern_tooltip_stripped_in_source(self):
        src = (ROOT / "apps/command-center-v3/src/components/DecisionPacketBand.tsx").read_text()
        self.assertIn("sanitizeTechEvidence", src)
        self.assertIn("failClosed", src)


if __name__ == "__main__":
    unittest.main()
