"""BridgeHermesResearchBackend — mocked HTTP / parse paths (no live bridge)."""
from __future__ import annotations

import json
import urllib.error
from io import BytesIO

import pytest

from lib.hermes_bridge_backend import BridgeHermesResearchBackend
from lib.hermes_research_backend import HermesBackendError


def _req():
    return {
        "authority": "READ_ONLY_ADVISORY",
        "research_id": "res_test",
        "plan_id": "plan_test",
        "thesis_version": "desk@v5",
        "subject": {"symbol": "SCHD"},
        "questions": [
            {"id": "q1", "text": "Catalysts next 10 sessions?", "intent": "catalyst_map"},
            {"id": "q2", "text": "Invalidation for hold?", "intent": "invalidation"},
        ],
        "context_snapshot": {"weight_pct": 17.5, "cash_pct": 45.0},
    }


def _openai_wrap(content: str) -> str:
    return json.dumps({
        "choices": [{"message": {"content": content}}],
    })


def _good_json() -> dict:
    return {
        "as_of": "2026-08-12T18:00:00+00:00",
        "answers": [
            {
                "question_id": "q1",
                "status": "answered",
                "summary": "No high-urgency catalyst that forces size review under defer.",
                "detail": "Calendar soft; observe.",
                "confidence": 0.7,
                "citations": [],
            },
            {
                "question_id": "q2",
                "status": "answered",
                "summary": "Invalidation: sustained weight above fire without buffer thesis.",
                "confidence": 0.65,
            },
        ],
        "findings": [
            {"id": "f1", "kind": "catalyst", "severity": "low", "text": "Soft calendar window", "confidence": 0.6},
        ],
        "desk_implications": {
            "suggestion_bias": "hold_with_thesis",
            "changes_materiality": False,
            "watch_triggers": ["weight_pct >= 16.5"],
            "notes": "Honor operator defer.",
        },
        "limitations": ["bridge_mock"],
    }


class _FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_happy_json(monkeypatch):
    be = BridgeHermesResearchBackend()
    payload = _openai_wrap(json.dumps(_good_json())).encode()

    def _urlopen(req, timeout=None):
        return _FakeResp(payload)

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    body = be.run(_req())
    assert body["as_of"]
    assert {a["question_id"] for a in body["answers"]} == {"q1", "q2"}
    assert body["desk_implications"]["suggestion_bias"] == "hold_with_thesis"


def test_markdown_fence(monkeypatch):
    be = BridgeHermesResearchBackend()
    fenced = "```json\n" + json.dumps(_good_json()) + "\n```"
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResp(_openai_wrap(fenced).encode()),
    )
    body = be.run(_req())
    assert len(body["answers"]) == 2


def test_empty_content_retryable(monkeypatch):
    be = BridgeHermesResearchBackend()
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResp(_openai_wrap("").encode()),
    )
    with pytest.raises(HermesBackendError) as ei:
        be.run(_req())
    assert ei.value.retryable is True


def test_non_json_non_retryable(monkeypatch):
    be = BridgeHermesResearchBackend()
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResp(_openai_wrap("sorry I cannot").encode()),
    )
    with pytest.raises(HermesBackendError) as ei:
        be.run(_req())
    assert ei.value.retryable is False


