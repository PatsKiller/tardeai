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

    def test_cross_surface_quote_coherence(self):
        """Rockville last/change/as_of/source match watchlist items (canonical CASE overlay)."""
        import urllib.request
        from lib.rockville.live_projection import build_live_cards
        cards = {c["symbol"]: c for c in (build_live_cards().get("cards") or [])}
        for sym in ("FTH", "NUAI", "AXTI", "SWBI", "CECO", "PFLT"):
            if sym not in cards:
                continue
            raw = urllib.request.urlopen(
                f"http://127.0.0.1:7777/api/v2/watchlist/items?symbol={sym}", timeout=45
            ).read()
            it = json.loads(raw)["data"]["items"][0]
            c = cards[sym]
            self.assertIsNotNone(c.get("price_as_of"), msg=f"{sym} missing timestamp")
            self.assertIsNotNone(c.get("last"), msg=f"{sym} missing last")
            self.assertIsNotNone(c.get("quote_id"), msg=f"{sym} missing quote_id")
            self.assertEqual(float(c["last"]), float(it["price"]), msg=f"{sym} last mismatch")
            # change_pct may be float-equal
            if it.get("change_pct") is not None and c.get("day_change_pct") is not None:
                self.assertAlmostEqual(float(c["day_change_pct"]), float(it["change_pct"]), places=4, msg=sym)
            self.assertEqual(c.get("price_source"), it.get("price_source"), msg=sym)
            # timestamps both present and equal when both set
            if it.get("price_as_of") and c.get("price_as_of"):
                self.assertTrue(
                    str(c["price_as_of"])[:19] == str(it["price_as_of"])[:19]
                    or str(c["price_as_of"]).startswith(str(it["price_as_of"])[:19]),
                    msg=f"{sym} as_of {c.get('price_as_of')} vs {it.get('price_as_of')}",
                )
            # company names not full prose
            co = c.get("company") or ""
            self.assertNotIn(" provides ", co)
            self.assertNotIn(" is a Private", co)
            self.assertLessEqual(len(co), 80)

    def test_company_name_canonicalizer(self):
        from lib.rockville.live_projection import _canonical_company_name
        self.assertEqual(
            _canonical_company_name(
                "CECO Environmental Corp. provides critical solutions in industrial air quality",
                "CECO",
            ),
            "CECO Environmental Corp.",
        )
        self.assertEqual(
            _canonical_company_name(
                "PennantPark Floating Rate Capital Ltd. is a Private Debt fund",
                "PFLT",
            ),
            "PennantPark Floating Rate Capital Ltd.",
        )
        self.assertEqual(
            _canonical_company_name("Faeth Therapeutics, Inc., a clinical-stage", "FTH"),
            "Faeth Therapeutics, Inc.",
        )



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
