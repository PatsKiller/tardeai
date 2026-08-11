"""Phase 7: 30-session promotion gate, authority fence, alert integrity."""
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


def _fake_sessions(n_pass: int, n_fail_prefix: int = 0) -> list[dict]:
    rows = []
    for i in range(n_fail_prefix):
        rows.append({
            "session_id": f"fail{i}",
            "gates": {
                "session_pass": False,
                "validation_ok": False,
                "plausibility_pass": True,
                "invariants_green": True,
                "spend_usd": 0.0,
            },
            "metrics": {"changed_rows": 10},
        })
    for i in range(n_pass):
        rows.append({
            "session_id": f"pass{i}",
            "gates": {
                "session_pass": True,
                "validation_ok": True,
                "plausibility_pass": True,
                "invariants_green": True,
                "spend_usd": 0.01,
            },
            "metrics": {"changed_rows": 5 + (i % 3)},
        })
    return rows


class TestConsecutivePasses(unittest.TestCase):
    def test_streak_counts_from_end(self) -> None:
        from lib.advisory.promotion_gate import consecutive_passes, PROMOTION_SESSIONS

        self.assertEqual(PROMOTION_SESSIONS, 30)
        s = consecutive_passes(_fake_sessions(5, n_fail_prefix=2))
        self.assertEqual(s["consecutive_passes"], 5)
        self.assertFalse(s["met"])
        s30 = consecutive_passes(_fake_sessions(30))
        self.assertEqual(s30["consecutive_passes"], 30)
        self.assertTrue(s30["met"])
        # fail at end breaks streak
        broken = _fake_sessions(30) + [{
            "session_id": "x",
            "gates": {"session_pass": False, "validation_ok": False,
                      "plausibility_pass": True, "invariants_green": True, "spend_usd": 0},
            "metrics": {},
        }]
        self.assertEqual(consecutive_passes(broken)["consecutive_passes"], 0)


class TestAuthorityAndAlerts(unittest.TestCase):
    def test_authority_fence_ok(self) -> None:
        from lib.advisory.promotion_gate import check_authority_fence
        r = check_authority_fence()
        self.assertTrue(r["ok"], r.get("issues"))
        self.assertFalse(r["broker_credentials_on_agents"])

    def test_alert_integrity_ok(self) -> None:
        from lib.advisory.promotion_gate import check_alert_integrity
        r = check_alert_integrity()
        self.assertTrue(r["ok"], r)


class TestPromotionFlow(unittest.TestCase):
    def test_promote_requires_confirm_and_gates(self) -> None:
        from lib.advisory import promotion_gate as pg
        from lib.advisory import advisory_memory as am
        from lib.advisory import kb_lessons as kb
        from lib.advisory import shadow_session as sh

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sessions = td_path / "sessions.jsonl"
            # 30 green sessions
            for s in _fake_sessions(30):
                with open(sessions, "a") as f:
                    f.write(json.dumps(s) + "\n")
            # useful feedback n>=5, 60%+
            fb = td_path / "fb.jsonl"
            for i in range(6):
                with open(fb, "a") as f:
                    f.write(json.dumps({
                        "rating": "useful" if i < 5 else "notuseful",
                        "reason_code": "TOO_SMALL" if i >= 5 else "USEFUL",
                    }) + "\n")
            # lessons ratified
            lessons = td_path / "lessons.jsonl"
            for i in range(10):
                with open(lessons, "a") as f:
                    f.write(json.dumps({
                        "id": f"L{i}", "status": "ratified", "title": f"t{i}",
                        "applications": 0, "hits": 0, "citations": 0,
                    }) + "\n")

            with patch.object(pg, "SESSIONS_PATH", sessions), patch.object(
                pg, "PROMOTION_PATH", td_path / "PROMOTION.json"
            ), patch.object(pg, "PROMOTION_LOG", td_path / "plog.jsonl"), patch.object(
                pg, "SCOREBOARD_PATH", td_path / "sb.json"
            ), patch.object(pg, "ARTIFACTS_DIR", td_path / "arts"), patch.object(
                am, "FEEDBACK_PATH", fb
            ), patch.object(kb, "LESSONS_PATH", lessons), patch.object(
                kb, "CANDIDATES_PATH", td_path / "cands.jsonl"
            ), patch.object(kb, "APPLICATIONS_PATH", td_path / "apps.jsonl"), patch.object(
                sh, "SESSIONS_PATH", sessions
            ), patch.object(sh, "SCOREBOARD_PATH", td_path / "sb.json"), patch.object(
                sh, "ARTIFACTS_DIR", td_path / "arts"
            ), patch.object(sh, "SHADOW_DIR", td_path):
                (td_path / "arts").mkdir(exist_ok=True)
                # refuse without confirm
                r0 = pg.promote(confirm=False)
                self.assertFalse(r0.get("ok"))
                ev = pg.evaluate_promotion()
                self.assertTrue(ev["gates"]["consecutive_30"]["met"], ev["gates"]["consecutive_30"])
                self.assertTrue(ev["gates"]["useful_rate"]["ok"], ev["gates"]["useful_rate"])
                self.assertTrue(ev["gates"]["authority_fence"]["ok"])
                self.assertTrue(ev["gates"]["alert_integrity"]["ok"])
                self.assertTrue(ev["gates"]["lessons"]["ok"], ev["gates"]["lessons"])
                self.assertTrue(ev.get("all_gates_green"), json.dumps(ev["gates"], default=str)[:800])
                r = pg.promote(confirm=True, operator="test")
                self.assertTrue(r.get("ok"), r)
                st = pg.load_promotion_state()
                self.assertEqual(st["status"], "PROMOTED")
                self.assertTrue(st["morning_path_default"])
                self.assertFalse(st.get("broker_enabled", True) and st.get("broker_enabled"))
                self.assertTrue(pg.is_morning_path_default())
                # demote
                pg.demote(reason="test")
                self.assertFalse(pg.is_morning_path_default())


class TestMorningPath(unittest.TestCase):
    def test_morning_respects_promotion(self) -> None:
        from morning_command_digest import advisory_morning_enabled
        from lib.advisory import promotion_gate as pg
        import os

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            prom = td_path / "PROMOTION.json"
            prom.write_text(json.dumps({"status": "NOT_PROMOTED", "morning_path_default": False}))
            with patch.object(pg, "PROMOTION_PATH", prom):
                os.environ["ADVISORY_MORNING"] = "0"
                self.assertFalse(advisory_morning_enabled())
                os.environ["ADVISORY_MORNING"] = "1"
                self.assertTrue(advisory_morning_enabled())
                del os.environ["ADVISORY_MORNING"]
                prom.write_text(json.dumps({"status": "PROMOTED", "morning_path_default": True, "promoted": True}))
                self.assertTrue(advisory_morning_enabled())


if __name__ == "__main__":
    unittest.main()
