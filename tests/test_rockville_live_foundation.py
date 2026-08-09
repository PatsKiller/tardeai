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

    def test_fixture_fth_is_exact_deterministic_fail(self):
        """Frozen regression fixture — exact DETERMINISTIC_FAIL (not mutable live)."""
        from lib.rockville.decision_projection import (
            project_watch_decision,
            assert_no_mechanics_on_invalid,
        )
        from lib.rockville.live_projection import _verification_stages
        fx_path = ROOT / "tests" / "fixtures" / "rockville" / "ROCKVILLE_FTH_REGRESSION_FIXTURE.json"
        fx = json.loads(fx_path.read_text(encoding="utf-8"))
        dec = project_watch_decision(fx["packet"], fx["action_policy"], symbol="FTH")
        self.assertEqual(dec.get("primary_state"), "DETERMINISTIC_FAIL")
        self.assertFalse(dec.get("proposal_allowed"))
        self.assertFalse(dec.get("current_mechanics_visible"))
        self.assertIsNone(dec.get("current_mechanics"))
        assert_no_mechanics_on_invalid(dec)
        rec = ((fx["packet"].get("ticket_review") or {}).get("reconciled") or {})
        self.assertEqual(rec.get("state"), "DETERMINISTIC_FAIL")
        self.assertFalse(rec.get("proposal_allowed"))
        stages = _verification_stages(fx["packet"])
        self.assertEqual(stages.get("reconciliation_status"), "FAIL_CLOSED")

    def test_live_fth_invariants_state_independent(self):
        """Live FTH may be WAIT or DETERMINISTIC_FAIL — assert invariants, not a frozen state."""
        from lib.rockville.live_projection import build_live_symbol
        out = build_live_symbol("FTH")
        self.assertTrue(out.get("ok"))
        self.assertIn("Faeth", out.get("company") or "")
        self.assertNotIn("Fate Therapeutics", out.get("company") or "")
        self.assertNotIn("Fate ", (out.get("company") or ""))
        self.assertFalse(out.get("fixture"))

        # Quote provenance complete or explicit DATA_UNAVAILABLE
        fresh = out.get("freshness_state")
        if fresh == "DATA_UNAVAILABLE" or out.get("last") is None:
            self.assertEqual(fresh, "DATA_UNAVAILABLE")
            self.assertIsNone(out.get("last"))
        else:
            self.assertIsNotNone(out.get("quote_id"))
            self.assertIsNotNone(out.get("source_record_id"))
            self.assertIsNotNone(out.get("price_as_of"))
            self.assertIsNotNone(out.get("price_source"))
            self.assertIsNotNone(out.get("market_session"))

        dec = out.get("decision") or {}
        st = dec.get("primary_state")
        self.assertIsNotNone(st)

        non_ready_no_proposal = {
            "WAIT", "DETERMINISTIC_FAIL", "BLOCKED", "STALE",
            "DATA_UNAVAILABLE", "AVOID", "REVIEW_PENDING",
        }
        if st in non_ready_no_proposal:
            self.assertFalse(dec.get("proposal_allowed"), msg=f"live FTH {st}")
            self.assertFalse(dec.get("current_mechanics_visible"), msg=f"live FTH {st}")
            self.assertIsNone(dec.get("current_mechanics"))

        if st != "READY":
            self.assertFalse(dec.get("current_mechanics_visible"), msg=f"non-READY {st}")
            if dec.get("current_mechanics") is not None and st != "MANAGING":
                # Only READY may show executable current mechanics
                self.assertFalse(dec.get("current_mechanics_visible"))

        stages = out.get("verification_stages") or dec.get("verification_stages") or {}
        if st == "DETERMINISTIC_FAIL":
            self.assertEqual(stages.get("reconciliation_status"), "FAIL_CLOSED")
            self.assertFalse(dec.get("proposal_allowed"))
            self.assertFalse(dec.get("current_mechanics_visible"))
            self.assertIsNone(dec.get("current_mechanics"))

        if st == "WAIT":
            self.assertFalse(dec.get("proposal_allowed"))
            self.assertFalse(dec.get("current_mechanics_visible"))
            self.assertIsNone(dec.get("current_mechanics"))
            # Only a non-executable wait contract may appear
            wc = dec.get("wait_contract")
            if wc is not None:
                self.assertIsInstance(wc, dict)
                # wait contract must not look like executable ticket mechanics
                for banned in ("entry_zone", "stop_price", "risk_reward", "targets"):
                    if banned in wc and wc.get(banned) is not None:
                        # tolerate presence only if clearly non-executable label
                        self.assertTrue(
                            wc.get("non_executable") or wc.get("label") or wc.get("what_must_happen"),
                            msg="WAIT contract must be non-executable",
                        )

    def test_fail_symbols_fail_closed(self):
        from lib.rockville.live_projection import build_live_symbol
        for sym in ("FTH", "NUAI", "AXTI", "SWBI"):
            out = build_live_symbol(sym)
            if not out.get("ok"):
                self.skipTest(f"{sym} no packet")
            dec = out["decision"]
            st = dec["primary_state"]
            if st in ("DETERMINISTIC_FAIL", "BLOCKED", "STALE", "AVOID", "DATA_UNAVAILABLE", "WAIT"):
                self.assertFalse(dec["proposal_allowed"], sym)
                self.assertFalse(dec["current_mechanics_visible"], sym)
                if st != "READY":
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
        """Full canonical quote contract equal on legacy v2 items AND Rockville v3 symbol API.

        Does NOT compare Rockville to a second call of the same helper — that is
        circular. Both HTTP surfaces must expose the complete artifact.
        """
        import urllib.request
        from lib.rockville.live_projection import build_live_cards

        cards = {c["symbol"]: c for c in (build_live_cards().get("cards") or [])}
        contract_keys = (
            "last", "day_change_pct", "price_as_of", "price_source",
            "quote_id", "source_record_id", "market_session",
            "freshness_state", "market_state",
        )
        for sym in ("FTH", "NUAI", "AXTI", "SWBI", "CECO", "PFLT"):
            if sym not in cards:
                continue
            # Legacy Watch API
            raw_v2 = urllib.request.urlopen(
                f"http://127.0.0.1:7777/api/v2/watchlist/items?symbol={sym}", timeout=45
            ).read()
            body_v2 = json.loads(raw_v2)
            items = (body_v2.get("data") or body_v2).get("items") or []
            self.assertTrue(items, msg=f"{sym} no v2 item")
            it = items[0]

            # Rockville v3 symbol API (HTTP — not helper re-call)
            raw_v3 = urllib.request.urlopen(
                f"http://127.0.0.1:7777/api/v3/watch/symbols/{sym}", timeout=45
            ).read()
            v3 = json.loads(raw_v3)
            if "data" in v3 and isinstance(v3["data"], dict):
                v3 = v3["data"]

            c = cards[sym]

            # Full provenance required on both HTTP surfaces
            for surface, row in (("v2", it), ("v3", v3), ("card", c)):
                self.assertIsNotNone(row.get("quote_id") if surface != "v2" else it.get("quote_id"),
                                     msg=f"{sym} {surface} quote_id")
                self.assertIsNotNone(
                    (row.get("source_record_id") if surface != "v2" else it.get("source_record_id")),
                    msg=f"{sym} {surface} source_record_id",
                )
                self.assertIsNotNone(
                    (row.get("market_session") if surface != "v2" else it.get("market_session")),
                    msg=f"{sym} {surface} market_session",
                )
                self.assertIsNotNone(
                    (row.get("freshness_state") if surface != "v2" else it.get("freshness_state")),
                    msg=f"{sym} {surface} freshness_state",
                )

            # Normalize v2 price → last for comparison
            v2_last = it.get("price")
            v2_chg = it.get("change_pct")
            v2_asof = it.get("price_as_of")

            self.assertIsNotNone(c.get("last"), msg=f"{sym} card last")
            self.assertIsNotNone(c.get("price_as_of"), msg=f"{sym} card as_of")
            self.assertEqual(float(c["last"]), float(v2_last), msg=f"{sym} last v2 vs card")
            self.assertEqual(float(v3["last"]), float(v2_last), msg=f"{sym} last v3 vs v2")

            if v2_chg is not None and c.get("day_change_pct") is not None:
                self.assertAlmostEqual(float(c["day_change_pct"]), float(v2_chg), places=4, msg=f"{sym} chg card/v2")
            if v3.get("day_change_pct") is not None and v2_chg is not None:
                self.assertAlmostEqual(float(v3["day_change_pct"]), float(v2_chg), places=4, msg=f"{sym} chg v3/v2")

            self.assertEqual(c.get("price_source"), it.get("price_source"), msg=f"{sym} source card/v2")
            self.assertEqual(v3.get("price_source"), it.get("price_source"), msg=f"{sym} source v3/v2")

            if v2_asof and c.get("price_as_of"):
                self.assertEqual(str(c["price_as_of"])[:19], str(v2_asof)[:19], msg=f"{sym} asof card/v2")
            if v2_asof and v3.get("price_as_of"):
                self.assertEqual(str(v3["price_as_of"])[:19], str(v2_asof)[:19], msg=f"{sym} asof v3/v2")

            for key in ("quote_id", "source_record_id", "market_session", "freshness_state", "market_state"):
                self.assertEqual(c.get(key), it.get(key), msg=f"{sym} {key} card vs v2")
                self.assertEqual(v3.get(key), it.get(key), msg=f"{sym} {key} v3 vs v2")

            if c.get("price_source") == "enrichment":
                self.assertIsInstance(c.get("quote_id"), str)
                self.assertTrue(str(c.get("quote_id")).startswith("enrichment:"))
                self.assertNotIn("mq_id_unused", c)
                self.assertNotIn("mq_id_unused", it)

            co = c.get("company") or ""
            self.assertNotIn(" provides ", co)
            self.assertNotIn(" is a Private", co)
            self.assertLessEqual(len(co), 80)

    def test_watchcard_source_has_provenance_dom(self):
        src = (ROOT / "apps/command-center-v3/src/components/rockville/WatchCardV2.tsx").read_text()
        for attr in (
            "data-quote-id",
            "data-source-record-id",
            "data-market-session",
            "data-freshness-state",
            "data-market-state",
        ):
            self.assertIn(attr, src)

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
    def test_presentation_header_fixture_fail(self):
        """Fixture packet → DETERMINISTIC FAIL header (not mutable live state)."""
        import operator_presentation as op
        fx_path = ROOT / "tests" / "fixtures" / "rockville" / "ROCKVILLE_FTH_REGRESSION_FIXTURE.json"
        fx = json.loads(fx_path.read_text(encoding="utf-8"))
        pres = op.build(fx["packet"], fx.get("action_policy"))
        self.assertEqual(pres["header_state"], "DETERMINISTIC FAIL")
        self.assertFalse(pres["display_current_mechanics"])
        for k, v in (pres.get("mechanics") or {}).items():
            self.assertIsNone(v)

    def test_presentation_live_nonready_hides_mechanics(self):
        """Live packet: whatever state, non-READY must hide current mechanics."""
        import operator_presentation as op
        import shadow_decision_service as svc
        rb = svc.readback("FTH")
        self.assertTrue(rb.get("ok"))
        pres = op.build(rb["packet"], None)
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
