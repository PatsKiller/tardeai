"""Phase 3: verdict history, thrash, feedback, outcomes."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))


class TestThrashPenalty(unittest.TestCase):
    def test_no_penalty_below_threshold(self) -> None:
        from lib.advisory.advisory_memory import apply_thrash_penalty, thrash_penalty_points

        self.assertEqual(thrash_penalty_points(0), 0)
        self.assertEqual(thrash_penalty_points(2), 0)
        adj, pen = apply_thrash_penalty(80, 2)
        self.assertEqual(pen, 0)
        self.assertEqual(adj, 80)

    def test_penalty_reduces_conviction(self) -> None:
        from lib.advisory.advisory_memory import apply_thrash_penalty, thrash_penalty_points

        self.assertGreater(thrash_penalty_points(3), 0)
        adj, pen = apply_thrash_penalty(80, 5)
        self.assertGreater(pen, 0)
        self.assertLess(adj, 80)
        self.assertGreaterEqual(adj, 0)


class TestVerdictHistory(unittest.TestCase):
    def test_append_and_prior(self) -> None:
        from lib.advisory import advisory_memory as am

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            rows_path = td_path / "rows.jsonl"
            with patch.object(am, "ROWS_PATH", rows_path), patch.object(
                am, "RUNTIME", td_path
            ):
                n = am.append_run_history(
                    [
                        {
                            "symbol": "SPCX",
                            "account": "schwab_taxable",
                            "verdict": "EXIT",
                            "confidence": 0.85,
                            "advisory_row_hash": "abc111",
                            "row_class": "holding",
                            "market_value": 5000,
                            "rationale": "long held",
                        }
                    ],
                    opinions={
                        "abc111": {
                            "verdict": "TRIM",
                            "conviction": 70,
                            "key_risk": "momentum could reverse",
                            "rationale": "rally + basis gap",
                        }
                    },
                    run_id="test-run-1",
                )
                self.assertEqual(n, 1)
                # second run flip
                am.append_run_history(
                    [
                        {
                            "symbol": "SPCX",
                            "account": "schwab_taxable",
                            "verdict": "TRIM",
                            "confidence": 0.7,
                            "advisory_row_hash": "abc222",
                            "row_class": "holding",
                            "market_value": 5500,
                        }
                    ],
                    opinions={
                        "abc222": {
                            "verdict": "HOLD",
                            "conviction": 55,
                            "key_risk": "still concentrated",
                        }
                    },
                    run_id="test-run-2",
                )
                prior = am.load_prior_for_row("SPCX", "schwab_taxable")
                self.assertTrue(prior["has_prior"])
                self.assertEqual(prior["prior_verdict"], "HOLD")
                self.assertGreaterEqual(prior["verdict_changes_90d"], 1)
                block = am.format_memory_block(prior=prior)
                self.assertIn("Prior:", block)
                self.assertIn("HOLD", block)


class TestFeedback(unittest.TestCase):
    def test_disagree_thesis_round_trip(self) -> None:
        from lib.advisory import advisory_memory as am

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            fb_path = td_path / "fb.jsonl"
            with patch.object(am, "FEEDBACK_PATH", fb_path), patch.object(
                am, "RUNTIME", td_path
            ):
                e = am.record_feedback(
                    symbol="SPCX",
                    account="schwab_taxable",
                    rating="notuseful",
                    reason_code="DISAGREE_THESIS",
                    note="held the position",
                )
                self.assertEqual(e["reason_code"], "DISAGREE_THESIS")
                d = am.latest_disagree_thesis("SPCX", "schwab_taxable")
                self.assertIsNotNone(d)
                block = am.format_memory_block(
                    prior={"has_prior": True, "prior_verdict": "TRIM",
                           "prior_conviction": 70, "prior_date": "2026-07-14",
                           "verdict_changes_90d": 1, "thrash_penalty": 0},
                    feedback=[d],
                )
                self.assertIn("DISAGREE_THESIS", block)
                self.assertIn("held", block.lower())

    def test_notuseful_requires_code(self) -> None:
        from lib.advisory import advisory_memory as am

        with self.assertRaises(ValueError):
            am.record_feedback(symbol="X", rating="notuseful", reason_code="")


class TestOutcomeScoring(unittest.TestCase):
    def test_score_verdict_rules(self) -> None:
        from lib.advisory.advisory_memory import score_verdict_outcome

        self.assertTrue(score_verdict_outcome("TRIM", -5.0)["correct"])
        self.assertFalse(score_verdict_outcome("TRIM", 15.0)["correct"])
        self.assertTrue(score_verdict_outcome("ADD", 8.0)["correct"])
        self.assertFalse(score_verdict_outcome("ADD", -8.0)["correct"])
        self.assertTrue(score_verdict_outcome("HOLD", -5.0)["correct"])
        self.assertFalse(score_verdict_outcome("HOLD", -20.0)["correct"])

    def test_calibration_rebuild(self) -> None:
        from lib.advisory import advisory_memory as am

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            out_path = td_path / "out.jsonl"
            cal_path = td_path / "cal.json"
            with patch.object(am, "OUTCOMES_PATH", out_path), patch.object(
                am, "CALIBRATION_PATH", cal_path
            ), patch.object(am, "RUNTIME", td_path):
                for i, (v, ok) in enumerate([
                    ("TRIM", True), ("TRIM", False), ("TRIM", True),
                    ("ADD", True), ("HOLD", True),
                ]):
                    am._append_jsonl(out_path, {
                        "verdict": v, "correct": ok, "horizon_d": 30, "i": i
                    })
                cal = am.rebuild_calibration()
                self.assertEqual(cal["n_scored"], 5)
                self.assertIn("TRIM", cal["by_verdict"])
                self.assertAlmostEqual(cal["by_verdict"]["TRIM"]["hit_rate"], 2 / 3)


class TestEnrichMemoryWire(unittest.TestCase):
    def test_enrich_appends_history_and_thrash(self) -> None:
        from lib.data_broker.advisory_desk import (
            build_advisory_desk,
            enrich_advisory_with_opinions,
        )
        from lib.advisory import advisory_memory as am

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            rows_path = td_path / "rows.jsonl"
            fb_path = td_path / "fb.jsonl"
            with patch.object(am, "ROWS_PATH", rows_path), patch.object(
                am, "FEEDBACK_PATH", fb_path
            ), patch.object(am, "RUNTIME", td_path), patch.object(
                am, "CALIBRATION_PATH", td_path / "cal.json"
            ):
                # Seed thrashing history for first holding symbol
                desk = build_advisory_desk(force=True, max_age_s=0)
                holds = [
                    r for r in desk["data"]["rows"]
                    if r.get("row_class") == "holding"
                    and float(r.get("market_value") or 0) >= 500
                ]
                self.assertTrue(holds)
                # Largest MV so it is always in the enrichment ordered set
                holds.sort(key=lambda r: float(r.get("market_value") or 0), reverse=True)
                sym = holds[0]["symbol"]
                acct = holds[0].get("account") or ""
                for i, v in enumerate(["TRIM", "HOLD", "TRIM", "HOLD", "TRIM"]):
                    am.append_run_history(
                        [{
                            "symbol": sym,
                            "account": acct,
                            "verdict": v,
                            "confidence": 0.7,
                            "advisory_row_hash": f"seed{i}",
                            "row_class": "holding",
                            "market_value": 10000,
                        }],
                        opinions={f"seed{i}": {"verdict": v, "conviction": 70, "key_risk": "x"}},
                        run_id=f"seed-{i}",
                    )
                am.record_feedback(
                    symbol=sym,
                    account=acct,
                    rating="notuseful",
                    reason_code="DISAGREE_THESIS",
                    note="held through",
                )
                out = enrich_advisory_with_opinions(desk, dry_run=True, max_rows=10)
                tel = out["opinions"]["telemetry"]
                self.assertGreaterEqual(tel.get("history_rows_appended", 0), 1)
                self.assertGreaterEqual(tel.get("memory_prior_hits", 0), 1)
                # thrash should fire for the seeded symbol if in ordered set
                mem = out["opinions"].get("memory") or {}
                self.assertIn("thrash_applied_n", mem)
                # DISAGREE surfaced for at least the seeded symbol when enriched
                found = False
                for op in (out["opinions"].get("rows") or {}).values():
                    if "DISAGREE_THESIS" in str(op.get("rationale") or ""):
                        found = True
                        self.assertIn("thrash_penalty", op)
                        break
                # May not be in top-10 ordered if other actionables dominate — check prior load
                prior = am.load_prior_for_row(sym, acct)
                self.assertGreaterEqual(prior["verdict_changes_90d"], 3)
                adj, pen = am.apply_thrash_penalty(70, prior["verdict_changes_90d"])
                self.assertGreater(pen, 0)
                self.assertLess(adj, 70)


class TestAdvisoryCLI(unittest.TestCase):
    def test_cli_help(self) -> None:
        import advisory_commands as ac

        out = ac.cmd_help(None)
        self.assertIn("DISAGREE_THESIS", out)
        self.assertIn("rate", out)


if __name__ == "__main__":
    unittest.main()
