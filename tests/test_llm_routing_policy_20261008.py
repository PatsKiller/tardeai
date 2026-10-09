"""W4 routing policy: one row per process, typed refusals, receipt join, semaphore size.

Hermetic. Health and balance paths point at files that do not exist unless a test
writes them. No provider network call. The bridge binds 127.0.0.1 port 0 only.
"""

from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_governed_model_bridge as bridge  # noqa: E402

KNOWN_LANE_POLICIES = frozenset({"PRO", "FAST", "PRO_THINK", "FAST_THINK"})
ROW_KEYS = frozenset(
    {
        "primary",
        "secondary",
        "fallback",
        "health_gate",
        "latency_budget_ms",
        "cost_ceiling_usd",
    }
)


def _load(name: str) -> dict:
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@pytest.fixture(autouse=True)
def hermetic_routing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("TRADEAI_LLM_PROVIDER_HEALTH", str(tmp_path / "absent-health.json"))
    monkeypatch.setenv("TRADEAI_DEEPSEEK_BALANCE_HISTORY", str(tmp_path / "absent-balance.jsonl"))
    monkeypatch.delenv("TRADEAI_LLM_ROUTING_POLICY", raising=False)
    monkeypatch.setattr(bridge, "BIND_MODE", "mock")
    bridge._reset_circuit()

    def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    for target in ("model_chooser.apply", "scripts.lib.model_chooser.apply"):
        try:
            monkeypatch.setattr(target, _noop)
        except (AttributeError, ModuleNotFoundError, ImportError):
            continue
    yield
    bridge._reset_circuit()


def _registered(process_id: str) -> dict:
    return {
        "process_id": process_id,
        "registered": True,
        "mode": "automated",
        "deepseek_allowed_policies": ["PRO", "PRO_THINK", "FAST", "FAST_THINK"],
        "max_input_tokens": 32000,
        "max_output_tokens": 16384,
        "daily_soft_cap": 40,
        "daily_cost_cap_usd": 1.0,
    }


@contextmanager
def _governed(monkeypatch: pytest.MonkeyPatch, *, reserve_id: int = 4242):
    """Patch the consumption path so a test cannot reserve against the live ledger."""
    reserve = MagicMock(return_value=reserve_id)
    monkeypatch.setattr("lib.llm_consumption.get_process_config", lambda pid: _registered(pid))
    monkeypatch.setattr("lib.llm_consumption.reserve_projected_cost", reserve)
    monkeypatch.setattr("lib.llm_consumption.settle_reservation", MagicMock(return_value=None))
    monkeypatch.setattr("lib.llm_consumption.check_cost_cap", lambda *a, **k: {"allow": True})
    monkeypatch.setattr(
        "lib.llm_consumption.calibrated_projected_usd",
        lambda *_a, **_k: {"projected_usd": 0.002, "basis": "test"},
    )
    monkeypatch.setattr("lib.llm_consumption.log_call", MagicMock(return_value=None))
    monkeypatch.setattr("lib.llm_model_registry.reject_legacy_model_id", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "lib.llm_model_registry.estimate_usd_cost",
        lambda *_a, **_k: {
            "estimated_cost_usd": 0.0005,
            "cost_basis": "provider_usage_x_registry_snapshot",
            "pricing_effective_at": "2026-10-08",
        },
    )
    monkeypatch.setattr("lib.consumption_run_manual.validate_paid_cap_config", lambda *_a, **_k: None)
    monkeypatch.setattr("lib.consumption_run_manual.projected_max_cost_usd", lambda *_a, **_k: 0.002)
    yield reserve


