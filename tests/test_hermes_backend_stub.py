"""HermesResearchBackend protocol + StubHermesResearchBackend tests."""
from __future__ import annotations

import pytest

from lib.hermes_research_backend import (
    HermesBackendError,
    HermesResearchBackend,
    StubHermesResearchBackend,
    assert_no_execution_language,
    build_hermes_backend,
    questions_from_request,
)


def _req(**kw):
    base = {
        "authority": "READ_ONLY_ADVISORY",
        "thesis_version": "desk@v5",
        "subject": {"symbol": "SCHD"},
        "questions": [
            {"id": "q1", "text": "Catalysts next 10 sessions?", "intent": "catalyst_map"},
            {"id": "q2", "text": "Invalidation for hold?", "intent": "invalidation"},
        ],
    }
    base.update(kw)
    return base


def test_protocol_runtime_check():
    assert isinstance(StubHermesResearchBackend(), HermesResearchBackend)


def test_stub_backend_answers_all_questions():
    body = StubHermesResearchBackend().run(_req())
    assert body["as_of"]
    assert {a["question_id"] for a in body["answers"]} == {"q1", "q2"}
    assert all(a["status"] == "answered" for a in body["answers"])
    assert body["desk_implications"]["suggestion_bias"] == "observe"
    assert "stub_backend" in body["limitations"]


def test_stub_accepts_question_id_field():
    body = StubHermesResearchBackend().run(_req(questions=[
        {"question_id": "qa", "text": "Flow vs price drift?", "intent": "drift_attribution"},
    ]))
    assert body["answers"][0]["question_id"] == "qa"


def test_backend_rejects_non_readonly_authority():
    with pytest.raises(HermesBackendError, match="READ_ONLY"):
        StubHermesResearchBackend().run({
            "authority": "TRADE",
            "questions": [{"id": "q1", "text": "x"}],
        })


def test_backend_rejects_empty_questions():
    with pytest.raises(HermesBackendError, match="no questions"):
        StubHermesResearchBackend().run({
            "authority": "READ_ONLY_ADVISORY",
            "questions": [],
        })


def test_lint_blocks_buy_sell_stop_language():
    with pytest.raises(HermesBackendError):
        assert_no_execution_language("we should buy now the dip")
    with pytest.raises(HermesBackendError):
        assert_no_execution_language("place stop under 100")
    assert_no_execution_language("hold with thesis; observe through event")


def test_questions_from_request_filters_empty():
    qs = questions_from_request({
        "questions": [
            {"id": "q1", "text": "ok"},
            {"id": "q2", "text": "  "},
            "plain string question",
        ],
    })
    assert len(qs) == 2
    assert qs[1]["id"] == "q2" or qs[1]["text"] == "plain string question"


def test_build_hermes_backend_factory():
    assert type(build_hermes_backend("stub")).__name__ == "StubHermesResearchBackend"
    assert type(build_hermes_backend("catalyst")).__name__ == "CatalystFirstHermesBackend"
    with pytest.raises(ValueError):
        build_hermes_backend("nope")


def test_partial_mode():
    body = StubHermesResearchBackend(mark_partial=True).run(_req())
    assert all(a["status"] == "partial" for a in body["answers"])
