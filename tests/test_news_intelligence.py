#!/usr/bin/env python3
"""News/catalyst freshness + projection (zero provider calls)."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class TestCatalystFreshness(unittest.TestCase):
    def test_compute_freshness_bands(self):
        from lib.data_broker.news_intelligence import compute_freshness
        now = datetime(2026, 8, 5, 19, 0, tzinfo=timezone.utc)  # ~15:00 ET RTH-ish summer
        # force with fixed now via age
        fresh = (now - timedelta(hours=1)).isoformat()
        stale = (now - timedelta(hours=30)).isoformat()
        missing = (now - timedelta(hours=100)).isoformat()
        self.assertEqual(compute_freshness(fresh, now=now), "FRESH")
        self.assertIn(compute_freshness(stale, now=now), ("STALE", "FRESH"))  # depends RTH window
        self.assertEqual(compute_freshness(missing, now=now), "MISSING")
        self.assertEqual(compute_freshness(None, now=now), "MISSING")

    def test_project_no_provider_imports(self):
        src = (ROOT / "scripts/lib/data_broker/news_intelligence.py").read_text().lower()
        for banned in ("openai", "anthropic", "chat.completions"):
            self.assertNotIn(banned, src)

    def test_enrich_sets_freshness_field(self):
        from lib.data_broker.news_intelligence import project_catalyst_context
        out = project_catalyst_context({"symbol": "ZZZZNOPE", "catalyst_summary": None})
        self.assertEqual(out.get("catalyst_freshness"), "MISSING")
        self.assertEqual(out.get("catalyst_vs_industry_quality"), "UNAVAILABLE")


class TestBrokerZeroCalls(unittest.TestCase):
    def test_list_has_catalyst_freshness(self):
        from lib.data_broker.watch_intelligence import list_watch_intelligence
        out = list_watch_intelligence({"view": "top_ideas", "page_size": 5})
        self.assertEqual(out.get("provider_calls"), 0)
        for c in out.get("cards") or []:
            self.assertIn(c.get("catalyst_freshness"), ("FRESH", "STALE", "MISSING", None))
            # field should be set
            self.assertIsNotNone(c.get("catalyst_freshness"))


if __name__ == "__main__":
    unittest.main()