def test_one_policy_row_per_registered_process() -> None:
    registry = _load("llm_process_registry.json")
    policy = _load("llm_routing_policy.json")
    assert policy["schema"] == "LlmRoutingPolicy@v1"
    assert policy["default_policy_id"] == "default"
    rows = policy["policies"]["default"]["processes"]
    registered = {row["id"] for row in registry["processes"]}
    assert set(rows) == registered
    assert len(rows) == len(registered)
    for row in rows.values():
        assert ROW_KEYS <= set(row)
        assert isinstance(row["health_gate"], bool)
        assert _number(row["latency_budget_ms"])
        assert _number(row["cost_ceiling_usd"])
        for lane in ("primary", "secondary", "fallback"):
            spec = row[lane]
            assert spec["policy"] in KNOWN_LANE_POLICIES
            assert isinstance(spec["provider"], str) and spec["provider"]


def test_named_processes_keep_today_requested_policy() -> None:
    synthesis = bridge.resolve_model_policy("alex_cio_synthesis")
    assert synthesis is not None and "refused" not in synthesis
    assert synthesis["requested_policy"] == "PRO"
    assert synthesis["provider"] == "deepseek"
    assert synthesis["model_id"]
    assert synthesis["routing_decision"]["reason"] == "health_unknown"

    escalation = bridge.resolve_model_policy("alex_cio_escalation")
    assert escalation["requested_policy"] == "PRO_THINK"
    assert escalation["thinking"] == "enabled"
    assert escalation["provider"] == "deepseek"

    digest = bridge.resolve_model_policy("n8n_material_digest_draft")
    assert digest["requested_policy"] == "FAST"
    assert digest["provider"] == "deepseek"

    smoke = bridge.resolve_model_policy("deepseek_flash_operator_smoke")
    assert smoke["requested_policy"] == "FAST"
    assert smoke["provider"] == "deepseek"
    assert bridge.resolve_model_policy("unknown_process") is None


def test_routing_header_matches_gateway_and_blank_selects_default() -> None:
    from scripts.lib.n8n_model_job import ROUTING_POLICY_HEADER

    assert bridge.ROUTING_POLICY_HEADER == ROUTING_POLICY_HEADER == "X-TradeAI-Routing-Policy"
    assert bridge.normalize_routing_policy_header(None) == "default"
    assert bridge.normalize_routing_policy_header("   ") == "default"
    assert bridge.routing_policy_known(None) is True
    assert bridge.routing_policy_known("") is True
    assert bridge.routing_policy_known("not-a-real-policy") is False


def test_unknown_routing_policy_refuses_before_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    generate = MagicMock(side_effect=AssertionError("provider must not be called"))
    monkeypatch.setattr(bridge.MockProvider, "generate", generate)
    monkeypatch.setattr(bridge.RealProvider, "generate", generate)
    with _governed(monkeypatch) as reserve:
        result = bridge.execute_governed_call(
            [{"role": "user", "content": "should not run"}],
            process_id="alex_cio_synthesis",
            routing_policy="not-a-real-policy",
        )
    assert result["error"]["code"] == "unknown_routing_policy"
    assert result["error"]["status"] == 400
    assert result["routing_decision"]["policy_id"] == "not-a-real-policy"
    assert result["routing_decision"]["reason"] == "unknown_routing_policy"
    assert result["routing_decision"]["lane_chosen"] is None
    assert generate.call_count == 0
    assert reserve.call_count == 0


def test_unknown_header_on_loopback_refuses_before_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    generate = MagicMock(side_effect=AssertionError("provider must not be called"))
    monkeypatch.setattr(bridge.MockProvider, "generate", generate)
    monkeypatch.setattr(bridge.RealProvider, "generate", generate)
    server = bridge.start_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = int(server.server_address[1])
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        body = json.dumps({"messages": [{"role": "user", "content": "x"}]}).encode("utf-8")
        conn.request(
            "POST",
            "/v1/chat/completions",
            body=body,
            headers={
                "Content-Type": "application/json",
                "X-TradeAI-Agent": "alex",
                "X-TradeAI-Routing-Policy": "not-a-real-policy",
            },
        )
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert response.status == 400
    assert payload["error"]["code"] == "unknown_routing_policy"
    assert payload["routing_decision"]["reason"] == "unknown_routing_policy"
    assert generate.call_count == 0


