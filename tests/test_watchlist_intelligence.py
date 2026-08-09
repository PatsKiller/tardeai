#!/usr/bin/env python3
"""Watchlist Intelligence Board — truthfulness + zero provider-call tests."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.watchlist_intelligence import (  # noqa: E402
    not_run_review,
    validate_complete_review,
    complete_review_from_validated,
    map_street_rating,
    list_intelligence,
    detail_intelligence,
    reviews_intelligence,
    _try_promote_artifact,
)


class TestStreetPrimary(unittest.TestCase):
    def test_street_mapping(self):
        self.assertEqual(map_street_rating("strong_buy")["street_rating"], "STRONG BUY")
        self.assertEqual(map_street_rating("buy")["street_rating"], "BUY")
        self.assertEqual(map_street_rating("hold")["street_rating"], "HOLD")
        self.assertEqual(map_street_rating(None)["street_rating"], "NOT RATED")


class TestReviewTruthfulness(unittest.TestCase):
    def test_not_run_never_shows_model(self):
        r = not_run_review("cio", reason_code="NO_MATERIAL_CHANGE_NO_CALL")
        self.assertEqual(r["status"], "NOT_RUN")
        self.assertIsNone(r["provider"])
        self.assertIsNone(r["model"])
        self.assertEqual(r["requested_policy"], "NO_CALL")
        self.assertEqual(r["executed_policy"], "NO_CALL")
        self.assertEqual(r["estimated_cost_usd"], 0.0)
        self.assertEqual(r["display"]["provider"], "NONE")
        self.assertEqual(r["display"]["model"], "NONE")
        self.assertEqual(r["display"]["policy"], "NO_CALL")
        self.assertEqual(r["display"]["cost"], "$0")
        self.assertNotIn("deepseek", json.dumps(r).lower())

    def test_incomplete_cannot_be_complete(self):
        ok, missing = validate_complete_review({
            "agent_id": "maria",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
        })
        self.assertFalse(ok)
        self.assertTrue(missing)

    def test_complete_requires_full_provenance(self):
        full = {
            "agent_id": "maria",
            "process_id": "watchlist_maria_flash_narrative",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "requested_policy": "FAST",
            "executed_policy": "FAST",
            "fallback_used": False,
            "provider_request_id": "req-abc",
            "started_at": "2026-08-05T12:00:00Z",
            "completed_at": "2026-08-05T12:00:02Z",
            "input_snapshot_id": "snap-1",
            "input_hash": "hash-in",
            "artifact_id": "art-1",
            "artifact_hash": "hash-art",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "estimated_cost_usd": 0.0002,
            "summary": "Thesis intact",
            "verdict": "HOLD",
        }
        self.assertTrue(validate_complete_review(full)[0])
        c = complete_review_from_validated(full)
        self.assertEqual(c["status"], "COMPLETE")
        self.assertEqual(c["model"], "deepseek-v4-flash")
        self.assertEqual(c["provider"], "deepseek")
        self.assertTrue(c["request_id_present"])

    def test_legacy_incomplete_demoted(self):
        r = _try_promote_artifact(
            {
                "agent_id": "maria",
                "model": "gemma3:4b",
                "summary": "legacy",
            },
            agent_id="maria",
        )
        self.assertEqual(r["status"], "NOT_RUN")
        self.assertIsNone(r["model"])
        self.assertEqual(r["reason_code"], "LEGACY_INCOMPLETE_PROVENANCE")


class TestListDetailReadOnly(unittest.TestCase):
    def test_list_zero_provider_calls_and_street_primary(self):
        out = list_intelligence(limit=6)
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("provider_calls"), 0)
        self.assertFalse(out.get("paid_flags_enabled"))
        cards = out.get("cards") or []
        self.assertGreaterEqual(len(cards), 1)
        for c in cards:
            self.assertIn(c.get("street_rating"), {
                "STRONG BUY", "BUY", "HOLD", "SELL", "NOT RATED",
            })
            # CIO/Maria never invent models when not COMPLETE
            for key in ("cio_review", "maria_review"):
                rev = c.get(key) or {}
                if rev.get("status") != "COMPLETE":
                    self.assertIn(rev.get("model"), (None,))
                    self.assertIn(rev.get("provider"), (None,))
                    self.assertEqual(rev.get("policy"), "NO_CALL")
            # card surfaces
            self.assertTrue("company" in c)
            self.assertTrue("trade_ai_state" in c)
            self.assertTrue("cio_review" in c)
            self.assertTrue("maria_review" in c)

    def test_detail_sections_and_zero_calls(self):
        out = detail_intelligence("CECO")
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("provider_calls"), 0)
        for section in (
            "identity", "street", "trade_ai", "cio_review", "maria_review",
            "reviews", "catalysts", "relative_performance", "fundamentals",
            "technicals", "thesis", "freshness_matrix", "evidence_lineage",
        ):
            self.assertIn(section, out, msg=section)
        self.assertTrue(
            out["identity"].get("what_the_company_does")
            or out["identity"].get("description")
            or out["card"].get("company_summary")
        )
        # LLM cannot force READY via this endpoint
        if out["trade_ai"].get("primary_state") != "READY":
            self.assertFalse(out["trade_ai"].get("current_mechanics_visible") or False)
            self.assertIsNone(out.get("mechanics"))

    def test_reviews_endpoint_no_call(self):
        out = reviews_intelligence("FTH")
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("provider_calls"), 0)
        for r in out.get("reviews") or []:
            if r.get("status") == "COMPLETE":
                self.assertTrue(r.get("model"))
                self.assertTrue(r.get("provider"))
                self.assertTrue(r.get("artifact_id"))
            else:
                self.assertIsNone(r.get("model"))
                self.assertIsNone(r.get("provider"))
                self.assertEqual(r.get("executed_policy"), "NO_CALL")

    def test_no_provider_import_on_page_load_path(self):
        """Aggregator must not import live provider clients."""
        src = (ROOT / "scripts/lib/watchlist_intelligence.py").read_text()
        for banned in (
            "openai",
            "anthropic",
            "httpx.post",
            "requests.post",
            "deepseek_client",
            "call_provider",
            "chat.completions",
        ):
            self.assertNotIn(banned, src.lower() if banned.islower() else src)

    def test_ui_routes_exist(self):
        app = (ROOT / "apps/command-center-v3/src/App.tsx").read_text()
        self.assertIn("watch/intelligence/:symbol", app)
        hub = (ROOT / "apps/command-center-v3/src/pages/WatchHub.tsx").read_text()
        self.assertIn("Intelligence", hub)
        self.assertIn("WatchlistIntelligenceBoard", hub)
        board = (ROOT / "apps/command-center-v3/src/pages/WatchlistIntelligenceBoard.tsx").read_text()
        self.assertIn("data-primary-rating", board)
        self.assertIn("Provider NONE", board)
        self.assertIn("Model NONE", board)
        page = (ROOT / "apps/command-center-v3/src/pages/SymbolIntelligencePage.tsx").read_text()
        self.assertIn("What the company does", page)
        self.assertIn("data-symbol-intelligence-page", page)


if __name__ == "__main__":
    unittest.main()