def test_http_503_retryable(monkeypatch):
    be = BridgeHermesResearchBackend()

    def _boom(req, timeout=None):
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:8766/v1/chat/completions",
            code=503,
            msg="unavailable",
            hdrs=None,
            fp=BytesIO(b'{"error":"busy"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    with pytest.raises(HermesBackendError) as ei:
        be.run(_req())
    assert ei.value.retryable is True
    assert "503" in str(ei.value)


def test_http_403_non_retryable(monkeypatch):
    be = BridgeHermesResearchBackend()

    def _boom(req, timeout=None):
        raise urllib.error.HTTPError(
            url="http://x",
            code=403,
            msg="forbidden",
            hdrs=None,
            fp=BytesIO(b'{"error":"forbidden"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    with pytest.raises(HermesBackendError) as ei:
        be.run(_req())
    assert ei.value.retryable is False


def test_omitted_question_becomes_unanswered(monkeypatch):
    be = BridgeHermesResearchBackend()
    partial = _good_json()
    partial["answers"] = [partial["answers"][0]]  # only q1
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResp(_openai_wrap(json.dumps(partial)).encode()),
    )
    body = be.run(_req())
    by = {a["question_id"]: a for a in body["answers"]}
    assert by["q1"]["status"] == "answered"
    assert by["q2"]["status"] == "unanswered"


def test_execution_language_lint(monkeypatch):
    be = BridgeHermesResearchBackend()
    bad = _good_json()
    bad["answers"][0]["summary"] = "You should buy now the dip"
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResp(_openai_wrap(json.dumps(bad)).encode()),
    )
    with pytest.raises(HermesBackendError, match="execution language"):
        be.run(_req())


def test_bad_bias_normalized(monkeypatch):
    be = BridgeHermesResearchBackend()
    raw = _good_json()
    raw["desk_implications"]["suggestion_bias"] = "all_in"
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResp(_openai_wrap(json.dumps(raw)).encode()),
    )
    body = be.run(_req())
    assert body["desk_implications"]["suggestion_bias"] == "observe"


def test_messages_include_question_ids():
    be = BridgeHermesResearchBackend()
    msgs = be._build_messages(_req(), [
        {"id": "q1", "text": "A?", "intent": "catalyst_map"},
        {"id": "q2", "text": "B?", "intent": "invalidation"},
    ])
    user = msgs[1]["content"]
    assert "q1" in user and "q2" in user
    assert "READ_ONLY" in msgs[0]["content"] or "read_only" in user.lower() or "no_order" in user


def _req_with_catalyst():
    req = _req()
    req["known_catalyst_event_ids"] = ["cat_schd_2026-08-18_analyst_upgrade_a05f99"]
    req["catalyst"] = {
        "as_of": "2026-08-18T15:19:19+00:00",
        "symbol": "SCHD",
        "open_count": 1,
        "quality_state": "OK",
        "events": [{
            "event_id": "cat_schd_2026-08-18_analyst_upgrade_a05f99",
            "title": "The 3% ETF Outperforming 11% Competitors: How SCHD Keeps Beating Covered-Call ETFs",
            "kind": "analyst_upgrade",
            "severity": "medium",
            "session_date": "2026-08-18",
            "source": "catalyst_events",
            "confirmed": True,
            "symbol": "SCHD",
        }],
    }
    return req


def test_messages_include_catalyst_events():
    be = BridgeHermesResearchBackend()
    req = _req_with_catalyst()
    qs = [{"id": "q1", "text": "Catalysts next 10 sessions?", "intent": "catalyst_map"}]
    user = be._build_messages(req, qs)[1]["content"]
    assert "cat_schd_2026-08-18_analyst_upgrade_a05f99" in user
    assert "analyst_upgrade" in user


def test_canary_shaped_empty_context_gets_summary_and_sources(monkeypatch):
    """R6.1 canary: model had answer text but no top-level summary/sources; as_of was 2025-07-11."""
    be = BridgeHermesResearchBackend()
    raw = {
        "as_of": "2025-07-11",
        "answers": [
            {
                "question_id": "q1",
                "status": "unanswered",
                "summary": "No specific catalysts identified within the next 10 sessions for SCHD.",
                "detail": "No scheduled events or data releases found in the provided context.",
                "confidence": 0.2,
                "citations": [],
            },
            {
                "question_id": "q2",
                "status": "unanswered",
                "summary": "No high-impact catalysts identified that would alter hold vs size-review language.",
                "confidence": 0.2,
                "citations": [],
            },
        ],
        "findings": [],
        "desk_implications": {
            "suggestion_bias": "hold_with_thesis",
            "changes_materiality": False,
            "notes": "No material catalysts or risks identified; maintain current thesis.",
        },
        "limitations": ["No forward-looking data or event calendar provided in context."],
    }
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResp(_openai_wrap(json.dumps(raw)).encode()),
    )
    body = be.run(_req_with_catalyst())
    assert "2025-07-11" not in str(body.get("as_of"))
    assert "SCHD" in (body.get("summary") or "")
    assert "cat_schd_2026-08-18_analyst_upgrade_a05f99" in (body.get("sources") or [])
