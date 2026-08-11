"""Phase 6: kb_lessons + notification broker."""
from __future__ import annotations

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


class TestKbLessons(unittest.TestCase):
    def test_propose_ratify_retrieve_retire(self) -> None:
        from lib.advisory import kb_lessons as kb

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            with patch.object(kb, "RUNTIME", td_path), patch.object(
                kb, "LESSONS_PATH", td_path / "lessons.jsonl"
            ), patch.object(kb, "CANDIDATES_PATH", td_path / "cands.jsonl"), patch.object(
                kb, "APPLICATIONS_PATH", td_path / "apps.jsonl"
            ), patch.object(kb, "LESSONS_INDEX", td_path / "idx.json"):
                c = kb.propose_lesson(
                    title="Test cash lesson",
                    body="Lead synthesis with cash excess.",
                    symbols=["CASH"],
                    verdict_types=["TRIM"],
                    source="reflection_ips",
                )
                self.assertEqual(c["status"], "candidate")
                r = kb.ratify_lesson(c["id"], by="iris_test")
                self.assertEqual(r["status"], "ratified")
                got = kb.list_lessons(status="ratified")
                self.assertEqual(len(got), 1)
                hits = kb.retrieve_lessons_for_row(symbol="CASH", verdict="TRIM", query_text="cash excess")
                self.assertTrue(hits)
                # applications + auto-retire path
                for i in range(20):
                    kb.record_application(c["id"], symbol="CASH", hit=(i < 5), cited_in_rationale=(i < 3))
                # hit_rate 5/20 = 0.25 < 0.40 → auto-retire on next record or sweep
                retired = kb.auto_retire_sweep()
                self.assertTrue(any(x["id"] == c["id"] for x in retired) or
                                any(l.get("status") == "retired" for l in kb.list_lessons(status=None)))
                st = kb.stats()
                self.assertIn("by_status", st)

    def test_reflection_and_safe_ratify(self) -> None:
        from lib.advisory import kb_lessons as kb
        from lib.advisory import advisory_memory as am

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            with patch.object(kb, "RUNTIME", td_path), patch.object(
                kb, "LESSONS_PATH", td_path / "lessons.jsonl"
            ), patch.object(kb, "CANDIDATES_PATH", td_path / "cands.jsonl"), patch.object(
                kb, "APPLICATIONS_PATH", td_path / "apps.jsonl"
            ), patch.object(kb, "LESSONS_INDEX", td_path / "idx.json"), patch.object(
                am, "ROWS_PATH", td_path / "rows.jsonl"
            ), patch.object(am, "FEEDBACK_PATH", td_path / "fb.jsonl"), patch.object(
                am, "OUTCOMES_PATH", td_path / "out.jsonl"
            ):
                # seed thrash history
                for i, v in enumerate(["TRIM", "HOLD", "TRIM", "HOLD"]):
                    am.append_run_history(
                        [{"symbol": "ZZZ", "account": "t", "verdict": v, "confidence": 0.7,
                          "advisory_row_hash": f"h{i}", "row_class": "holding", "market_value": 9000}],
                        opinions={f"h{i}": {"verdict": v, "conviction": 70}},
                        run_id=f"r{i}",
                    )
                r = kb.nightly_reflection()
                self.assertTrue(r["ok"])
                self.assertGreaterEqual(r["proposed"], 1)
                ratified = kb.iris_auto_ratify_safe(limit=20)
                self.assertGreaterEqual(len(ratified), 1)


class TestNotificationBroker(unittest.TestCase):
    def test_dedupe_compression_and_zero_material_drop(self) -> None:
        from lib.advisory import notification_broker as nb

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            with patch.object(nb, "BROKER_DIR", td_path), patch.object(
                nb, "INGEST_PATH", td_path / "ingest.jsonl"
            ), patch.object(nb, "DECISIONS_PATH", td_path / "dec.jsonl"), patch.object(
                nb, "METRICS_PATH", td_path / "metrics.json"
            ), patch.object(nb, "PROOF_PATH", td_path / "proof.json"):
                nb.ingest("⚠️ ORPHANED STOP X", producer="stops", alert_type="orphaned_stop")
                nb.ingest("⚠️ ORPHANED STOP X", producer="stops", alert_type="orphaned_stop")
                nb.ingest("debug ok", producer="health", alert_type="debug_or_success")
                nb.ingest("debug ok", producer="health", alert_type="debug_or_success")
                r = nb.process_window(hours=24)
                m = r["metrics"]
                self.assertEqual(m["ingested"], 4)
                self.assertEqual(m["unique"], 2)
                self.assertGreater(m["compression_ratio"], 0)
                self.assertTrue(m["zero_material_drops"])
                self.assertEqual(r["proof"]["egress_cutover"], "ELIGIBLE_OPERATOR_GATE")
                # material still present
                self.assertGreaterEqual(m["material_out"], 1)

    def test_wrap_send_never_raises(self) -> None:
        from lib.advisory.notification_broker import wrap_send_hook
        # even if paths fail, should not raise for telegram chokepoint
        wrap_send_hook("hello", producer="test")


if __name__ == "__main__":
    unittest.main()
