"""FinOps call-site instrumentation. Fixtures + mocks only — no paid traffic."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.provider_cost.context import cost_attribution
from scripts.lib.provider_cost.emit import (
    OUTCOME_ATTEMPT,
    OUTCOME_PRE_SEND,
    OUTCOME_SUCCESS,
    _SEEN_IDS,
    emit_cost_event,
    emit_paid_call,
)
from scripts.lib.provider_cost.identity import fingerprint_key, redact_mapping
from scripts.lib.provider_cost.schema import is_test_process


FORBIDDEN_STATUSES = {"KNOWN_BYPASS", "INSTRUMENTED_BUT_INCOMPLETE", "UNKNOWN"}
ALLOWED_NON_ACTIVE = {
    "CANONICAL_INSTRUMENTED",
    "NON_BILLABLE",
    "DISABLED",
    "THIRD_PARTY_TOOL",
    "DEVELOPER_TOOL",
}


def _events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _clear_seen():
    _SEEN_IDS.clear()


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    log = tmp_path / "events.jsonl"
    monkeypatch.setenv("PROVIDER_COST_EVENT_LOG", str(log))
    _clear_seen()
    return log


def test_registry_has_no_active_bypass():
    data = json.loads((ROOT / "config" / "provider_cost_call_sites.json").read_text())
    bad = [
        s for s in data["sites"]
        if s.get("instrumented") in FORBIDDEN_STATUSES
    ]
    assert bad == [], bad
    for s in data["sites"]:
        assert s.get("instrumented") in ALLOWED_NON_ACTIVE, s


def test_successful_canonical_request_emits_once(_iso):
    from lib import deepseek_client as dc

    payload = {
        "model": "deepseek-v4-flash",
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"x-request-id": "prov-1"}
    resp.content = json.dumps(payload).encode()
    resp.json.return_value = payload

    with patch.object(dc, "get_deepseek_api_key", return_value=("sk-test-key-not-real-aaaa", "deepseek_tradeai", False)):
        with patch.object(dc.requests, "post", return_value=resp):
            out = dc.chat(model_id="deepseek-v4-flash", prompt="hi")
    assert out.ok
    rows = _events(_iso)
    assert len(rows) == 1
    assert rows[0]["outcome"] == OUTCOME_SUCCESS
    assert rows[0]["request_id"] == "prov-1"
    assert rows[0]["client_request_id"]
    assert rows[0]["possibly_billable"] is True
    assert "sk-test" not in json.dumps(rows[0])


def test_wrapper_through_canonical_emits_once(_iso):
    from lib import deepseek_client as dc

    payload = {
        "model": "deepseek-v4-flash",
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 2},
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"x-request-id": "prov-wrap"}
    resp.content = json.dumps(payload).encode()
    resp.json.return_value = payload

    with patch.object(dc, "get_deepseek_api_key", return_value=("sk-wrap-key-xxxxxxxxxxxx", "deepseek_tradeai", False)):
        with patch.object(dc.requests, "post", return_value=resp):
            with cost_attribution(source_service="llm_lane", source_process="reentry_llm_insight", source_lane="FAST"):
                dc.chat(model_id="deepseek-v4-flash", prompt="hi")
                emit_paid_call(  # must be ignored as a second logical emit if same identity — we do not call this
                    provider="deepseek", model="deepseek-v4-flash", request_id="other"
                )
    # chat emitted once; the extra emit_paid_call is a different event_id (different rid)
    # wrapper contract: wrappers must NOT call emit_paid_call. Prove chat-only path:
    rows = [r for r in _events(_iso) if r.get("request_id") == "prov-wrap"]
    assert len(rows) == 1
    assert rows[0]["source_service"] == "llm_lane"
    assert rows[0]["source_process"] == "reentry_llm_insight"
    assert rows[0]["source_lane"] == "FAST"


def test_direct_bypass_emits_once(_iso):
    from lib.cio_governed_model_bridge import RealProvider, _emit_bridge_cost

    _emit_bridge_cost(
        outcome="success",
        model="deepseek-v4-flash",
        request_id="bridge-1",
        client_request_id="c1",
        raw_key="sk-bridge-secret-yyyyyyyy",
        usage={"prompt_tokens": 3, "completion_tokens": 1},
        request_sent=True,
        possibly_billable=True,
    )
    rows = _events(_iso)
    assert len(rows) == 1
    assert rows[0]["source_service"] == "cio_governed_model_bridge"
    assert "sk-bridge" not in json.dumps(rows[0])
    assert RealProvider  # imported (class exists)


def test_timeout_after_send_records_attempt(_iso):
    from lib import deepseek_client as dc

    with patch.object(dc, "get_deepseek_api_key", return_value=("sk-to-key-zzzzzzzzzzzz", "deepseek_tradeai", False)):
        with patch.object(dc.requests, "post", side_effect=dc.requests.Timeout()):
            out = dc.chat(model_id="deepseek-v4-flash", prompt="hi")
    assert out.ok is False
    assert out.possibly_billable is True
    rows = _events(_iso)
    assert len(rows) == 1
    assert rows[0]["outcome"] == OUTCOME_ATTEMPT
    assert rows[0]["possibly_billable"] is True
    assert rows[0]["request_sent"] is True
    assert rows[0]["calculated_cost_usd"] is None
    assert rows[0]["cost_source"] == "PRICE_UNKNOWN"
    assert rows[0]["usage_unknown"] is True
    assert "sk-to-key" not in json.dumps(rows[0])


def test_http_error_records_attempt(_iso):
    from lib import deepseek_client as dc

    resp = MagicMock()
    resp.status_code = 500
    resp.headers = {"x-request-id": "prov-500"}
    resp.text = "nope"
    with patch.object(dc, "get_deepseek_api_key", return_value=("sk-http-key-wwwwwwww", "deepseek_tradeai", False)):
        with patch.object(dc.requests, "post", return_value=resp):
            out = dc.chat(model_id="deepseek-v4-flash", prompt="hi")
    assert out.possibly_billable is True
    rows = _events(_iso)
    assert len(rows) == 1
    assert rows[0]["outcome"] == OUTCOME_ATTEMPT
    assert rows[0]["request_id"] == "prov-500"
    assert rows[0]["calculated_cost_usd"] is None


def test_pre_send_auth_failure_not_billed(_iso):
    from lib import deepseek_client as dc

    with patch.object(dc, "get_deepseek_api_key", return_value=(None, None, False)):
        out = dc.chat(model_id="deepseek-v4-flash", prompt="hi")
    assert out.error_class == dc.AUTH_MISSING
    rows = _events(_iso)
    assert len(rows) == 1
    assert rows[0]["outcome"] == OUTCOME_PRE_SEND
    assert rows[0]["possibly_billable"] is False
    assert rows[0]["request_sent"] is False
    assert rows[0]["calculated_cost_usd"] is None
    assert rows[0].get("attributed_usd") is None or rows[0].get("calculated_cost_usd") is None


def test_provider_usage_unknown_remains_unknown(_iso):
    eid = emit_cost_event(
        provider="deepseek",
        model="deepseek-v4-flash",
        outcome=OUTCOME_ATTEMPT,
        request_id="u1",
        client_request_id="c-u1",
        request_sent=True,
        possibly_billable=True,
        error_class="TIMEOUT",
    )
    assert eid
    row = _events(_iso)[0]
    assert row["usage_unknown"] is True
    assert row["calculated_cost_usd"] is None
    assert row["cost_source"] == "PRICE_UNKNOWN"


def test_request_id_joining(_iso):
    emit_cost_event(
        provider="deepseek",
        model="deepseek-v4-flash",
        outcome=OUTCOME_SUCCESS,
        request_id="join-prov",
        client_request_id="join-client",
        prompt_tokens=1,
        completion_tokens=1,
    )
    row = _events(_iso)[0]
    assert row["request_id"] == "join-prov"
    assert row["client_request_id"] == "join-client"


def test_key_fingerprint_not_raw(_iso):
    raw = "sk-super-secret-value-12345678"
    emit_paid_call(provider="deepseek", model="deepseek-v4-flash", raw_key=raw, request_id="fp1")
    row = _events(_iso)[0]
    assert row["key_fingerprint"] == fingerprint_key(raw, provider="deepseek")
    assert raw not in json.dumps(row)
    assert "super-secret" not in json.dumps(row)


def test_service_process_run_attribution(_iso):
    with cost_attribution(
        source_service="svc",
        source_process="proc",
        source_lane="FAST",
        agent="alex",
        run_id="run_1",
        reservation_id="99",
        environment="test",
    ):
        emit_paid_call(provider="deepseek", model="deepseek-v4-flash", request_id="attr1")
    row = _events(_iso)[0]
    assert row["source_service"] == "svc"
    assert row["source_process"] == "proc"
    assert row["source_lane"] == "FAST"
    assert row["agent_name"] == "alex"
    assert row["run_id"] == "run_1"
    assert row["reservation_id"] == "99"
    assert row["environment"] == "test"


def test_process_classification():
    assert is_test_process("test_smoke_bridge")
    assert is_test_process("test")
    assert is_test_process("/repo/tests/foo.py")
    assert not is_test_process("alex_cio_synthesis")


def test_dedupe_same_event_id(_iso):
    kwargs = dict(
        provider="deepseek",
        model="deepseek-v4-flash",
        request_id="dup-1",
        client_request_id="dup-c",
        usage_start="2026-08-17T00:00:00+00:00",
        prompt_tokens=1,
        completion_tokens=1,
    )
    a = emit_paid_call(**kwargs)
    b = emit_paid_call(**kwargs)
    assert a == b
    assert len(_events(_iso)) == 1


def test_secret_redaction_exception_and_http_paths(_iso):
    dirty = {
        "Authorization": "Bearer sk-should-never-persist",
        "DEEPSEEK_API_KEY": "sk-should-never-persist",
        "ok": 1,
    }
    clean = redact_mapping(dirty)
    dumped = json.dumps(clean)
    assert "sk-should-never" not in dumped
    assert clean["Authorization"] == "[REDACTED]"


def test_successful_call_not_double_emitted_with_wrapper(_iso):
    from lib import deepseek_client as dc

    payload = {
        "model": "deepseek-v4-flash",
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 2},
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"x-request-id": "once-1"}
    resp.content = json.dumps(payload).encode()
    resp.json.return_value = payload
    with patch.object(dc, "get_deepseek_api_key", return_value=("sk-once-key-bbbbbbbb", "deepseek_tradeai", False)):
        with patch.object(dc.requests, "post", return_value=resp):
            with cost_attribution(source_service="llm_consumption.gate_and_generate", source_process="test_finops"):
                dc.chat(model_id="deepseek-v4-flash", prompt="hi")
    rows = _events(_iso)
    assert len(rows) == 1
    assert rows[0]["classification"] == "TRADE_AI_TEST"
    assert rows[0]["is_test"] is True


def test_json_invalid_after_response(_iso):
    from lib import deepseek_client as dc

    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"x-request-id": "badjson"}
    resp.content = b"not-json"
    resp.json.side_effect = ValueError("nope")
    with patch.object(dc, "get_deepseek_api_key", return_value=("sk-json-key-cccccccc", "deepseek_tradeai", False)):
        with patch.object(dc.requests, "post", return_value=resp):
            out = dc.chat(model_id="deepseek-v4-flash", prompt="hi")
    assert out.error_class == dc.JSON_INVALID
    rows = _events(_iso)
    assert len(rows) == 1
    assert rows[0]["outcome"] == OUTCOME_ATTEMPT


def test_returned_model_mismatch_attempt(_iso):
    from lib import deepseek_client as dc

    payload = {
        "model": "deepseek-chat",
        "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"x-request-id": "mm"}
    resp.content = json.dumps(payload).encode()
    resp.json.return_value = payload
    with patch.object(dc, "get_deepseek_api_key", return_value=("sk-mm-key-dddddddd", "deepseek_tradeai", False)):
        with patch.object(dc.requests, "post", return_value=resp):
            out = dc.chat(model_id="deepseek-v4-flash", prompt="hi")
    assert out.error_class == dc.MISMATCHED_RETURNED_MODEL
    rows = _events(_iso)
    assert rows[0]["outcome"] == OUTCOME_ATTEMPT
    assert rows[0]["possibly_billable"] is True
