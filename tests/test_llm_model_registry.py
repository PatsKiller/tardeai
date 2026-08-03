"""Tests for canonical llm_model_registry + DeepSeek client contracts."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.llm_model_registry import (  # noqa: E402
    EXACT_DEEPSEEK_MODELS,
    LEGACY_DEEPSEEK_MODELS,
    RegistryError,
    estimate_usd_cost,
    load_registry,
    reject_legacy_model_id,
    resolve_lane_alias,
    resolve_logical_policy,
)
from lib import deepseek_client as dc  # noqa: E402


def test_registry_loads_and_has_exact_models():
    reg = load_registry()
    assert reg["version"] >= 1
    models = reg["providers"]["deepseek"]["models"]
    ids = {m["model_id"] for m in models.values()}
    assert ids == set(EXACT_DEEPSEEK_MODELS)
    for pol in ("FAST", "FAST_THINK", "PRO", "PRO_THINK", "PRO_MAX"):
        assert pol in reg["logical_policies"]


def test_logical_policy_maps_to_exact_ids():
    assert resolve_logical_policy("FAST")["model_id"] == "deepseek-v4-flash"
    assert resolve_logical_policy("FAST")["thinking"] == "disabled"
    assert resolve_logical_policy("FAST_THINK")["reasoning_effort"] == "high"
    assert resolve_logical_policy("PRO")["model_id"] == "deepseek-v4-pro"
    assert resolve_logical_policy("PRO_THINK")["model_id"] == "deepseek-v4-pro"
    with pytest.raises(RegistryError):
        resolve_logical_policy("PRO_MAX", operator_confirmed=False)
    assert resolve_logical_policy("PRO_MAX", operator_confirmed=True)["reasoning_effort"] == "max"


def test_unknown_policy_rejected():
    with pytest.raises(RegistryError):
        resolve_logical_policy("DEEPSEEK_V4")
    with pytest.raises(RegistryError):
        resolve_logical_policy("not_a_policy")


def test_legacy_model_ids_rejected():
    for mid in LEGACY_DEEPSEEK_MODELS:
        with pytest.raises(RegistryError):
            reject_legacy_model_id(mid)


def test_lane_aliases():
    assert resolve_lane_alias("deepseek-flash") == "FAST"
    assert resolve_lane_alias("deepseek-v4-flash") == "FAST"
    assert resolve_lane_alias("deepseek-v4-pro") == "PRO"
    assert resolve_lane_alias("FAST_THINK") == "FAST_THINK"


def test_cost_estimate_uses_tokens_not_chars():
    est = estimate_usd_cost(
        model_id="deepseek-v4-flash",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
        cache_miss_tokens=1_000_000,
    )
    # 0.14 + 0.28 = 0.42 per snapshot
    assert est["estimated_cost_usd"] == pytest.approx(0.42, rel=1e-6)
    assert est["cost_basis"] == "provider_usage_x_registry_snapshot"


def test_available_unknown_lane_false():
    import llm_lane
    assert llm_lane.available("not-a-real-lane") is False
    assert llm_lane.available("") is False


def test_generate_unknown_lane_no_silent_gemma():
    import llm_lane
    with pytest.raises(RuntimeError, match="UNKNOWN_LANE"):
        llm_lane.generate("hi", lane="mystery-provider", _skip_consumption=True)


def test_generate_rejects_legacy_model_override():
    import llm_lane
    with pytest.raises(RuntimeError, match="legacy|LEGACY|rejected"):
        llm_lane.generate("hi", lane="deepseek-flash", model="deepseek-reasoner", _skip_consumption=True)


def test_chat_mismatched_returned_model(monkeypatch):
    """If provider returns a different model than requested, fail closed."""
    class FakeResp:
        status_code = 200
        content = b'{"model":"deepseek-v4-flash","choices":[{"message":{"content":"x"},"finish_reason":"stop"}],"usage":{}}'
        headers = {}
        def json(self):
            return json.loads(self.content)

    monkeypatch.setattr(dc, "get_deepseek_api_key", lambda: ("fake-key", "deepseek_tradeai", False))
    monkeypatch.setattr(dc.requests, "post", lambda *a, **k: FakeResp())
    resp = dc.chat(model_id="deepseek-v4-pro", prompt="hi")
    assert resp.ok is False
    assert resp.error_class == dc.MISMATCHED_RETURNED_MODEL


def test_parse_strict_json_no_prose_strip():
    with pytest.raises(dc.DeepSeekError) as ei:
        dc.parse_strict_json('Here you go:\n{"ok": true}')
    assert ei.value.code == dc.JSON_INVALID
    assert dc.parse_strict_json('{"ok": true, "n": 1}')["n"] == 1


def test_parse_strict_json_empty():
    with pytest.raises(dc.DeepSeekError) as ei:
        dc.parse_strict_json("")
    assert ei.value.code == dc.EMPTY_CONTENT


def test_registry_schema_file_exists():
    schema = ROOT / "config" / "schemas" / "llm_model_registry.schema.json"
    assert schema.is_file()
    json.loads(schema.read_text())
    reg = json.loads((ROOT / "config" / "llm_model_registry.json").read_text())
    assert "logical_policies" in reg


def test_ambiguous_deepseek_v4_rejected():
    from lib.llm_model_registry import AmbiguousLegacyLane, resolve_lane_alias
    import pytest
    with pytest.raises(AmbiguousLegacyLane):
        resolve_lane_alias("deepseek-v4")


def test_llm_lane_rejects_ambiguous():
    import llm_lane
    import pytest
    with pytest.raises(RuntimeError, match="AMBIGUOUS"):
        llm_lane.generate("hi", lane="deepseek-v4", _skip_consumption=True)


def test_available_ambiguous_false():
    import llm_lane
    assert llm_lane.available("deepseek-v4") is False


def test_json_contract_validate_watch():
    from lib.llm_output_schemas import validate_process_output
    data = validate_process_output("watch_narrative.v1", {
        "schema_id": "watch_narrative.v1",
        "symbol": "AAPL",
        "narrative": "ok",
        "stance": "bullish",
        "confidence": 0.5,
        "drivers": [],
        "risks": [],
    })
    assert data["symbol"] == "AAPL"


def test_json_contract_rejects_bad_type():
    from lib.llm_output_schemas import validate_process_output
    import pytest
    with pytest.raises(ValueError):
        validate_process_output("watch_narrative.v1", {
            "schema_id": "watch_narrative.v1",
            "symbol": "AAPL",
            "narrative": "ok",
            "confidence": "high",  # wrong type
        })


def test_cost_not_relative_units_in_estimate():
    from lib.llm_model_registry import estimate_usd_cost
    # 1000 chars of text must NOT be used; only tokens
    est = estimate_usd_cost(model_id="deepseek-v4-flash", prompt_tokens=0, completion_tokens=0)
    assert est["estimated_cost_usd"] == 0.0


def test_auth_canonical_deepseek_tradeai_alone(monkeypatch):
    from lib import llm_model_registry as reg
    reg.clear_registry_cache()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("deepseek_tradeai", "unit-test-placeholder-not-a-real-key")
    key, name, used_alias = reg.get_deepseek_api_key()
    assert key == "unit-test-placeholder-not-a-real-key"
    assert name == "deepseek_tradeai"
    assert used_alias is False
    # never embed key in exception messages from helpers
    assert "unit-test-placeholder" not in name


def test_auth_compatibility_alias_alone(monkeypatch):
    from lib import llm_model_registry as reg
    reg.clear_registry_cache()
    monkeypatch.delenv("deepseek_tradeai", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "alias-placeholder-not-real")
    key, name, used_alias = reg.get_deepseek_api_key()
    assert name == "DEEPSEEK_API_KEY"
    assert used_alias is True
    assert key == "alias-placeholder-not-real"


def test_auth_canonical_precedes_alias(monkeypatch):
    from lib import llm_model_registry as reg
    reg.clear_registry_cache()
    monkeypatch.setenv("deepseek_tradeai", "canonical-placeholder")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "alias-placeholder")
    key, name, used_alias = reg.get_deepseek_api_key()
    assert name == "deepseek_tradeai"
    assert used_alias is False
    assert key == "canonical-placeholder"


def test_auth_missing_both(monkeypatch):
    from lib import llm_model_registry as reg
    reg.clear_registry_cache()
    monkeypatch.delenv("deepseek_tradeai", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    key, name, used_alias = reg.get_deepseek_api_key()
    assert key is None
    assert name is None


def test_registry_auth_env_is_deepseek_tradeai():
    from lib.llm_model_registry import load_registry, clear_registry_cache
    clear_registry_cache()
    reg = load_registry()
    ds = reg["providers"]["deepseek"]
    assert ds["auth_env"] == "deepseek_tradeai"
    assert ds.get("compatibility_auth_env") == "DEEPSEEK_API_KEY"
    assert "legacy_auth_env" not in ds or ds.get("auth_env") == "deepseek_tradeai"


def test_auth_missing_message_has_no_secret_value(monkeypatch):
    from lib import deepseek_client as dc
    from lib import llm_model_registry as reg
    reg.clear_registry_cache()
    monkeypatch.delenv("deepseek_tradeai", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(dc, "get_deepseek_api_key", lambda: (None, None, False))
    resp = dc.chat(policy="FAST", prompt="x")
    assert resp.error_class == dc.AUTH_MISSING
    blob = (resp.error_message or "") + str(resp.to_dict())
    assert "sk-" not in blob
    # placeholder keys must never appear if we accidentally used them
    assert "unit-test-placeholder" not in blob
    assert "alias-placeholder" not in blob
