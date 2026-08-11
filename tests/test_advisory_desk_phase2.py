"""Phase 2: material hash, stable prompts, dollars-first synthesis, cache telemetry."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))


class TestMaterialHash(unittest.TestCase):
    def test_penny_tick_same_hash(self) -> None:
        from lib.data_broker.advisory_desk import _row_hash

        base = {
            "symbol": "SCHD",
            "verdict": "TRIM",
            "confidence": 0.70,
            "weight_pct": 16.49,
            "market_value": 208_400.00,
            "gain_loss_pct": 12.3,
            "days_held": 400,
            "account": "schwab_taxable",
            "source": "holdings",
            "risk_signals": ["overweight"],
            "housekeeping_flag": False,
            "row_class": "holding",
            "lot_data_status": "VERIFIED",
        }
        a = dict(base)
        b = dict(base)
        b["market_value"] = 208_401.50  # +$1.50 noise — within 0.5% bucket
        self.assertEqual(_row_hash(a), _row_hash(b))

    def test_material_weight_change_differs(self) -> None:
        from lib.data_broker.advisory_desk import _row_hash

        a = {
            "symbol": "SCHD",
            "verdict": "TRIM",
            "confidence": 0.70,
            "weight_pct": 16.0,
            "market_value": 200_000,
            "gain_loss_pct": 10.0,
            "days_held": 100,
            "account": "x",
            "source": "holdings",
            "risk_signals": [],
            "row_class": "holding",
        }
        b = dict(a)
        b["weight_pct"] = 17.5  # >0.1pp bucket
        self.assertNotEqual(_row_hash(a), _row_hash(b))


class TestStablePrompt(unittest.TestCase):
    def test_system_prompt_identical_across_symbols(self) -> None:
        from lib.advisory.advisory_opinion_engine import _build_opinion_messages

        cfg = {
            "routing": {
                "stable_system_prompt": "STABLE PREFIX v1\nNo timestamps.",
            }
        }
        m1 = _build_opinion_messages(
            {"evidence_items": [{"type": "x", "title": "a"}]},
            "HOLD",
            cfg,
            symbol="AAA",
        )
        m2 = _build_opinion_messages(
            {"evidence_items": [{"type": "y", "title": "b"}]},
            "TRIM",
            cfg,
            symbol="BBB",
        )
        self.assertEqual(m1[0]["content"], m2[0]["content"])
        self.assertEqual(m1[0]["role"], "system")
        self.assertIn("STABLE PREFIX", m1[0]["content"])
        # Volatile content lives in user message
        self.assertIn("AAA", m1[1]["content"] or "")
        self.assertIn("BBB", m2[1]["content"] or "")
        self.assertNotIn("AAA", m1[0]["content"])


class TestDollarsFirstSynthesis(unittest.TestCase):
    def test_rank_order(self) -> None:
        from lib.advisory.advisory_opinion_engine import rank_rows_dollars_first

        rows = [
            {"symbol": "SMALL", "market_value": 1000, "verdict": "TRIM", "row_class": "holding"},
            {"symbol": "CASH", "market_value": 500_000, "verdict": "ADD", "row_class": "allocation"},
            {"symbol": "MID", "market_value": 50_000, "verdict": "HOLD", "row_class": "holding"},
        ]
        ranked = rank_rows_dollars_first(rows)
        self.assertEqual(ranked[0]["symbol"], "CASH")
        self.assertEqual(ranked[1]["symbol"], "MID")

    def test_synthesis_lead_is_largest(self) -> None:
        from lib.advisory import advisory_opinion_engine as aoe

        rows = [
            {
                "symbol": "TINY",
                "row_class": "holding",
                "verdict": "EXIT",
                "market_value": 600,
                "rationale": "small",
                "evidence_bundle": {"evidence_count": 3, "evidence_gaps": []},
            },
            {
                "symbol": "WHALE",
                "row_class": "allocation",
                "verdict": "ADD",
                "market_value": 514_000,
                "rationale": "cash excess",
                "evidence_bundle": {"evidence_count": 3, "evidence_gaps": []},
            },
        ]
        # Force degraded path (no network) by killing lanes
        cfg = {"routing": {"lane_preference": [], "bridge": {}}}
        out = aoe.generate_desk_synthesis(rows, config=cfg, force=True)
        self.assertEqual(out.get("lead_symbol"), "WHALE")
        self.assertIn("WHALE", out.get("text") or "")


class TestLocalCacheZeroCalls(unittest.TestCase):
    def test_second_call_is_cache_hit(self) -> None:
        from lib.advisory import advisory_opinion_engine as aoe

        # Seed cache
        row_hash = "phase2test01"
        cache = aoe._load_opinion_cache()
        cache[row_hash] = {
            "verdict": "HOLD",
            "conviction": 50,
            "what_changed": "cached",
            "rationale": "from cache",
            "key_risk": "none",
            "evidence_cited": [],
            "advisory_row_hash": row_hash,
            "model": "seed",
        }
        aoe._save_opinion_cache(cache)

        calls = {"n": 0}

        def boom(*a, **k):
            calls["n"] += 1
            raise AssertionError("bridge must not be called on cache hit")

        with patch.object(aoe, "_call_bridge", side_effect=boom):
            out = aoe.generate_row_opinion(
                {"advisory_row_hash": row_hash, "symbol": "X", "confidence": 0.5},
                {"evidence_items": []},
                "HOLD",
                config={"routing": {"lane_preference": [{"lane": "deepseek-flash", "provider": "deepseek"}]}},
            )
        self.assertTrue(out.get("cache_hit"))
        self.assertEqual(calls["n"], 0)
        self.assertEqual(out.get("verdict"), "HOLD")


class TestEvidenceMeanAndTechnicals(unittest.TestCase):
    def test_build_evidence_stats(self) -> None:
        from lib.data_broker.advisory_desk import build_advisory_desk

        r = build_advisory_desk(force=True, max_age_s=0)
        holds = [x for x in r["data"]["rows"] if x.get("row_class") == "holding"]
        counts = [
            (x.get("evidence_bundle") or {}).get("evidence_count") or 0
            for x in holds
        ]
        mean = sum(counts) / len(counts) if counts else 0
        # Phase 2A target ≥8
        self.assertGreaterEqual(mean, 8.0, f"mean evidence {mean} < 8")
        # technicals gap should drop vs pure indicator_snapshot (derived OK)
        tech_gaps = sum(
            1
            for x in holds
            if "technicals" in ((x.get("evidence_bundle") or {}).get("evidence_gaps") or [])
        )
        # Not all must have native RSI, but most should have technicals item
        with_tech = 0
        for x in holds:
            items = (x.get("evidence_bundle") or {}).get("evidence_items") or []
            if any(i.get("type") == "technicals" for i in items if isinstance(i, dict)):
                with_tech += 1
        self.assertGreaterEqual(with_tech, int(0.7 * len(holds)))


class TestActionableCoverageDryRun(unittest.TestCase):
    def test_actionable_all_covered_in_dry_run(self) -> None:
        from lib.data_broker.advisory_desk import (
            build_advisory_desk,
            enrich_advisory_with_opinions,
            MATERIALITY_FLOOR_USD,
        )

        desk = build_advisory_desk(force=True, max_age_s=0)
        out = enrich_advisory_with_opinions(desk, dry_run=True, max_rows=20)
        tel = out["opinions"]["telemetry"]
        # When there are actionable rows, coverage must be 100%
        if tel["actionable_total"] > 0:
            self.assertEqual(
                tel["actionable_covered"],
                tel["actionable_total"],
                msg=tel,
            )
            self.assertEqual(tel["actionable_coverage_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
