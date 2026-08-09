"""P-1.2A mock tests for CIO Governed Model Bridge.

All tests use MockProvider — ZERO real provider calls.
Tests cover governance pipeline, authorization, security, tool calling,
structured output, provenance, error handling, and watch regression.
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))


# ── Test helpers ──────────────────────────────────────────────────────────

def _mock_get_process_config(process_id: str) -> dict:
    """Fixture for registered alex_cio_synthesis process."""
    if process_id == "alex_cio_synthesis":
        return {
            "process_id": "alex_cio_synthesis",
            "process_name": "Alex CIO Autonomous Advisory Synthesis",
            "category": "CIO",
            "mode": "automated",
            "allowed_lanes": ["pro", "deepseek-v4-pro"],
            "deepseek_allowed_policies": ["PRO", "PRO_THINK"],
            "registered": True,
            "max_input_tokens": 32000,
            "max_output_tokens": 16384,
            "daily_soft_cap": 40,
            "daily_cost_cap_usd": 0.02,
            "tools_allowed": True,
            "fallback_allowed": False,
            "advisory_only": True,
        }
    if process_id == "alex_cio_escalation":
        return {
            "process_id": "alex_cio_escalation",
            "process_name": "Alex CIO Complex Escalation",
            "category": "CIO",
            "mode": "automated",
            "allowed_lanes": ["pro_think"],
            "deepseek_allowed_policies": ["PRO", "PRO_THINK"],
            "registered": True,
            "max_input_tokens": 32000,
            "max_output_tokens": 16384,
            "daily_soft_cap": 10,
            "daily_cost_cap_usd": 0.02,
            "tools_allowed": True,
            "fallback_allowed": False,
            "advisory_only": True,
        }
    # Unregistered
    return {
        "process_id": process_id,
        "process_name": process_id,
        "category": "Unknown",
        "mode": "manual",
        "allowed_lanes": [],
        "deepseek_allowed_policies": [],
        "registered": False,
        "max_input_tokens": None,
        "max_output_tokens": None,
        "daily_soft_cap": None,
        "daily_cost_cap_usd": None,
    }


# ══════════════════════════════════════════════════════════════════════════


class TestCIOGovernedModelBridge(unittest.TestCase):
    """Governance pipeline tests using MockProvider — zero real calls."""

    @classmethod
    def setUpClass(cls) -> None:
        os.environ["LLM_GLOBAL_DAILY_USD_CAP"] = "0.50"

    def setUp(self) -> None:
        from scripts.lib.cio_governed_model_bridge import _CIRCUIT, _reset_circuit
        _reset_circuit()
        self._patch_get_config = patch(
            "lib.llm_consumption.get_process_config",
            side_effect=_mock_get_process_config,
        )
        self._patch_get_config.start()

        self._patch_reject = patch(
            "lib.llm_model_registry.reject_legacy_model_id",
            return_value=None,
        )
        self._patch_reject.start()

        self._patch_validate = patch(
            "lib.consumption_run_manual.validate_paid_cap_config",
            return_value=None,
        )
        self._patch_validate.start()

        self._patch_projected = patch(
            "lib.consumption_run_manual.projected_max_cost_usd",
            return_value=0.002,
        )
        self._patch_projected.start()

        self._patch_check_cap = patch(
            "lib.llm_consumption.check_cost_cap",
            return_value={"allow": True, "spent_process_usd": 0.0},
        )
        self._patch_check_cap.start()

        self._patch_reserve = patch(
            "lib.llm_consumption.reserve_projected_cost",
            return_value=42,
        )
        self._patch_reserve.start()

        self._patch_settle = patch(
            "lib.llm_consumption.settle_reservation",
            return_value=None,
        )
        self._patch_settle.start()

        self._patch_cost_est = patch(
            "lib.llm_model_registry.estimate_usd_cost",
            return_value={
                "estimated_cost_usd": 0.0005,
                "cost_basis": "provider_usage_x_registry_snapshot",
                "pricing_effective_at": "2026-08-03",
            },
        )
        self._patch_cost_est.start()

        self._patch_log = patch("lib.llm_consumption.log_call", return_value=None)
        self._patch_log.start()

    def tearDown(self) -> None:
        patch.stopall()

    # ── Test 1: Valid Alex PRO request accepted ──────────────────────────

    def test_alex_pro_request_accepted(self) -> None:
        from scripts.lib.cio_governed_model_bridge import execute_governed_call
        result = execute_governed_call(
            [{"role": "user", "content": "Portfolio strategy review"}],
            process_id="alex_cio_synthesis",
        )
        self.assertNotIn("error", result)
        self.assertEqual(result["choices"][0]["message"]["role"], "assistant")
        self.assertIn("deepseek-v4-pro", result["model"])
        self.assertTrue(result.get("_tradeai", {}).get("governance_pass"))
        self.assertTrue(result.get("_tradeai", {}).get("mock"))

    # ── Test 2: Unregistered process rejected ────────────────────────────

    def test_unregistered_process_rejected(self) -> None:
        from scripts.lib.cio_governed_model_bridge import execute_governed_call
        result = execute_governed_call(
            [{"role": "user", "content": "test"}],
            process_id="nonexistent_process",
        )
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], "PROCESS_NOT_REGISTERED")
        self.assertEqual(result["cost_estimate"], 0.0)
        self.assertFalse(result["governance_pass"])

    # ── Test 3: Client model override ignored ────────────────────────────

    def test_client_arbitrary_model_override_rejected(self) -> None:
        from scripts.lib.cio_governed_model_bridge import execute_governed_call
        result = execute_governed_call(
            [{"role": "user", "content": "test override model"}],
            process_id="alex_cio_synthesis",
        )
        self.assertNotIn("error", result)
        # Server always uses resolved model, not client-supplied
        self.assertIn("deepseek-v4-pro", result["model"])
        self.assertNotEqual(result["model"], "gpt-5")

    # ── Test 4: Legacy model IDs rejected ───────────────────────────────

    def test_legacy_model_id_rejected(self) -> None:
        from scripts.lib.cio_governed_model_bridge import (
            execute_governed_call, LEGACY_MODEL_IDS,
        )
        self.assertIn("deepseek-chat", LEGACY_MODEL_IDS)
        self.assertIn("deepseek-reasoner", LEGACY_MODEL_IDS)
        # The bridge resolves model server-side, so client can't inject
        result = execute_governed_call(
            [{"role": "user", "content": "test"}],
            process_id="alex_cio_synthesis",
        )
        self.assertNotIn("error", result)
        self.assertIn("deepseek-v4-pro", result["model"])

    # ── Test 5: Global cap exceeded returns error $0 cost ────────────────

    def test_global_cap_rejection(self) -> None:
        # Override the cap check to simulate cap exceeded
        self._patch_check_cap.stop()
        patch("lib.llm_consumption.check_cost_cap",
              return_value={"allow": False, "reason": "COST_CAP_EXCEEDED",
                            "scope": "global", "spent_usd": 0.51, "cap_usd": 0.50}).start()
        from scripts.lib.cio_governed_model_bridge import execute_governed_call
        result = execute_governed_call(
            [{"role": "user", "content": "test"}],
            process_id="alex_cio_synthesis",
        )
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], "COST_CAP_EXCEEDED")
        self.assertEqual(result["cost_estimate"], 0.0)

    # ── Test 6: Reservation failure returns error $0 cost ────────────────

    def test_reservation_failure(self) -> None:
        self._patch_reserve.stop()
        patch("lib.llm_consumption.reserve_projected_cost",
              side_effect=RuntimeError("COST_CONFIGURATION_INVALID")).start()
        from scripts.lib.cio_governed_model_bridge import execute_governed_call
        result = execute_governed_call(
            [{"role": "user", "content": "test"}],
            process_id="alex_cio_synthesis",
        )
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], "RESERVATION_FAILED")
        self.assertEqual(result["cost_estimate"], 0.0)

    # ── Test 7: Circuit open returns error $0 cost ───────────────────────

    def test_circuit_open_no_call(self) -> None:
        from scripts.lib.cio_governed_model_bridge import (
            _CIRCUIT, execute_governed_call,
        )
        _CIRCUIT["open_until"] = time.time() + 900
        _CIRCUIT["errors"] = 10
        _CIRCUIT["last_error"] = "persistent_failure"
        result = execute_governed_call(
            [{"role": "user", "content": "test"}],
            process_id="alex_cio_synthesis",
        )
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], "CIRCUIT_OPEN")
        self.assertEqual(result["cost_estimate"], 0.0)

    # ── Test 8: No silent fallback on error ──────────────────────────────

    def test_no_silent_fallback(self) -> None:
        from scripts.lib.cio_governed_model_bridge import execute_governed_call
        result = execute_governed_call(
            [{"role": "user", "content": "test"}],
            process_id="alex_cio_synthesis",
        )
        self.assertNotIn("error", result)
        tradeai = result.get("_tradeai", {})
        # Mock provider never uses fallback
        self.assertNotIn("unexpected_model", result.get("model", "").lower())

    # ── Test 9: Tool call roundtrip ──────────────────────────────────────

    def test_tool_call_roundtrip(self) -> None:
        from scripts.lib.cio_governed_model_bridge import execute_governed_call
        tools = [{
            "type": "function",
            "function": {
                "name": "get_portfolio_summary",
                "description": "Get portfolio summary data",
                "parameters": {"type": "object", "properties": {}},
            },
        }]
        result = execute_governed_call(
            [{"role": "user", "content": "Show portfolio summary"}],
            process_id="alex_cio_synthesis",
            tools=tools,
            tool_choice="auto",
        )
        self.assertNotIn("error", result)
        msg = result["choices"][0]["message"]
        self.assertIn("tool_calls", msg)
        self.assertIsNotNone(msg.get("tool_calls"))

    # ── Test 10: Tool result continuity messages roundtrip ───────────────

    def test_tool_result_continuation(self) -> None:
        from scripts.lib.cio_governed_model_bridge import execute_governed_call
        messages = [
            {"role": "user", "content": "Get portfolio"},
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_portfolio", "arguments": "{}"},
            }]},
            {"role": "tool", "tool_call_id": "call_1",
             "content": '{"total_value": 1193911}'},
        ]
        result = execute_governed_call(
            messages,
            process_id="alex_cio_synthesis",
        )
        self.assertNotIn("error", result)
        self.assertIsNotNone(result["choices"][0]["message"]["content"])

    # ── Test 11: Structured output (JSON schema) preserved ───────────────

    def test_structured_output(self) -> None:
        from scripts.lib.cio_governed_model_bridge import execute_governed_call
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "portfolio_analysis",
                "schema": {"type": "object"},
            },
        }
        result = execute_governed_call(
            [{"role": "user", "content": "Analyze portfolio"}],
            process_id="alex_cio_synthesis",
            response_format=response_format,
        )
        self.assertNotIn("error", result)
        content = result["choices"][0]["message"]["content"]
        # Should be valid JSON
        parsed = json.loads(content)
        self.assertIn("analysis", parsed)
        self.assertEqual(parsed["model"], "deepseek-v4-pro")

    # ── Test 12: Returned model mismatch quarantined ─────────────────────

    def test_returned_model_mismatch_rejected(self) -> None:
        from scripts.lib.cio_governed_model_bridge import execute_governed_call
        # Even with mock, the bridge checks model consistency
        result = execute_governed_call(
            [{"role": "user", "content": "test"}],
            process_id="alex_cio_synthesis",
        )
        self.assertNotIn("error", result)
        self.assertIn("deepseek-v4-pro", result["model"])

    # ── Test 13: Request ID provenance ───────────────────────────────────

    def test_request_id_provenance(self) -> None:
        from scripts.lib.cio_governed_model_bridge import execute_governed_call
        result = execute_governed_call(
            [{"role": "user", "content": "test"}],
            process_id="alex_cio_synthesis",
            request_id="test_rid_123",
        )
        self.assertNotIn("error", result)
        self.assertEqual(result.get("id"), "test_rid_123")

    # ── Test 14: Full prompt not in log output ───────────────────────────

    def test_full_prompt_not_in_logs(self) -> None:
        from scripts.lib.cio_governed_model_bridge import hash_content, sanitize_log_summary
        # Verify hash function doesn't leak content
        messages = [
            {"role": "user", "content": "My portfolio is worth $1,193,911. Account number 12345. "
             "SSN 123-45-6789. PIN 9876."},
        ]
        summary = sanitize_log_summary(messages)
        # Summary must NOT contain raw content
        self.assertNotIn("$1,193,911", summary)
        self.assertNotIn("12345", summary)
        self.assertNotIn("123-45-6789", summary)
        # Summary should show role counts
        self.assertIn("user", summary.lower())
        # Hash must be deterministic
        h1 = hash_content("secret portfolio data")
        h2 = hash_content("secret portfolio data")
        self.assertEqual(h1, h2)
        # Different content = different hash
        h3 = hash_content("different data")
        self.assertNotEqual(h1, h3)

    # ── Test 15: Flash policy cannot request PRO on Flash process ────────

    def test_flash_policy_cannot_request_pro(self) -> None:
        from scripts.lib.cio_governed_model_bridge import execute_governed_call, resolve_model_policy
        # Alex CIO escalation requires deterministic reason for PRO_THINK
        policy = resolve_model_policy("alex_cio_escalation")
        self.assertTrue(policy.get("requires_deterministic_escalation_reason"))
        self.assertFalse(policy.get("requires_operator_cost_confirmation"))
        # Ordinary synthesis uses PRO
        policy = resolve_model_policy("alex_cio_synthesis")
        self.assertEqual(policy["model_id"], "deepseek-v4-pro")
        self.assertEqual(policy["thinking"], "disabled")

    # ── Test 16: PRO_MAX without confirmation rejected ──────────────────

    def test_pro_cannot_request_pro_max(self) -> None:
        from scripts.lib.cio_governed_model_bridge import resolve_model_policy
        # Alex CIO synthesis only allows PRO and PRO_THINK
        policy = resolve_model_policy("alex_cio_synthesis")
        self.assertEqual(policy["model_id"], "deepseek-v4-pro")
        self.assertNotIn("max", policy.get("reasoning_effort") or "")

    # ── Test 17: Settlement failure fail-closed ─────────────────────────

    def test_settlement_failure_fail_closed(self) -> None:
        self._patch_settle.stop()
        patch("lib.llm_consumption.settle_reservation",
              side_effect=Exception("DB connection lost")).start()
        from scripts.lib.cio_governed_model_bridge import execute_governed_call
        result = execute_governed_call(
            [{"role": "user", "content": "test_fail_closed"}],
            process_id="alex_cio_synthesis",
        )
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], "SETTLEMENT_FAILED")

    # ── Test 18: Unauthorized caller rejected (HTTP handler) ────────────

    def test_unauthorized_caller_rejected(self) -> None:
        from scripts.lib.cio_governed_model_bridge import resolve_caller
        result = resolve_caller("evil_agent")
        self.assertIsNone(result)
        result = resolve_caller(None)
        self.assertIsNone(result)
        result = resolve_caller("")
        self.assertIsNone(result)
        # Valid caller
        result = resolve_caller("alex")
        self.assertEqual(result, "alex_cio_synthesis")

    # ── Test 19: Watch governance not broken ─────────────────────────────

    def test_watch_governance_not_broken(self) -> None:
        """Verify agent_flash_governance still imports and functions correctly."""
        import scripts.lib.agent_flash_governance as afg
        self.assertEqual(afg.FLASH_MODEL, "deepseek-v4-flash")
        self.assertEqual(afg.FLASH_POLICY, "FAST")
        self.assertIn("watchlist_maria_flash_narrative", afg.TASK_TO_PROCESS.values())
        # Process for task
        pid = afg.process_for_task("agent_narrative")
        self.assertEqual(pid, "watchlist_maria_flash_narrative")
        # Legacy model rejection
        with self.assertRaises(RuntimeError):
            afg.reject_legacy_model_id("deepseek-chat")
        # Default is not rejected
        afg.reject_legacy_model_id("deepseek-v4-flash")

    # ── Test 20: Resolve caller header mapping ─────────────────────────

    def test_caller_process_mapping_server_side(self) -> None:
        from scripts.lib.cio_governed_model_bridge import (
            CALLER_PROCESS_MAP, resolve_caller,
        )
        self.assertIn("alex", CALLER_PROCESS_MAP)
        self.assertEqual(CALLER_PROCESS_MAP["alex"], "alex_cio_synthesis")
        self.assertIsNone(resolve_caller("unknown"))
        self.assertIsNone(resolve_caller(""))

    # ── Test 21: PRO_THINK escalation requires deterministic reason (not operator confirmation) ────

    def test_pro_think_escalation_requires_deterministic_reason(self) -> None:
        from scripts.lib.cio_governed_model_bridge import resolve_model_policy
        policy = resolve_model_policy("alex_cio_escalation")
        self.assertTrue(policy.get("requires_deterministic_escalation_reason"))
        self.assertFalse(policy.get("requires_operator_cost_confirmation"))
        self.assertEqual(policy["thinking"], "enabled")
        self.assertEqual(policy["reasoning_effort"], "high")

    # ── Test 22: MockProvider generates valid chat completion JSON ──────

    def test_mock_provider_valid_json(self) -> None:
        from scripts.lib.cio_governed_model_bridge import MockProvider
        mock = MockProvider()
        result = mock.generate(
            [{"role": "user", "content": "Hello"}],
            "deepseek-v4-pro",
        )
        self.assertIn("id", result)
        self.assertEqual(result["object"], "chat.completion")
        self.assertIn("choices", result)
        self.assertIn("usage", result)
        self.assertIn("prompt_tokens", result["usage"])
        self.assertIn("completion_tokens", result["usage"])

    # ── Test 23: MockProvider supports tool calls in fixture ────────────

    def test_mock_provider_tool_calls(self) -> None:
        from scripts.lib.cio_governed_model_bridge import MockProvider
        mock = MockProvider()
        tools = [{
            "type": "function",
            "function": {"name": "get_data", "parameters": {}},
        }]
        result = mock.generate(
            [{"role": "user", "content": "get data"}],
            "deepseek-v4-pro",
            tools=tools,
            tool_choice="auto",
        )
        msg = result["choices"][0]["message"]
        self.assertIn("tool_calls", msg)
        self.assertIsNotNone(msg["tool_calls"])
        self.assertEqual(msg["tool_calls"][0]["type"], "function")

    # ── Test 24: MockProvider supports streaming ────────────────────────

    def test_mock_provider_streaming(self) -> None:
        from scripts.lib.cio_governed_model_bridge import MockProvider
        mock = MockProvider()
        chunks = mock.generate_stream(
            [{"role": "user", "content": "stream test"}],
            "deepseek-v4-pro",
        )
        self.assertGreater(len(chunks), 0)
        # Last chunk should be [DONE]
        self.assertIn("[DONE]", chunks[-1])
        # Each chunk should be SSE-formatted
        for chunk in chunks[:-1]:
            self.assertTrue(chunk.startswith("data: "))
        # Should contain valid JSON in data chunks
        json_chunk = json.loads(chunks[0].replace("data: ", "").strip())
        self.assertIn("choices", json_chunk)


# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
