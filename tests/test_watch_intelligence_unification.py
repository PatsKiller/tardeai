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
        self.assertTrue(db.get("composes"))

    def test_ui_advertises_broker(self):
        ui = (ROOT / "apps/command-center-v3/src/pages/WatchIntelligenceUnified.tsx").read_text()
        self.assertIn("data-broker-projection", ui)
        self.assertIn("/api/v3/data-broker", ui)
        self.assertIn("Data Broker", ui)


if __name__ == "__main__":
    unittest.main()
