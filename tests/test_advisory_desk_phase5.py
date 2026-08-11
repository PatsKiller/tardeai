"""Phase 5: shadow sessions + Guardian/Ledger specialist mandates."""
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


class TestGuardianLedger(unittest.TestCase):
    def test_specialists_shadow_readonly(self) -> None:
        from lib.advisory import specialist_shadow as ss

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            with patch.object(ss, "SHADOW_DIR", td_path), patch.object(
                ss, "ARTIFACTS_DIR", td_path / "artifacts"
            ), patch.object(ss, "SENTINEL_PATH", td_path / "sentinel.jsonl"), patch.object(
                ss, "DARWIN_PATH", td_path / "darwin.jsonl"
            ):
                r = ss.run_all_specialists(session_id="test")
                self.assertIn("guardian", r)
                self.assertIn("ledger", r)
                self.assertIn("steph", r)
                g = r["guardian"]
                self.assertEqual(g["mode"], "SHADOW")
                self.assertEqual(g["authority"], "READ_ONLY_ADVISORY")
                self.assertEqual(g["mandate"], "cash_concentration_ips")
                self.assertEqual(g["sentinel"]["status"], "PASS")
                self.assertIsNotNone(g["darwin"]["overall"])

                led = r["ledger"]
                self.assertEqual(led["tax_lane"], "claude_only_numbers_via_portfolio_retirement")
                self.assertFalse(led["deepseek_used"])
                self.assertEqual(led["mandate"], "roth_conversion_golden_window")
                self.assertEqual(led["sentinel"]["status"], "PASS")
                self.assertFalse(r.get("deepseek_on_tax_lane"))
                self.assertEqual(r.get("contradictions"), 0)
                self.assertTrue(r.get("ok"))


class TestShadowSession(unittest.TestCase):
    def test_dry_session_passes_gates(self) -> None:
        from lib.advisory import shadow_session as sh
        from lib.advisory import specialist_shadow as ss

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            with patch.object(sh, "SHADOW_DIR", td_path), patch.object(
                sh, "SESSIONS_PATH", td_path / "sessions.jsonl"
            ), patch.object(sh, "SCOREBOARD_PATH", td_path / "scoreboard.json"), patch.object(
                sh, "ARTIFACTS_DIR", td_path / "artifacts"
            ), patch.object(ss, "SHADOW_DIR", td_path), patch.object(
                ss, "ARTIFACTS_DIR", td_path / "artifacts"
            ), patch.object(ss, "SENTINEL_PATH", td_path / "sentinel.jsonl"), patch.object(
                ss, "DARWIN_PATH", td_path / "darwin.jsonl"
            ):
                rec = sh.run_shadow_session(live_llm=False, max_rows=5, run_specialists=True)
                self.assertEqual(rec["mode"], "SHADOW")
                self.assertTrue(rec["gates"]["session_pass"], rec["gates"])
                self.assertFalse(rec["gates"]["live_llm"])
                self.assertEqual(rec["gates"]["spend_usd"], 0.0)
                self.assertTrue(rec["gates"]["validation_ok"])
                self.assertTrue(rec["gates"]["plausibility_pass"])
                self.assertTrue(rec["gates"]["invariants_green"])
                # scoreboard advances
                board = sh.rebuild_scoreboard()
                self.assertEqual(board["sessions_completed"], 1)
                self.assertEqual(board["sessions_passed"], 1)
                self.assertGreaterEqual(board["specialist_artifacts_on_disk"], 3)

    def test_scoreboard_target(self) -> None:
        from lib.advisory.shadow_session import TARGET_SESSIONS, USEFUL_RATE_TARGET

        self.assertEqual(TARGET_SESSIONS, 20)
        self.assertEqual(USEFUL_RATE_TARGET, 0.60)


class TestCLI(unittest.TestCase):
    def test_status_cli(self) -> None:
        import advisory_shadow_session as cli

        # Should not crash
        rc = cli.main(["--status"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
