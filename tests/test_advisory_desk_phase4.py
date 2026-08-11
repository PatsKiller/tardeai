"""Phase 4: API surface, banners, brief length, feedback round-trip."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))


class TestAdvisoryApi(unittest.TestCase):
    def test_desk_payload_shape(self) -> None:
        import api_v3_advisory as adv

        d = adv.get_advisory_desk(force=True)
        self.assertTrue(d.get("ok"))
        self.assertEqual(d.get("authority"), "READ_ONLY_ADVISORY")
        self.assertIsInstance(d.get("rows"), list)
        self.assertEqual(len(d.get("banners") or []), 5)
        banner_ids = {b["id"] for b in d["banners"]}
        self.assertTrue(banner_ids)  # non-empty set of 5 states
        # data_quality column present
        if d["rows"]:
            r = d["rows"][0]
            self.assertIn("data_quality", r)
            self.assertIn("expand", r)
            self.assertIn("lots", r["expand"])
            self.assertIn("price_action", r["expand"])
            self.assertIn("memory", r["expand"])

    def test_class_filter(self) -> None:
        import api_v3_advisory as adv

        d = adv.get_advisory_desk(force=False, row_class="holding")
        for r in d.get("rows") or []:
            self.assertEqual(r.get("row_class"), "holding")

    def test_brief_body_le_5_lines(self) -> None:
        import api_v3_advisory as adv

        b = adv.get_advisory_brief(max_items=3)
        self.assertTrue(b.get("ok"))
        body_n = int(b.get("body_line_count") or 0)
        self.assertLessEqual(body_n, 5)
        text_lines = (b.get("text") or "").split("\n")
        # header + ≤5 body
        self.assertLessEqual(len(text_lines), 6)

    def test_feedback_round_trip(self) -> None:
        import api_v3_advisory as adv
        import tempfile
        from lib.advisory import advisory_memory as am

        with tempfile.TemporaryDirectory() as td:
            from pathlib import Path
            td_path = Path(td)
            with patch.object(am, "FEEDBACK_PATH", td_path / "fb.jsonl"), patch.object(
                am, "RUNTIME", td_path
            ):
                r = adv.post_feedback(
                    {"symbol": "SCHD", "rating": "useful"},
                    kind="rate",
                )
                self.assertTrue(r.get("ok"), r)
                r2 = adv.post_feedback({"symbol": "SCHD"}, kind="ack")
                self.assertTrue(r2.get("ok"), r2)
                r3 = adv.post_feedback({"symbol": "SCHD"}, kind="snooze")
                self.assertTrue(r3.get("ok"), r3)
                hist = adv.get_history("SCHD")
                self.assertTrue(hist.get("ok"))
                self.assertGreaterEqual(len(hist.get("feedback") or []), 3)


class TestTelegramParseAdvisory(unittest.TestCase):
    def test_parse_advisory_commands(self) -> None:
        from telegram_command_handler import parse_command

        self.assertEqual(parse_command("/advisory")["command"], "advisory")
        self.assertEqual(parse_command("/advisory")["args"], "brief")
        p = parse_command("/advisory rate SCHD useful")
        self.assertEqual(p["command"], "advisory")
        self.assertIn("rate", p["args"])


class TestHandleRouting(unittest.TestCase):
    def test_api_v2_advisory_get(self) -> None:
        import api_v2

        status, body = api_v2.handle("/api/v3/advisory", method="GET", body=None, query={})
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertIn("rows", body)
        self.assertEqual(len(body.get("banners") or []), 5)

    def test_api_v2_advisory_brief(self) -> None:
        import api_v2

        status, body = api_v2.handle("/api/v3/advisory/brief", method="GET", body=None, query={})
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertLessEqual(int(body.get("body_line_count") or 0), 5)


class TestAlertRegressionDoc(unittest.TestCase):
    """Phase 4.5: advisory delivery must not remove or gate existing producers."""

    def test_advisory_not_in_alert_router_suppress_path(self) -> None:
        # Morning digest still has prior sections; advisory is additive only.
        from morning_command_digest import _SECTION_ORDER

        keys = [k for k, _ in _SECTION_ORDER]
        self.assertIn("portfolio", keys)
        self.assertIn("stops", keys)
        self.assertIn("health", keys)
        self.assertIn("advisory", keys)
        # advisory is not first and does not replace others
        self.assertNotEqual(keys[0], "advisory")


if __name__ == "__main__":
    unittest.main()