def test_unhealthy_primary_without_healthy_fallback_does_not_call_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    health = {
        "checked_at": "2026-10-08T16:00:00Z",
        "window_hours": 3,
        "worst_severity": "CRITICAL",
        "findings": [
            {
                "lane": "deepseek-flash",
                "kind": "BILLING",
                "severity": "CRITICAL",
                "calls": 1,
                "failures": 1,
                "recovered": False,
            }
        ],
    }
    (tmp_path / "health.json").write_text(json.dumps(health), encoding="utf-8")
    balance = {"schema": "DeepSeekBalanceSnapshot@v1", "is_available": False, "total_balance": 0}
    (tmp_path / "balance.jsonl").write_text(json.dumps(balance) + "\n", encoding="utf-8")
    monkeypatch.setenv("TRADEAI_LLM_PROVIDER_HEALTH", str(tmp_path / "health.json"))
    monkeypatch.setenv("TRADEAI_DEEPSEEK_BALANCE_HISTORY", str(tmp_path / "balance.jsonl"))
    generate = MagicMock(side_effect=AssertionError("provider must not be called"))
    monkeypatch.setattr(bridge.MockProvider, "generate", generate)
    monkeypatch.setattr(bridge.RealProvider, "generate", generate)
    with _governed(monkeypatch) as reserve:
        result = bridge.execute_governed_call(
            [{"role": "user", "content": "should not run"}],
            process_id="alex_cio_synthesis",
        )
    assert result["error"]["code"] == "lane_unhealthy"
    assert result["error"]["status"] == 503
    decision = result["routing_decision"]
    assert set(decision) >= {"policy_id", "lane_chosen", "reason", "health_snapshot"}
    assert decision["policy_id"] == "default"
    assert decision["lane_chosen"] is None
    assert decision["reason"] == "lane_unhealthy"
    assert decision["health_snapshot"]["lanes"]["deepseek"] == "unhealthy"
    assert generate.call_count == 0
    assert reserve.call_count == 0


def test_pytest_ignores_the_host_health_file_unless_the_env_points_at_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRADEAI_LLM_PROVIDER_HEALTH", raising=False)
    monkeypatch.delenv("TRADEAI_DEEPSEEK_BALANCE_HISTORY", raising=False)
    live = bridge._PROJECT_ROOT / "data" / "runtime" / "llm_provider_health.json"
    assert bridge.provider_health_path() != live
    ignored = bridge.select_governed_lane("alex_cio_synthesis")
    assert ignored.get("refused") is None
    assert ignored["policy"]["requested_policy"] == "PRO"
    assert ignored["routing_decision"]["reason"] == "health_unknown"
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert bridge.provider_health_path() == live


def test_success_receipt_joins_routing_decision_to_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    from lib.provider_cost.context import cost_attribution as real_attribution

    seen: dict[str, object] = {}

    @contextmanager
    def _spy(**kwargs: object):
        seen.update(kwargs)
        with real_attribution(**kwargs):
            yield

    monkeypatch.setattr("lib.provider_cost.context.cost_attribution", _spy)
    real_generate = bridge.MockProvider.generate
    mock_calls = {"n": 0}

    def _counting(self: bridge.MockProvider, *args: object, **kwargs: object) -> dict:
        mock_calls["n"] += 1
        return real_generate(self, *args, **kwargs)

    monkeypatch.setattr(bridge.MockProvider, "generate", _counting)
    real_calls = MagicMock(side_effect=AssertionError("real provider must not be called"))
    monkeypatch.setattr(bridge.RealProvider, "generate", real_calls)
    with _governed(monkeypatch, reserve_id=4242):
        result = bridge.execute_governed_call(
            [{"role": "user", "content": "portfolio context"}],
            process_id="alex_cio_synthesis",
        )
    assert "error" not in result
    decision = result["_tradeai"]["routing_decision"]
    assert decision["policy_id"] == "default"
    assert decision["lane_chosen"] == "primary"
    assert decision["reason"] == "health_unknown"
    assert isinstance(decision["health_snapshot"], dict)
    assert result["_tradeai"]["reservation_id"] == 4242
    assert decision["reservation_id"] == 4242
    assert str(seen["reservation_id"]) == "4242"
    assert mock_calls["n"] == 1
    assert real_calls.call_count == 0
    sem = bridge.provider_semaphore("deepseek", "default")
    assert sem._value == sem._initial_value


