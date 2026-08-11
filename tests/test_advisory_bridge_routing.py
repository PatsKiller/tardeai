"""P0: Advisory desk must route DeepSeek through the governed bridge.

- No direct api.deepseek.com from the opinion engine.
- Cap exhaustion is returned as governance_refused (not silent spend).
- Synthesis prefers deepseek-pro / advisory_synthesis task type.
- Bridge maps advisory_desk + task_type → registered process_ids.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))


class TestAdvisoryBridgeRouting(unittest.TestCase):
    def setUp(self) -> None:
        from scripts.lib.advisory import advisory_opinion_engine as aoe

        aoe._DEAD_LANES.clear()
        self.aoe = aoe
        self.config = {
            "routing": {
                "lane_preference": [
                    {
                        "order": 1,
                        "lane": "deepseek-flash",
                        "model": "deepseek-v4-flash",
                        "purpose": "per-row opinions",
                        "provider": "deepseek",
                        "endpoint": "http://127.0.0.1:8766/v1/chat/completions",
                    },
                    {
                        "order": 2,
                        "lane": "deepseek-pro",
                        "model": "deepseek-v4-pro",
                        "purpose": "desk-level synthesis",
                        "provider": "deepseek",
                        "endpoint": "http://127.0.0.1:8766/v1/chat/completions",
                    },
                    {
                        "order": 3,
                        "lane": "local",
                        "model": "gemma3:12b",
                        "purpose": "fallback",
                        "provider": "ollama",
                        "endpoint": "http://127.0.0.1:11434/v1/chat/completions",
                        "degraded": True,
                    },
                ],
                "bridge": {
                    "endpoint": "http://127.0.0.1:8766/v1/chat/completions",
                    "caller": "advisory_desk",
                    "process_id": "advisory_desk_opinion",
                    "task_type": "advisory_opinion",
                },
            }
        }

    def test_deepseek_never_targets_public_api(self) -> None:
        """DeepSeek lanes must hit the bridge, never api.deepseek.com."""
        captured: dict = {}

        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {"message": {"content": '{"verdict":"HOLD","conviction":50,"what_changed":"x","rationale":"y","key_risk":"z","evidence_cited":[]}'}}
                        ],
                        "model": "deepseek-v4-flash",
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                    }
                ).encode()

        def fake_urlopen(req, timeout=60):
            captured["url"] = req.full_url
            captured["headers"] = {k: v for k, v in req.header_items()}
            return _FakeResp()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = self.aoe._call_bridge(
                [{"role": "user", "content": "hi"}],
                self.config,
                prefer_lane="deepseek-flash",
                task_type="advisory_opinion",
            )

        self.assertTrue(result and result.get("ok"))
        self.assertIn("127.0.0.1:8766", captured["url"])
        self.assertNotIn("api.deepseek.com", captured["url"])
        self.assertEqual(captured["headers"].get("X-tradeai-agent") or captured["headers"].get("X-TradeAI-Agent"), "advisory_desk")
        # urllib lower-cases header keys in header_items on some versions
        hdrs_lower = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertEqual(hdrs_lower.get("x-tradeai-agent"), "advisory_desk")
        self.assertEqual(hdrs_lower.get("x-tradeai-task-type"), "advisory_opinion")
        self.assertTrue(result.get("via_bridge"))

    def test_cap_exhaustion_is_governance_refused(self) -> None:
        """When bridge refuses at cap, engine surfaces COST_CAP_EXCEEDED."""
        import urllib.error

        err_body = json.dumps(
            {
                "error": {
                    "code": "COST_CAP_EXCEEDED",
                    "message": "Cost cap would be exceeded: {'allow': False}",
                    "status": 429,
                },
                "governance_pass": False,
            }
        ).encode()

        def fake_urlopen(req, timeout=60):
            raise urllib.error.HTTPError(
                req.full_url, 429, "Too Many Requests", hdrs=None, fp=MagicMock(read=lambda: err_body)
            )

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = self.aoe._call_bridge(
                [{"role": "user", "content": "hi"}],
                self.config,
                prefer_lane="deepseek-flash",
                task_type="advisory_opinion",
            )

        self.assertFalse(result.get("ok"))
        self.assertTrue(result.get("governance_refused"))
        self.assertEqual(result.get("governance_code"), "COST_CAP_EXCEEDED")
        self.assertIn("COST_CAP_EXCEEDED", result.get("error", ""))

    def test_synthesis_uses_pro_task_type(self) -> None:
        captured: dict = {}

        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [{"message": {"content": "Three things: cash, SCHD, V."}}],
                        "model": "deepseek-v4-pro",
                    }
                ).encode()

        def fake_urlopen(req, timeout=60):
            captured["url"] = req.full_url
            captured["headers"] = {k.lower(): v for k, v in req.header_items()}
            return _FakeResp()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            out = self.aoe.generate_desk_synthesis(
                [
                    {
                        "symbol": "SCHD",
                        "row_class": "holding",
                        "verdict": "TRIM",
                        "confidence": 0.7,
                        "weight_pct": 16.5,
                        "market_value": 200000,
                        "rationale": "overweight",
                        "evidence_bundle": {"evidence_count": 8, "evidence_gaps": []},
                    }
                ],
                config=self.config,
                force=True,
            )

        self.assertIn("Three things", out.get("text") or "")
        self.assertIn("127.0.0.1:8766", captured["url"])
        self.assertEqual(captured["headers"].get("x-tradeai-task-type"), "advisory_synthesis")
        self.assertEqual(out.get("lead_symbol"), "SCHD")

    def test_bridge_task_type_process_map(self) -> None:
        from scripts.lib.cio_governed_model_bridge import (
            resolve_caller,
            resolve_model_policy,
        )

        self.assertEqual(resolve_caller("advisory_desk"), "advisory_desk_opinion")
        self.assertEqual(
            resolve_caller("advisory_desk", "advisory_opinion"),
            "advisory_desk_opinion",
        )
        self.assertEqual(
            resolve_caller("advisory_desk", "advisory_synthesis"),
            "advisory_desk_synthesis",
        )
        flash = resolve_model_policy("advisory_desk_opinion")
        pro = resolve_model_policy("advisory_desk_synthesis")
        self.assertIsNotNone(flash)
        self.assertIsNotNone(pro)
        self.assertEqual(flash["model_id"], "deepseek-v4-flash")
        self.assertEqual(flash["requested_policy"], "FAST")
        self.assertEqual(pro["model_id"], "deepseek-v4-pro")
        self.assertEqual(pro["requested_policy"], "PRO")

    def test_cap_refusal_in_execute_governed_call(self) -> None:
        """Forced-exhaustion: check_cost_cap allow=False → COST_CAP_EXCEEDED."""
        from scripts.lib import cio_governed_model_bridge as bridge

        bridge._reset_circuit()

        with (
            patch.object(bridge, "_ensure_governance_imports", return_value=True),
            patch("lib.llm_consumption.get_process_config") as get_cfg,
            patch("lib.llm_model_registry.reject_legacy_model_id", return_value=None),
            patch("lib.consumption_run_manual.validate_paid_cap_config", return_value=None),
            patch("lib.consumption_run_manual.projected_max_cost_usd", return_value=0.01),
            patch("lib.llm_consumption.check_cost_cap", return_value={"allow": False, "reason": "global_cap"}),
        ):
            get_cfg.return_value = {
                "registered": True,
                "deepseek_allowed_policies": ["FAST"],
                "max_input_tokens": 32000,
                "max_output_tokens": 8192,
                "daily_cost_cap_usd": 0.05,
            }
            result = bridge.execute_governed_call(
                [{"role": "user", "content": "ping"}],
                process_id="advisory_desk_opinion",
                max_tokens=100,
            )

        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], "COST_CAP_EXCEEDED")
        self.assertFalse(result.get("governance_pass", True))
        self.assertEqual(result.get("cost_estimate"), 0.0)


if __name__ == "__main__":
    unittest.main()
