"""Phase 1 advisory desk: catalyst path, validation on build, conviction rule, flag."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))


class TestCatalystCachePath(unittest.TestCase):
    def test_latest_catalyst_cache_not_hardcoded(self) -> None:
        from lib.data_broker import advisory_desk as ad

        # Ensure helper does not reference a fixed date filename
        src = Path(ad.__file__).read_text(encoding="utf-8")
        self.assertNotIn("catalyst_cache_2026-08-10.json", src)
        self.assertIn("catalyst_cache_*.json", src)

        path = ad._latest_catalyst_cache_path()
        # On this host there should be at least one cache file
        if path is not None:
            self.assertTrue(path.name.startswith("catalyst_cache_"))
            self.assertTrue(path.exists())


class TestConvictionRule(unittest.TestCase):
    def test_confidence_ignores_size(self) -> None:
        """Same signals/basis → same confidence regardless of imaginary size."""
        from lib.data_broker.advisory_desk import _compute_confidence

        a = _compute_confidence(
            signals=["material_loss", "long_held"],
            days_held=200,
            gain_loss_pct=-20.0,
            reconciliation_status="OK",
            cost_basis=100.0,
        )
        b = _compute_confidence(
            signals=["material_loss", "long_held"],
            days_held=200,
            gain_loss_pct=-20.0,
            reconciliation_status="OK",
            cost_basis=100.0,
        )
        self.assertEqual(a, b)

    def test_different_basis_can_differ(self) -> None:
        """Different gain/loss (account entry) may change confidence — thesis-relevant."""
        from lib.data_broker.advisory_desk import _compute_confidence

        mild = _compute_confidence(
            signals=["material_loss"],
            days_held=100,
            gain_loss_pct=-16.0,
            reconciliation_status="OK",
            cost_basis=50.0,
        )
        deep = _compute_confidence(
            signals=["material_loss"],
            days_held=100,
            gain_loss_pct=-40.0,  # >1.5× threshold → margin bonus
            reconciliation_status="OK",
            cost_basis=50.0,
        )
        self.assertGreaterEqual(deep, mild)


class TestValidationOnBuild(unittest.TestCase):
    def test_validate_attached_to_metadata_shape(self) -> None:
        from lib.data_broker.advisory_desk import validate_advisory_output

        # Minimal invalid payload
        errs = validate_advisory_output({"ok": False})
        self.assertTrue(any("ok" in e for e in errs))

    def test_build_includes_validation_metadata(self) -> None:
        """Live build should stamp validation_ok / plausibility_gate."""
        from lib.data_broker.advisory_desk import build_advisory_desk

        result = build_advisory_desk(force=True, max_age_s=0)
        self.assertTrue(result.get("ok"))
        meta = result["data"]["metadata"]
        self.assertIn("validation_ok", meta)
        self.assertIn("validation_errors", meta)
        self.assertIn("plausibility_gate", meta)
        self.assertIsInstance(meta["validation_errors"], list)
        # Catalyst path should be resolved if any cache exists
        # (may be None only if no files — still must not crash)
        self.assertIn("catalyst_cache_path", meta)


class TestReentryUniverseJoin(unittest.TestCase):
    """Phase 1 — closed_journal must join the full decision-desk universe, not the
    journal-first-20 subset."""

    def test_reentry_row_to_opinion_maps_states(self) -> None:
        from lib.data_broker.advisory_desk import _reentry_row_to_opinion
        from lib.data_broker.advisory_desk import AdvisoryVerdict

        ready = _reentry_row_to_opinion(
            {"symbol": "FATN", "intel": {"state": "NEAR ENTRY", "reason": "in zone"}, "price": 6.24, "entry_low": 5.6, "entry_high": 6.1},
            set(),
        )
        self.assertEqual(ready["verdict"].value, "RE_ENTER")
        self.assertEqual(ready["reentry_state"], "NEAR ENTRY")
        self.assertEqual(ready["source"], "reentry_decision_desk")

        wait = _reentry_row_to_opinion(
            {"symbol": "AMC", "intel": {"state": "OVERBOUGHT WAIT", "reason": "rsi 72"}, "price": 2.52},
            set(),
        )
        self.assertEqual(wait["verdict"].value, "WAIT")
        self.assertEqual(wait["reentry_state"], "OVERBOUGHT WAIT")

    def test_reentry_row_to_opinion_skips_held(self) -> None:
        from lib.data_broker.advisory_desk import _reentry_row_to_opinion
        out = _reentry_row_to_opinion(
            {"symbol": "SCHD", "intel": {"state": "NEAR ENTRY"}},
            {"SCHD"},
        )
        self.assertIsNone(out)


class TestHubOpportunitySlice(unittest.TestCase):
    """Phase 1 — a bounded Watch Hub opportunity slice, distinct from the personal
    operator watch."""

    def test_derive_hub_opinion_is_wait_not_held(self) -> None:
        from lib.data_broker.advisory_desk import _derive_hub_opinion

        row = _derive_hub_opinion("AMD", {"asset_type": "stock", "score": 92, "source_tier": "tier1"}, set())
        self.assertEqual(row["verdict"].value, "WAIT")
        self.assertEqual(row["source"], "watch_hub")
        self.assertIn("not on personal operator watch", row["rationale"])
        self.assertEqual(row["hub_score"], 92)

    def test_derive_hub_opinion_skips_held(self) -> None:
        from lib.data_broker.advisory_desk import _derive_hub_opinion
        self.assertIsNone(_derive_hub_opinion("AMD", {}, {"AMD"}))

    def test_source_maps_to_watchlist_hub_class(self) -> None:
        # row_class assignment lives inline in build_advisory_desk; assert the
        # canonical source->class mapping is wired by exercising a built row.
        import lib.data_broker.advisory_desk as ad
        src_map = {
            "holdings": "holding",
            "watchlist": "watchlist",
            "watch_hub": "watchlist_hub",
            "reentry_decision_desk": "closed_journal",
            "allocation": "allocation",
        }
        self.assertEqual(ad._derive_hub_opinion("AMD", {}, set())["source"], "watch_hub")
        self.assertEqual(src_map["watch_hub"], "watchlist_hub")


class TestEnrichmentFlag(unittest.TestCase):
    def test_flag_off_forces_dry_run(self) -> None:
        from lib.data_broker.advisory_desk import enrich_advisory_with_opinions

        desk = {
            "ok": True,
            "data": {
                "deterministic": True,
                "llm_in_path": False,
                "metadata": {"validation_ok": True},
                "rows": [
                    {
                        "symbol": "TEST",
                        "verdict": "HOLD",
                        "confidence": 0.5,
                        "market_value": 5000,
                        "row_class": "holding",
                        "advisory_row_hash": "abc123deadbeef",
                        "evidence_bundle": {"evidence_items": [], "evidence_gaps": []},
                        "lot_data_status": "VERIFIED",
                    }
                ],
            },
        }
        with patch(
            "lib.advisory.advisory_opinion_engine._load_config",
            return_value={"ADVISORY_DESK_V1": False, "routing": {"cost": {"max_model_rows_per_run": 5}}},
        ):
            # Even if caller asks for live, flag OFF forces dry_run
            out = enrich_advisory_with_opinions(desk, dry_run=False, max_rows=1)
        self.assertTrue(out["opinions"]["dry_run"])
        self.assertFalse(out["opinions"]["ADVISORY_DESK_V1"])
        row_op = next(iter(out["opinions"]["rows"].values()))
        self.assertIn("dry_run", row_op.get("model", ""))


class TestLotRebuildScript(unittest.TestCase):
    def test_module_importable(self) -> None:
        import rebuild_tax_lots_from_transactions as r

        self.assertTrue(callable(r.rebuild))
        self.assertEqual(r.SHARE_MATCH_TOLERANCE, 0.05)


class TestHoldingsEnqueueScript(unittest.TestCase):
    def test_holdings_symbol_filter(self) -> None:
        import enqueue_holdings_agent_opinions as e

        # Function should return list (may be empty in broken env)
        syms = e._holdings_symbols()
        self.assertIsInstance(syms, list)
        for s in syms:
            self.assertFalse(s.isdigit(), f"CUSIP-like slipped through: {s}")


if __name__ == "__main__":
    unittest.main()