def test_provider_semaphore_releases_when_generate_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(self: bridge.MockProvider, *_args: object, **_kwargs: object) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(bridge.MockProvider, "generate", _boom)
    with _governed(monkeypatch):
        result = bridge.execute_governed_call(
            [{"role": "user", "content": "portfolio context"}],
            process_id="alex_cio_synthesis",
        )
    assert result["error"]["code"] == "PROVIDER_ERROR"
    assert result["routing_decision"]["policy_id"] == "default"
    sem = bridge.provider_semaphore("deepseek", "default")
    assert sem._value == sem._initial_value


def test_stream_resolves_once_and_streams_the_governed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-10-09 (audit B, H1): the stream path no longer re-resolves or calls a provider a second time.

    Before, a refusal that appeared only on a second resolve was answered as typed JSON; that second resolve
    existed only to feed a second, unreserved provider call. Now the policy is resolved once, inside the
    governed call, and a later lane flip cannot reach the stream at all.
    """
    calls = {"n": 0}
    real = bridge.resolve_model_policy

    def _flip(process_id: str, task_type: str = "", routing_policy: str | None = None):
        calls["n"] += 1
        if calls["n"] == 1:
            return real(process_id, task_type, routing_policy)
        return {"refused": "lane_unhealthy", "refused_status": 503, "refused_message": "flipped"}

    monkeypatch.setattr(bridge, "resolve_model_policy", _flip)
    stream = MagicMock(side_effect=AssertionError("stream cannot call a provider again"))
    original_generate = bridge.MockProvider.generate
    generate = MagicMock(side_effect=lambda self, *a, **k: original_generate(self, *a, **k))
    monkeypatch.setattr(bridge.MockProvider, "generate", lambda self, *a, **k: generate(self, *a, **k))
    monkeypatch.setattr(bridge.MockProvider, "generate_stream", stream)
    monkeypatch.setattr(bridge.RealProvider, "generate", MagicMock(side_effect=AssertionError("real provider")))
    server = bridge.start_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with _governed(monkeypatch):
            port = int(server.server_address[1])
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            body = json.dumps({"stream": True, "messages": [{"role": "user", "content": "x"}]}).encode("utf-8")
            conn.request(
                "POST",
                "/v1/chat/completions",
                body=body,
                headers={"Content-Type": "application/json", "X-TradeAI-Agent": "alex"},
            )
            response = conn.getresponse()
            parts = []
            while True:
                line = response.readline()
                parts.append(line)
                if line.strip() == b"data: [DONE]" or not line:
                    break
            raw = b"".join(parts)
            content_type = response.getheader("Content-Type")
            conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    frames = [
        json.loads(line[6:])
        for line in raw.decode("utf-8").splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    assert response.status == 200
    assert content_type == "text/event-stream"
    assert frames[-1]["_tradeai"]["routing_decision"]["lane_chosen"] == "primary"
    assert frames[-1]["_tradeai"]["reservation_id"] == 4242
    assert calls["n"] == generate.call_count == 1
    assert stream.call_count == 0
    assert raw.count(b"data: [DONE]") == 1


def _fresh_recovered_health(provider: str = "grok") -> dict:
    from datetime import datetime, timezone

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": 3,
        "worst_severity": "OK",
        "findings": [{"lane": provider, "recovered": True, "calls": 4, "failures": 1}],
    }


@pytest.mark.parametrize(
    "process_id",
    ["maria_research_critique", "portfolio_ai_analyst", "watchlist_agent_oauth_fallback"],
)
def test_explicit_no_fallback_refuses_before_reservation_and_provider(
    monkeypatch: pytest.MonkeyPatch, process_id: str
) -> None:
    policy = _load("llm_routing_policy.json")["policies"]["default"]["processes"][process_id]
    primary = policy["primary"]["provider"]
    lanes = {spec["provider"]: "healthy" for key, spec in policy.items() if key in {"primary", "secondary", "fallback"}}
    lanes[primary] = "unhealthy"
    monkeypatch.setattr(bridge, "read_health_snapshot", lambda _: {"lanes": lanes})
    generate = MagicMock(side_effect=AssertionError("no-fallback process must not call a provider"))
    monkeypatch.setattr(bridge.MockProvider, "generate", generate)
    monkeypatch.setattr(bridge.RealProvider, "generate", generate)
    with _governed(monkeypatch) as reserve:
        result = bridge.execute_governed_call([{"role": "user", "content": "hermetic fixture"}], process_id=process_id)
    assert result["error"]["code"] == "lane_unhealthy"
    assert result["error"]["status"] == 503
    assert result["routing_decision"]["lane_chosen"] is None
    assert reserve.call_count == generate.call_count == 0


@pytest.mark.parametrize("fallback_allowed", [True, None])
def test_fallback_authority_preserves_explicit_grant_and_default_false(
    monkeypatch: pytest.MonkeyPatch, fallback_allowed: bool | None
) -> None:
    from lib import llm_consumption

    row = dict(llm_consumption._registry_process("maria_research_critique"))
    if fallback_allowed is None:
        row.pop("fallback_allowed")
    else:
        row["fallback_allowed"] = fallback_allowed
    monkeypatch.setattr(llm_consumption, "_registry_process", lambda _: row)
    monkeypatch.setattr(
        bridge,
        "read_health_snapshot",
        lambda _: {"lanes": {"deepseek": "unhealthy", "grok": "healthy"}},
    )
    result = bridge.select_governed_lane("maria_research_critique")
    if fallback_allowed is True:
        assert result["policy"]["provider"] == "grok"
        assert result["routing_decision"]["lane_chosen"] == "secondary"
    else:
        assert result["refused"] == "lane_unhealthy"
        assert result["routing_decision"]["lane_chosen"] is None


@pytest.mark.parametrize("clock", ["missing", "malformed", "naive", "future", "stale"])
def test_unproven_health_clock_cannot_qualify_an_alternate(clock: str) -> None:
    from datetime import datetime, timedelta, timezone

    health = _fresh_recovered_health()
    now = datetime.now(timezone.utc)
    if clock == "missing":
        health.pop("checked_at")
    elif clock == "malformed":
        health["checked_at"] = "not-a-clock"
    elif clock == "naive":
        health["checked_at"] = now.replace(tzinfo=None).isoformat()
    elif clock == "future":
        health["checked_at"] = (now + timedelta(hours=1)).isoformat()
    else:
        health["checked_at"] = (now - timedelta(hours=2)).isoformat()
        health["window_hours"] = 10000  # The writer lookback is never a freshness TTL.
    assert bridge._provider_health_status("grok", health, "present", None, "missing") == "unknown"


@pytest.mark.parametrize("provider", ["grok", "deepseek", "chatgpt"])
def test_global_health_receipt_without_attributable_recovery_is_unknown(provider: str) -> None:
    health = _fresh_recovered_health("other-provider")
    assert bridge._provider_health_status(provider, health, "present", None, "missing") == "unknown"
    health["findings"] = []
    assert bridge._provider_health_status(provider, health, "present", None, "missing") == "unknown"


@pytest.mark.parametrize("calls,failures", [(True, 0), (4, True), (3, 1), (4, 0), (2, 4), ("4", 1)])
def test_recovered_finding_requires_the_producer_success_count(calls: object, failures: object) -> None:
    health = _fresh_recovered_health()
    health["findings"][0].update(calls=calls, failures=failures)
    assert bridge._provider_health_status("grok", health, "present", None, "missing") == "unknown"


@pytest.mark.parametrize("lane", ["not-grok", "grokish", "other-grok-wrapper"])
def test_unattributable_provider_name_cannot_qualify_an_alternate(lane: str) -> None:
    health = _fresh_recovered_health(lane)
    assert bridge._provider_health_status("grok", health, "present", None, "missing") == "unknown"


@pytest.mark.parametrize("cadence", [0, -1, True, float("nan"), float("inf"), None])
def test_health_requires_finite_positive_declared_cadence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cadence: object
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "lane_registry.json").write_text(
        json.dumps({"lanes": [{"lane_id": "llm-provider-health", "expected_cadence_hours": cadence}]}), encoding="utf-8"
    )
    monkeypatch.setattr(bridge, "_PROJECT_ROOT", tmp_path)
    health = _fresh_recovered_health()
    assert bridge._provider_health_status("grok", health, "present", None, "missing") == "unknown"


def test_fresh_attributable_recovery_is_healthy_but_indictment_wins() -> None:
    health = _fresh_recovered_health()
    assert bridge._provider_health_status("grok", health, "present", None, "missing") == "healthy"
    health["findings"].append({"lane": "grok", "kind": "AUTH", "severity": "CRITICAL", "recovered": False})
    assert bridge._provider_health_status("grok", health, "present", None, "missing") == "unhealthy"


def _settled_messages_from_sse(frames: list[dict]) -> dict[int, dict]:
    messages = {}
    for frame in frames:
        for choice in frame["choices"]:
            message = messages.setdefault(choice["index"], {})
            for key, value in choice["delta"].items():
                if key in {"content", "reasoning_content"} and isinstance(value, str):
                    message[key] = (message.get(key) or "") + value
                else:
                    message[key] = value
    return messages


@pytest.mark.parametrize("mode", ["mock", "canary"])
def test_stream_reuses_accounted_result_without_resolve_or_provider(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    import io

    result = {
        "id": "settled-fixture",
        "object": "chat.completion",
        "created": 1,
        "model": "deepseek-flash",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "exact  whitespace\nUnicode: café",
                    "reasoning_content": "reason",
                    "tool_calls": [
                        {"id": "tool-1", "type": "function", "function": {"name": "fixture", "arguments": "{}"}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        "_tradeai": {"reservation_id": 4242, "routing_decision": {"provider": "deepseek", "lane_chosen": "primary"}},
    }
    resolve = MagicMock(return_value={"provider": "grok", "model_id": "deepseek-flash"})
    generate = MagicMock(side_effect=AssertionError("stream cannot make an unaccounted second call"))
    monkeypatch.setattr(bridge, "BIND_MODE", mode)
    monkeypatch.setattr(bridge, "resolve_model_policy", resolve)
    monkeypatch.setattr(bridge.RealProvider, "generate", generate)
    monkeypatch.setattr(bridge.MockProvider, "generate_stream", generate)
    handler = MagicMock()
    handler.wfile = io.BytesIO()
    bridge.GovernedBridgeHandler._send_stream(handler, result, [], "alex_cio_synthesis", None, 10)
    assert resolve.call_count == generate.call_count == 0
    handler.send_response.assert_called_once_with(200)
    handler._send_json.assert_not_called()
    raw = handler.wfile.getvalue().decode("utf-8")
    frames = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
    assert raw.count("data: [DONE]") == 1
    assert all(frame["id"] == result["id"] for frame in frames)
    messages = _settled_messages_from_sse(frames)
    expected = dict(result["choices"][0]["message"])
    expected["tool_calls"] = [{**call, "index": index} for index, call in enumerate(expected["tool_calls"])]
    assert messages == {0: expected}
    assert frames[-1]["choices"][0]["finish_reason"] == "tool_calls"
    assert frames[-1]["usage"] == result["usage"]
    assert frames[-1]["_tradeai"] == result["_tradeai"]


def test_stream_error_is_typed_json_before_any_success_header(monkeypatch: pytest.MonkeyPatch) -> None:
    error = {"error": {"code": "provider_not_configured", "message": "fixture", "status": 503}}
    monkeypatch.setattr(
        bridge, "resolve_model_policy", MagicMock(return_value={"provider": "grok", "model_id": "deepseek-flash"})
    )
    handler = MagicMock()
    bridge.GovernedBridgeHandler._send_stream(handler, error, [], "alex_cio_synthesis", None, 10)
    handler._send_json.assert_called_once_with(503, error)
    handler.send_response.assert_not_called()


@pytest.mark.parametrize(
    "choices",
    [
        [],
        [
            {
                "index": 2,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "tool-only", "type": "function", "function": {"name": "fixture", "arguments": "{}"}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        [
            {"index": 3, "message": {"content": ""}, "finish_reason": "stop"},
            {"index": 7, "message": {"content": "second"}, "finish_reason": "length"},
        ],
    ],
)
def test_stream_preserves_empty_tool_only_and_multiple_choices(choices: list) -> None:
    import io

    result = {
        "id": "fixture",
        "created": 1,
        "model": "deepseek-flash",
        "choices": choices,
        "usage": {"total_tokens": 3},
        "_tradeai": {"reservation_id": 1},
    }
    handler = MagicMock()
    handler.wfile = io.BytesIO()
    bridge.GovernedBridgeHandler._send_stream(handler, result, [], "alex_cio_synthesis", None, 10)
    raw = handler.wfile.getvalue().decode("utf-8")
    frames = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
    assert raw.count("data: [DONE]") == 1
    assert [choice["index"] for choice in frames[0]["choices"]] == [choice["index"] for choice in choices]
    assert [choice["finish_reason"] for choice in frames[-1]["choices"]] == [
        choice["finish_reason"] for choice in choices
    ]
    expected_messages = {}
    for choice in choices:
        message = dict(choice["message"])
        if "tool_calls" in message:
            message["tool_calls"] = [{**call, "index": index} for index, call in enumerate(message["tool_calls"])]
        expected_messages[choice["index"]] = message
    assert _settled_messages_from_sse(frames) == expected_messages
    assert frames[-1]["usage"] == result["usage"]
    assert frames[-1]["_tradeai"] == result["_tradeai"]


def test_stream_preserves_zero_created_in_settled_result() -> None:
    result = {"id": "zero-time", "created": 0, "model": "fixture", "choices": [], "usage": {}}
    frames = [json.loads(chunk[6:]) for chunk in bridge.governed_result_sse_chunks(result) if chunk != "data: [DONE]\n\n"]
    assert all(frame["created"] == 0 for frame in frames)


def test_initial_unconfigured_provider_refusal_never_starts_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge, "BIND_MODE", "canary")
    monkeypatch.setattr(
        bridge,
        "resolve_model_policy",
        lambda *a, **k: {"provider": "grok", "model_id": "deepseek-flash", "requested_policy": "FAST"},
    )
    generate = MagicMock(side_effect=AssertionError("unconfigured provider must not run"))
    monkeypatch.setattr(bridge.RealProvider, "generate", generate)
    with _governed(monkeypatch) as reserve:
        result = bridge.execute_governed_call(
            [{"role": "user", "content": "fixture"}], process_id="alex_cio_synthesis", stream=True
        )
    assert result["error"]["code"] == "provider_not_configured"
    assert reserve.call_count == generate.call_count == 0


def test_semaphore_size_is_the_configured_integer() -> None:
    policy = _load("llm_routing_policy.json")
    configured = policy["policies"]["default"]["provider_concurrency"]["deepseek"]
    assert isinstance(configured, int)
    assert configured != 32
    assert bridge.provider_slot_limit("deepseek") == configured
    sem = bridge.provider_semaphore("deepseek")
    assert sem._initial_value == configured
    assert bridge.provider_slot_limit("not-a-configured-provider") == 1
    missing = bridge.provider_semaphore("not-a-configured-provider")
    assert missing._initial_value == 1
    assert 32 not in policy["policies"]["default"]["provider_concurrency"].values()
