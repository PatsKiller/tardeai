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
    assert resolve_lane_alias("deepseek-v4") == "PRO_THINK"
    assert resolve_lane_alias("deepseek-v4-flash") == "FAST"
    assert resolve_lane_alias("deepseek-v4-pro") == "PRO_THINK"
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

    monkeypatch.setattr(dc, "get_deepseek_api_key", lambda: ("fake-key", "DEEPSEEK_API_KEY", False))
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
