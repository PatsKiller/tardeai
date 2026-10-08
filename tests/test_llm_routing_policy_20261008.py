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
