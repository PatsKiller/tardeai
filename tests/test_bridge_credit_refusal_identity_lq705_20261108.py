"""INC-261108-hvtspn: a credit-cap refusal must name its process and reach llm_consumption_log.

Two defects, one incident:

* ``walk_routes`` called the class-level ``FundingContext.record_fallback`` with no process id, so
  every Anthropic fallback row in ``anthropic_credit.jsonl`` read ``process: unknown:<pid>`` — the
  journal could not say which governed process had been refused.
* the no-answer branch of ``execute_governed_call`` settled the reservation and returned
  ``PROVIDER_ERROR`` without ever calling ``lc.log_call``; only Step 9b/Step 11 log, and neither
  runs when no lane serves. A repeated CREDIT_PROCESS_CAP therefore never appeared in
  ``llm_consumption_log`` and every spend/health reader saw a silent lane.

Synthetic providers and a tmp PROJECT_ROOT: no DB, no network, no credential value.
"""
import json
from unittest.mock import MagicMock

from tests.test_anthropic_bridge_20261025 import (  # noqa: F401 -- activates the autouse fixture
    Provider, activated_fixture_promotion,
)
from tests.test_bridge_oauth_llm_step_20261014 import DIAG, bridge, hermetic, wire  # noqa: F401
from tests.test_n8n_oauth_first_routing_20261015 import ledger

JOURNAL = "data/runtime/provider_cost/anthropic_credit.jsonl"
LANES = ("anthropic", "grok", "chatgpt", "deepseek")


def _configure(monkeypatch, anthropic_code, other_code):
    """Route the real bridge over injected providers; only anthropic_first is forced."""
    from lib.anthropic_transport import AnthropicError

    base = __import__("lib.llm_consumption", fromlist=["get_process_config"])
    cfg = base.get_process_config(DIAG)
    cfg.update(anthropic_first=True, allowed_lanes=["anthropic", "grok", "chatgpt", "fast"])
    monkeypatch.setattr(base, "get_process_config", lambda _pid: cfg)
    monkeypatch.setattr(base, "reprice_reservation", MagicMock())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key-not-a-credential")
    bridge.set_transport_override("anthropic", Provider(fail=AnthropicError(anthropic_code)))
    for name in LANES[1:]:
        bridge.set_transport_override(name, Provider(fail=AnthropicError(other_code)))


def _run(monkeypatch, tmp_path, *, anthropic_code, other_code):
    with ledger(monkeypatch) as led:
        _configure(monkeypatch, anthropic_code, other_code)
        try:
            result = bridge.execute_governed_call(
                [{"role": "user", "content": "synthetic"}], process_id=DIAG)
        finally:
            for name in LANES:
                bridge.set_transport_override(name, None)
        rows = []
        path = tmp_path / JOURNAL
        if path.exists():
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        return result, led, rows


def test_credit_cap_fallback_row_names_the_governed_process_not_unknown_pid(monkeypatch, tmp_path):
    result, _, rows = _run(monkeypatch, tmp_path,
                           anthropic_code="CREDIT_PROCESS_CAP", other_code="RATE_LIMITED")
    assert result.get("error", {}).get("code") == "PROVIDER_ERROR", result
    fallbacks = [row for row in rows if row.get("event") == "fallback"]
    assert [row["reason"] for row in fallbacks] == ["CREDIT_PROCESS_CAP"]
    assert fallbacks[0]["process"] == fallbacks[0]["process_id"] == DIAG
    assert not any(str(row.get("process", "")).startswith("unknown:") for row in rows)


def test_credit_cap_refusal_is_written_as_a_consumption_failure(monkeypatch, tmp_path):
    _, led, _ = _run(monkeypatch, tmp_path,
                     anthropic_code="CREDIT_PROCESS_CAP", other_code="RATE_LIMITED")
    assert led["log_call"].called, "a refused call left no llm_consumption_log row"
    call = led["log_call"].call_args.kwargs
    assert call["success"] is False
    assert call["error_message"] == "CREDIT_PROCESS_CAP"
    assert call["process_id"] == DIAG
    assert call["cost_basis"] == "refused_before_send"
    assert call["metadata"]["credit_refusal"] == "CREDIT_PROCESS_CAP"


def test_a_non_credit_provider_failure_is_not_logged_as_a_consumption_failure(monkeypatch, tmp_path):
    result, led, _ = _run(monkeypatch, tmp_path,
                          anthropic_code="RATE_LIMITED", other_code="RATE_LIMITED")
    assert result.get("error", {}).get("code") == "PROVIDER_ERROR", result
    led["log_call"].assert_not_called()
