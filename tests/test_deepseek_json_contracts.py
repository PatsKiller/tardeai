"""Strict process JSON contracts + bounded repair."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.deepseek_client import DeepSeekError, DeepSeekResponse, parse_strict_json  # noqa: E402
from lib.llm_json_contract import generate_structured  # noqa: E402
from lib.llm_output_schemas import SCHEMA_MODELS, schema_example, validate_process_output  # noqa: E402
from lib import deepseek_client as dc  # noqa: E402


ALL_SCHEMAS = ["cio_synthesis.v1", "watch_narrative.v1", "strategy_plan.v1", "pipeline_diagnosis.v1"]


def test_registry_schemas_all_implemented():
    import json as js
    reg = js.loads((ROOT / "config" / "llm_process_registry.json").read_text())
    declared = {p.get("output_schema") for p in reg.get("processes") or [] if p.get("output_schema")}
    assert declared <= set(SCHEMA_MODELS.keys())
    for s in ALL_SCHEMAS:
        assert s in SCHEMA_MODELS


@pytest.mark.parametrize("sid", ALL_SCHEMAS)
def test_valid_examples(sid):
    ex = schema_example(sid)
    out = validate_process_output(sid, ex)
    assert out["schema_id"] == sid


def test_missing_required():
    with pytest.raises(ValueError):
        validate_process_output("watch_narrative.v1", {"schema_id": "watch_narrative.v1"})


def test_wrong_type():
    with pytest.raises(ValueError):
        validate_process_output("watch_narrative.v1", {
            "schema_id": "watch_narrative.v1", "symbol": "AAPL", "narrative": "x",
            "confidence": "high",
        })


def test_invalid_enum():
    with pytest.raises(ValueError):
        validate_process_output("watch_narrative.v1", {
            "schema_id": "watch_narrative.v1", "symbol": "AAPL", "narrative": "x",
            "stance": "moon",
        })


def test_out_of_range():
    with pytest.raises(ValueError):
        validate_process_output("watch_narrative.v1", {
            "schema_id": "watch_narrative.v1", "symbol": "AAPL", "narrative": "x",
            "confidence": 2.5,
        })


def test_parse_strict_rejects_prose():
    with pytest.raises(DeepSeekError) as e:
        parse_strict_json('Here is JSON:\n{"ok": true}')
    assert e.value.code == "JSON_INVALID"


def test_parse_strict_rejects_fenced():
    with pytest.raises(DeepSeekError):
        parse_strict_json('```json\n{"ok": true}\n```')


def test_parse_empty():
    with pytest.raises(DeepSeekError) as e:
        parse_strict_json("")
    assert e.value.code == "EMPTY_CONTENT"


def test_parse_malformed():
    with pytest.raises(DeepSeekError):
        parse_strict_json("{not json")


def _resp(content, model="deepseek-v4-flash", ok=True, err=None, finish="stop"):
    return DeepSeekResponse(
        ok=ok if content else False,
        requested_policy="FAST",
        executed_policy="FAST",
        requested_model_id=model,
        returned_model=model,
        thinking="disabled",
        reasoning_effort=None,
        content=content,
        reasoning_content=None,
        tool_calls=None,
        finish_reason=finish,
        usage={"prompt_tokens": 1, "completion_tokens": 1},
        estimated_cost_usd=0.0,
        cost_basis="provider_usage_x_registry_snapshot",
        error_class=err,
        error_message=err,
    )


def test_repair_succeeds(monkeypatch):
    good = json.dumps(schema_example("watch_narrative.v1"))
    calls = {"n": 0}

    def fake_chat(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _resp('not json')  # fails parse
        return _resp(good)

    monkeypatch.setattr("lib.llm_json_contract.chat", fake_chat)
    out = generate_structured(policy="FAST", prompt="narrate AAPL", schema_id="watch_narrative.v1")
    assert out["ok"] is True
    assert out["attempts"] == 2
    assert out.get("repair_used") is True


def test_repair_fails(monkeypatch):
    def fake_chat(**kwargs):
        return _resp("{bad")

    monkeypatch.setattr("lib.llm_json_contract.chat", fake_chat)
    with pytest.raises(DeepSeekError) as e:
        generate_structured(policy="FAST", prompt="x", schema_id="watch_narrative.v1")
    assert e.value.code == "MODEL_OUTPUT_INVALID"


def test_finish_length_from_client(monkeypatch):
    monkeypatch.setattr(dc, "get_deepseek_api_key", lambda: ("k", "DEEPSEEK_API_KEY", False))

    def fake_post(url, json=None, headers=None, timeout=None):
        r = MagicMock()
        r.status_code = 200
        r.headers = {}
        body = {
            "model": "deepseek-v4-flash",
            "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
            "usage": {},
        }
        r.content = json_mod.dumps(body).encode()
        r.json.return_value = body
        return r

    import json as json_mod
    monkeypatch.setattr(dc.requests, "post", fake_post)
    resp = dc.chat(policy="FAST", prompt="x")
    assert resp.error_class == dc.OUTPUT_TRUNCATED
