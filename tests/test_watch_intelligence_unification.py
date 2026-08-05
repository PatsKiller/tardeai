#!/usr/bin/env python3
"""Watch Intelligence unification — broker + routes + no provider calls."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class TestDataBrokerWatch(unittest.TestCase):
    def test_list_envelope(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence
        out = list_watch_intelligence({"view": "top_ideas", "page_size": 10})
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("provider_calls"), 0)
        self.assertFalse(out.get("paid_flags_enabled"))
        self.assertEqual(out.get("broker_write_authority"), "NONE")
        self.assertIn("snapshot_id", out)
        self.assertIn("data_contract_version", out)
        self.assertIn("source_status", out)
        self.assertIn("counts", out)
        items = out.get("items") or []
        self.assertGreaterEqual(len(items), 1)
        # one card per symbol
        syms = [i.get("symbol") for i in items]
        self.assertEqual(len(syms), len(set(syms)))
        it = items[0]
        self.assertIn("domains", it)
        self.assertIn("SymbolIdentity", it["domains"])
        self.assertIn("CanonicalQuote", it["domains"])
        self.assertIn("StreetConsensus", it["domains"])
        q = it["domains"]["CanonicalQuote"]["last"]
        self.assertIn("value", q)
        self.assertIn("source", q)
        self.assertIn("freshness_state", q)
        self.assertIn("quality_state", q)

    def test_starred_view(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence, _starred_set
        stars = _starred_set()
        out = list_watch_intelligence({"view": "starred", "page_size": 40})
        self.assertEqual(out.get("provider_calls"), 0)
        for it in out.get("items") or []:
            self.assertTrue((it.get("card") or {}).get("starred"), it.get("symbol"))
        if stars:
            self.assertGreaterEqual(len(out.get("items") or []), 1)

    def test_held_view(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence
        out = list_watch_intelligence({"view": "held", "page_size": 40})
        for it in out.get("items") or []:
            c = it.get("card") or {}
            self.assertTrue(c.get("held") or c.get("trade_ai_state") == "MANAGING", c.get("symbol"))

    def test_screener_origin_filter(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence
        out = list_watch_intelligence({"view": "screener_finds", "page_size": 40})
        self.assertEqual(out.get("provider_calls"), 0)
        for it in out.get("items") or []:
            self.assertTrue((it.get("card") or {}).get("screener_origin"), it.get("symbol"))

    def test_street_filter(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence
        out = list_watch_intelligence({"view": "all", "street_rating": "STRONG_BUY", "page_size": 40})
        for it in out.get("items") or []:
            self.assertEqual((it.get("card") or {}).get("street_rating"), "STRONG BUY")

    def test_detail_and_reviews(self):
        from lib.data_broker.watch_intelligence import detail_watch_intelligence, watch_reviews, watch_filters, watch_lists
        d = detail_watch_intelligence("CECO")
        self.assertTrue(d.get("ok"))
        self.assertEqual(d.get("provider_calls"), 0)
        self.assertIn("domains", d.get("item") or {})
        r = watch_reviews("CECO")
        self.assertEqual(r.get("provider_calls"), 0)
        f = watch_filters()
        self.assertIn("views", f)
        self.assertIn("starred", f.get("views") or [])
        lists = watch_lists()
        self.assertEqual(lists.get("provider_calls"), 0)

    def test_no_provider_imports_in_broker(self):
        src = (ROOT / "scripts/lib/data_broker/watch_intelligence.py").read_text().lower()
        for banned in ("openai", "anthropic", "chat.completions", "call_provider"):
            self.assertNotIn(banned, src)

    def test_review_truthfulness_on_cards(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence
        out = list_watch_intelligence({"view": "all", "page_size": 40})
        for it in out.get("items") or []:
            c = it.get("card") or {}
            for key in ("cio_review", "maria_review"):
                rev = c.get(key) or {}
                if rev.get("status") != "COMPLETE":
                    self.assertIn(rev.get("model"), (None,))
                    self.assertIn(rev.get("provider"), (None,))


class TestRoutesAndNav(unittest.TestCase):
    def test_app_routes(self):
        app = (ROOT / "apps/command-center-v3/src/App.tsx").read_text()
        self.assertIn('path="watch"', app)
        self.assertIn("watch/intelligence/:symbol", app)
        self.assertIn("watch/discovery", app)
        self.assertIn("watch-legacy", app)
        self.assertIn('to="/watch?tab=intelligence&view=top_ideas"', app)

    def test_hub_no_legacy_tabs(self):
        hub = (ROOT / "apps/command-center-v3/src/pages/WatchHub.tsx").read_text()
        self.assertIn("WatchIntelligenceUnified", hub)
        self.assertNotIn("'Watchlist'", hub)
        self.assertNotIn("'Screener Finds'", hub)
        self.assertIn("Intelligence", hub)

    def test_unified_uses_broker(self):
        ui = (ROOT / "apps/command-center-v3/src/pages/WatchIntelligenceUnified.tsx").read_text()
        self.assertIn("/api/v3/data-broker/watch-intelligence", ui)
        self.assertIn("data-watch-intelligence-primary", ui)
        self.assertIn("Provider NONE", ui)
        self.assertNotIn("/api/v2/watchlist/items", ui)

    def test_legacy_page_exists(self):
        legacy = (ROOT / "apps/command-center-v3/src/pages/WatchLegacy.tsx").read_text()
        self.assertIn("data-watch-legacy", legacy)
        self.assertIn("ROLLBACK", legacy)

    def test_consumers_doc(self):
        doc = (ROOT / "docs/design/watchlist-intelligence-v3/DATA_BROKER_WATCH_CONSUMERS.md").read_text()
        for name in ("Portfolio", "Re-Entry", "Risk", "Active Trader", "Research", "Agents", "Reports"):
            self.assertIn(name, doc)


class TestCommands(unittest.TestCase):
    def test_star_command_no_provider(self):
        from api_v3_watch_commands import post_refresh_data, post_alert, post_list_membership
        r = post_refresh_data({"symbol": "CECO"})
        self.assertEqual(r.get("provider_calls"), 0)
        self.assertFalse(r.get("broker_write"))
        a = post_alert({"symbol": "CECO"})
        self.assertEqual(a.get("provider_calls"), 0)
        m = post_list_membership({"symbol": "CECO", "label": "test"})
        self.assertEqual(m.get("provider_calls"), 0)


class TestProductionTruthCorrection(unittest.TestCase):
    def test_operator_approved_not_authorization(self):
        from lib.data_broker.watch_domains import authorize_review_artifact
        fake = {
            "status": "COMPLETE",
            "operator_approved": True,
            "process_id": "watchlist_maria_flash_narrative",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "provider_request_id": "req-x",
            "input_hash": "h",
            "artifact_id": "a",
            "artifact_hash": "ah",
            "started_at": "t0",
            "completed_at": "t1",
            "requested_policy": "FAST",
            "executed_policy": "FAST",
            "fallback_used": False,
        }
        ok, reason = authorize_review_artifact(fake)
        self.assertFalse(ok)
        self.assertEqual(reason, "UNVERIFIED_OPERATOR_AUTHORIZATION")

    def test_quarantine_not_complete(self):
        from lib.data_broker.watch_domains import load_review_artifacts
        arts = load_review_artifacts("CECO")
        # Quarantined files must not load as COMPLETE from artifacts dir
        for a in arts.values():
            self.assertNotEqual(a.get("status"), "COMPLETE")

    def test_top_ideas_not_default_priority_only(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence
        from lib.watchlist_intelligence import DEFAULT_PRIORITY
        out = list_watch_intelligence({"view": "top_ideas", "page_size": 20})
        cards = out.get("cards") or []
        self.assertTrue(cards)
        # Must expose rank metadata from dynamic ranker
        self.assertIsNotNone(cards[0].get("rank"))
        self.assertIsNotNone(cards[0].get("rank_version"))
        # Rank scores must exist (dynamic)
        self.assertIsNotNone(cards[0].get("rank_score"))
        # Not merely equal to DEFAULT_PRIORITY ordering without scores
        self.assertTrue(out.get("rank_version") or cards[0].get("rank_version"))

    def test_near_trigger_requires_distance(self):
        from lib.data_broker.watch_domains import near_trigger_eval
        far = near_trigger_eval({
            "trade_ai_state": "WAIT",
            "last": 100,
            "resistance": 150,
            "freshness_state": "CURRENT",
        })
        self.assertFalse(far.get("is_near"))
        near = near_trigger_eval({
            "trade_ai_state": "WAIT",
            "last": 100,
            "resistance": 102,
            "freshness_state": "CURRENT",
        })
        self.assertTrue(near.get("is_near"))
        stale = near_trigger_eval({
            "trade_ai_state": "WAIT",
            "last": 100,
            "resistance": 101,
            "freshness_state": "STALE",
        })
        self.assertFalse(stale.get("is_near"))

    def test_reviewed_today_date_gate(self):
        from lib.data_broker.watch_domains import completed_today
        self.assertFalse(completed_today("2020-01-01T12:00:00+00:00"))
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.assertTrue(completed_today(now))

    def test_snapshot_excludes_generated_at_only(self):
        from lib.data_broker.watch_domains import content_snapshot_id
        items = [{"symbol": "X", "card": {"symbol": "X", "street_rating": "BUY", "last": 1}}]
        a = content_snapshot_id(items, view="all", query={})
        b = content_snapshot_id(items, view="all", query={})
        self.assertEqual(a, b)
        items2 = [{"symbol": "X", "card": {"symbol": "X", "street_rating": "BUY", "last": 2}}]
        c = content_snapshot_id(items2, view="all", query={})
        self.assertNotEqual(a, c)

    def test_quality_not_hardcoded_ok(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence
        out = list_watch_intelligence({"view": "top_ideas", "page_size": 6})
        self.assertIn(out.get("data_quality_status"), ("COMPLETE", "PARTIAL", "DEGRADED", "UNAVAILABLE"))
        self.assertIsInstance(out.get("data_quality"), dict)

    def test_absolute_not_relative_label(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence
        out = list_watch_intelligence({"view": "top_ideas", "page_size": 3})
        for c in out.get("cards") or []:
            # relative summary must not be absolute returns mislabeled
            if c.get("absolute_performance_summary"):
                self.assertIsNone(c.get("relative_performance_summary"))
            self.assertEqual(c.get("relative_performance_quality"), "UNAVAILABLE")

    def test_ceco_not_complete_after_quarantine(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence, watch_reviews
        out = list_watch_intelligence({"view": "all", "q": "CECO", "page_size": 20})
        for c in out.get("cards") or []:
            if c.get("symbol") == "CECO":
                self.assertNotEqual((c.get("cio_review") or {}).get("status"), "COMPLETE")
                self.assertNotEqual((c.get("maria_review") or {}).get("status"), "COMPLETE")
        rev = watch_reviews("CECO")
        for r in rev.get("items") or []:
            if r.get("agent_id") in ("cio", "maria"):
                self.assertNotEqual(r.get("status"), "COMPLETE")


class TestBrokerCatalogAdvertisement(unittest.TestCase):
    def test_catalog_lists_watch_intelligence(self):
        from lib.data_broker.catalog import broker_catalog, PROJECTIONS
        cat = broker_catalog()
        self.assertTrue(cat.get("ok"))
        self.assertEqual(cat.get("service"), "data_broker")
        self.assertEqual(cat.get("provider_calls"), 0)
        ids = {p["id"] for p in PROJECTIONS}
        self.assertIn("watch_intelligence", ids)
        self.assertIn("market_quote", ids)
        self.assertIn("reentry_decision_desk", ids)
        wi = cat.get("watch_intelligence") or {}
        self.assertTrue(wi.get("primary"))
        http = " ".join(wi.get("http") or [])
        self.assertIn("/api/v3/data-broker/watch-intelligence", http)
        self.assertEqual(wi.get("provider_calls_on_page_load"), 0)

    def test_list_payload_advertises_data_broker(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence
        out = list_watch_intelligence({"view": "top_ideas", "page_size": 3})
        db = out.get("data_broker") or {}
        self.assertEqual(db.get("package"), "scripts/lib/data_broker")
        self.assertEqual(db.get("projection"), "watch_intelligence")
        self.assertEqual(db.get("catalog"), "/api/v3/data-broker")
        self.assertTrue(db.get("domains") or db.get("composes") or db.get("direct_dependencies"))
        self.assertIn("watch_domains", str(db.get("dependency_direction") or db.get("domains") or ""))

    def test_ui_advertises_broker(self):
        ui = (ROOT / "apps/command-center-v3/src/pages/WatchIntelligenceUnified.tsx").read_text()
        self.assertIn("data-broker-projection", ui)
        self.assertIn("/api/v3/data-broker", ui)
        self.assertIn("Data Broker", ui)


class TestFinalGateBlockers(unittest.TestCase):
    """PR #295 final truth + read-only blockers."""

    def test_quarantine_precedence_ceco_everywhere(self):
        from lib.data_broker.watch_intelligence import (
            list_watch_intelligence,
            detail_watch_intelligence,
            watch_reviews,
        )
        from lib.data_broker.watch_domains import load_review_artifacts, merge_review_dispositions, _not_run_display

        arts = load_review_artifacts("CECO")
        for agent in ("cio", "maria"):
            self.assertEqual(arts[agent].get("status"), "NOT_RUN")
            self.assertEqual(arts[agent].get("reason_code"), "UNVERIFIED_OPERATOR_AUTHORIZATION")
            self.assertEqual(arts[agent].get("artifact_disposition"), "QUARANTINED")

        # Lower-priority reasons must not mask quarantine
        q = _not_run_display("cio", "UNVERIFIED_OPERATOR_AUTHORIZATION", disposition="QUARANTINED")
        nmc = _not_run_display("cio", "NO_MATERIAL_CHANGE_NO_CALL", disposition="NO_MATERIAL_CHANGE_NO_CALL")
        leg = _not_run_display("cio", "LEGACY_INCOMPLETE_PROVENANCE", disposition="LEGACY_INCOMPLETE_PROVENANCE")
        merged = merge_review_dispositions(nmc, leg, q)
        self.assertEqual(merged.get("artifact_disposition"), "QUARANTINED")
        self.assertEqual(merged.get("reason_code"), "UNVERIFIED_OPERATOR_AUTHORIZATION")

        out = list_watch_intelligence({"view": "all", "q": "CECO", "page_size": 40})
        ceco = next((c for c in (out.get("cards") or []) if c.get("symbol") == "CECO"), None)
        self.assertIsNotNone(ceco)
        for key in ("cio_review", "maria_review"):
            rev = ceco.get(key) or {}
            self.assertEqual(rev.get("status"), "NOT_RUN", key)
            self.assertEqual(rev.get("reason_code"), "UNVERIFIED_OPERATOR_AUTHORIZATION", key)
            self.assertEqual(rev.get("artifact_disposition"), "QUARANTINED", key)
            self.assertIsNone(rev.get("provider"))
            self.assertIsNone(rev.get("model"))

        detail = detail_watch_intelligence("CECO")
        self.assertTrue(detail.get("ok"))
        dcard = detail.get("card") or {}
        for key in ("cio_review", "maria_review"):
            rev = dcard.get(key) or {}
            self.assertEqual(rev.get("reason_code"), "UNVERIFIED_OPERATOR_AUTHORIZATION", f"detail.{key}")
            self.assertEqual(rev.get("artifact_disposition"), "QUARANTINED", f"detail.{key}")
        self.assertNotEqual(detail.get("data_quality_status"), "OK")
        self.assertIn(detail.get("data_quality_status"), ("COMPLETE", "PARTIAL", "DEGRADED", "UNAVAILABLE"))

        rev = watch_reviews("CECO")
        for r in rev.get("items") or []:
            if r.get("agent_id") in ("cio", "maria"):
                self.assertEqual(r.get("reason_code"), "UNVERIFIED_OPERATOR_AUTHORIZATION")
                self.assertEqual(r.get("artifact_disposition"), "QUARANTINED")

    def test_get_list_zero_writes(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence
        from lib.data_broker.watch_domains import FINGERPRINT_DIR, ARTIFACTS, QUARANTINE

        roots = [FINGERPRINT_DIR, ARTIFACTS, QUARANTINE]
        before = {}
        for root in roots:
            if not root.exists():
                before[str(root)] = {}
                continue
            before[str(root)] = {
                str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size)
                for p in root.rglob("*")
                if p.is_file()
            }
        out1 = list_watch_intelligence({"view": "top_ideas", "page_size": 8})
        out2 = list_watch_intelligence({"view": "top_ideas", "page_size": 8})
        self.assertEqual(out1.get("provider_calls"), 0)
        self.assertEqual(out2.get("provider_calls"), 0)
        self.assertEqual(out1.get("snapshot_id"), out2.get("snapshot_id"))
        # material_change must not flip solely because page was refreshed
        m1 = {(c.get("symbol"), c.get("material_change")) for c in (out1.get("cards") or [])}
        m2 = {(c.get("symbol"), c.get("material_change")) for c in (out2.get("cards") or [])}
        self.assertEqual(m1, m2)
        after = {}
        for root in roots:
            if not root.exists():
                after[str(root)] = {}
                continue
            after[str(root)] = {
                str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size)
                for p in root.rglob("*")
                if p.is_file()
            }
        self.assertEqual(before, after, "list GET must not mutate fingerprint/artifact/quarantine files")

    def test_get_detail_zero_writes(self):
        from lib.data_broker.watch_intelligence import detail_watch_intelligence
        from lib.data_broker.watch_domains import FINGERPRINT_DIR

        before = {}
        if FINGERPRINT_DIR.exists():
            before = {
                p.name: (p.stat().st_mtime_ns, p.stat().st_size)
                for p in FINGERPRINT_DIR.glob("*.json")
            }
        d1 = detail_watch_intelligence("CECO")
        d2 = detail_watch_intelligence("CECO")
        self.assertTrue(d1.get("ok"))
        self.assertEqual(d1.get("provider_calls"), 0)
        self.assertEqual(d1.get("snapshot_id"), d2.get("snapshot_id"))
        self.assertEqual((d1.get("card") or {}).get("material_change"), (d2.get("card") or {}).get("material_change"))
        after = {}
        if FINGERPRINT_DIR.exists():
            after = {
                p.name: (p.stat().st_mtime_ns, p.stat().st_size)
                for p in FINGERPRINT_DIR.glob("*.json")
            }
        self.assertEqual(before, after, "detail GET must not write fingerprints")

    def test_list_detail_parity_reviews(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence, detail_watch_intelligence
        out = list_watch_intelligence({"view": "all", "q": "CECO", "page_size": 40})
        list_card = next((c for c in (out.get("cards") or []) if c.get("symbol") == "CECO"), None)
        self.assertIsNotNone(list_card)
        detail = detail_watch_intelligence("CECO")
        dcard = detail.get("card") or {}
        for key in ("cio_review", "maria_review"):
            self.assertEqual(
                (list_card.get(key) or {}).get("reason_code"),
                (dcard.get(key) or {}).get("reason_code"),
                key,
            )
            self.assertEqual(
                (list_card.get(key) or {}).get("artifact_disposition"),
                (dcard.get(key) or {}).get("artifact_disposition"),
                key,
            )
            self.assertEqual(
                (list_card.get(key) or {}).get("status"),
                (dcard.get(key) or {}).get("status"),
                key,
            )
        # detail snapshot must not depend on generated_at transport noise
        self.assertNotIn("generated_at", (detail.get("snapshot_id") or ""))
        self.assertNotEqual(detail.get("data_quality_status"), "OK")

    def test_top_ideas_excludes_fail_avoid_unavailable(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence
        from lib.data_broker.watch_domains import EXCLUDED_TOP, REPAIR_QUEUE, rank_top_ideas

        # Unit: ranker drops excluded + repair
        fake = []
        for sym, state in (
            ("OK1", "READY"),
            ("OK2", "WAIT"),
            ("FAIL1", "DETERMINISTIC_FAIL"),
            ("AVOID1", "AVOID"),
            ("BLOCK1", "BLOCKED"),
            ("NA1", "DATA_UNAVAILABLE"),
            ("STALE1", "STALE"),
        ):
            fake.append({"symbol": sym, "card": {
                "symbol": sym,
                "trade_ai_state": state,
                "street_rating": "STRONG BUY",
                "implied_upside_pct": 80,
                "freshness_state": "CURRENT",
            }})
        ranked = rank_top_ideas(fake)
        states = {(r.get("card") or {}).get("trade_ai_state") for r in ranked}
        for bad in EXCLUDED_TOP | REPAIR_QUEUE:
            self.assertNotIn(bad, states)
        self.assertTrue(states <= {"READY", "WAIT", "MANAGING"})
        for r in ranked:
            self.assertEqual((r.get("card") or {}).get("rank_eligibility"), "eligible")
            self.assertIsNotNone((r.get("card") or {}).get("rank"))
            self.assertIsNotNone((r.get("card") or {}).get("rank_components"))
            self.assertIsNotNone((r.get("card") or {}).get("rank_version"))
            self.assertIsNotNone((r.get("card") or {}).get("rank_generated_at"))

        out = list_watch_intelligence({"view": "top_ideas", "page_size": 40})
        for c in out.get("cards") or []:
            st = (c.get("trade_ai_state") or "").upper()
            self.assertNotIn(st, EXCLUDED_TOP | REPAIR_QUEUE, c.get("symbol"))
            self.assertEqual(c.get("rank_eligibility"), "eligible")

    def test_dimensional_freshness_no_generic_chip(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence
        from lib.data_broker.watch_domains import dimensional_freshness

        dims = dimensional_freshness({
            "freshness_state": "CURRENT",
            "trade_ai_state": "DETERMINISTIC_FAIL",
            "primary_risk": "technical snapshot is STALE",
            "blockers": [],
            "cio_review": {"status": "NOT_RUN", "reason_code": "UNVERIFIED_OPERATOR_AUTHORIZATION", "artifact_disposition": "QUARANTINED"},
            "maria_review": {},
        })
        self.assertEqual(dims["quote_freshness"], "CURRENT")
        self.assertEqual(dims["technical_freshness"], "STALE")
        self.assertIsNone(dims.get("card_freshness_label"))

        out = list_watch_intelligence({"view": "all", "page_size": 10})
        for c in out.get("cards") or []:
            self.assertIn("quote_freshness", c)
            self.assertIn("technical_freshness", c)
            self.assertIn("decision_freshness", c)
            self.assertIn("street_freshness", c)
            self.assertIn("review_freshness", c)
            self.assertIsNone(c.get("card_freshness_label"))

        ui = (ROOT / "apps/command-center-v3/src/pages/WatchIntelligenceUnified.tsx").read_text()
        self.assertIn("FreshnessChips", ui)
        self.assertIn("quote_freshness", ui)
        self.assertIn("technical_freshness", ui)
        # dimensional chips use Quote / Technicals labels (not a bare whole-card CURRENT)
        self.assertIn("k: 'Quote'", ui)
        self.assertIn("k: 'Technicals'", ui)
        self.assertIn("data-freshness-dim", ui)

    def test_filter_options_data_derived(self):
        from lib.data_broker.watch_intelligence import watch_filters
        f = watch_filters()
        self.assertEqual(f.get("provider_calls"), 0)
        # When zero authorized COMPLETE artifacts, provider/model options empty
        self.assertIsInstance(f.get("providers"), list)
        self.assertIsInstance(f.get("models"), list)
        by_id = {x["id"]: x for x in (f.get("filters") or [])}
        self.assertIn("provider", by_id)
        self.assertIn("model", by_id)
        self.assertIn("saved_list", by_id)
        self.assertIn("cio_view", by_id)
        self.assertEqual(by_id["provider"]["options"], f.get("providers"))
        self.assertEqual(by_id["model"]["options"], f.get("models"))
        # Unavailable filters present and disabled
        for fid in ("catalyst_window", "earnings_window", "relative_strength_band", "valuation_band"):
            self.assertIn(fid, by_id)
            self.assertFalse(by_id[fid].get("enabled"))
        # Must not hard-code deepseek when no authorized completes
        if not f.get("providers"):
            self.assertNotIn("deepseek", by_id["provider"]["options"])
            self.assertNotIn("deepseek-v4-flash", by_id["model"]["options"])

    def test_paid_flags_and_read_only(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence, detail_watch_intelligence
        out = list_watch_intelligence({"view": "top_ideas", "page_size": 3})
        self.assertFalse(out.get("paid_flags_enabled"))
        self.assertEqual(out.get("broker_write_authority"), "NONE")
        self.assertTrue((out.get("data_broker") or {}).get("read_only"))
        d = detail_watch_intelligence("CECO")
        self.assertFalse(d.get("paid_flags_enabled"))
        self.assertEqual(d.get("broker_write_authority"), "NONE")


if __name__ == "__main__":
    unittest.main()
