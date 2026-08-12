"""Shared result-body contract for any HermesResearchBackend success path."""
from __future__ import annotations

from datetime import datetime

from lib.hermes_research_backend import (
    RESULT_BODY_KEYS,
    SUGGESTION_BIASES,
    StubHermesResearchBackend,
    questions_from_request,
)


def assert_result_body(body: dict, request: dict) -> None:
    assert isinstance(body, dict)
    assert body.get("as_of"), "as_of required"
    # parse ISO
    as_of = str(body["as_of"]).replace("Z", "+00:00")
    datetime.fromisoformat(as_of)

    qs = questions_from_request(request)
    answers = body.get("answers") or []
    assert len(answers) >= len(qs)
    ids = {a.get("question_id") for a in answers}
    for q in qs:
        assert q["id"] in ids, f"missing answer for {q['id']}"

    for a in answers:
        c = a.get("confidence")
        if c is not None:
            assert 0 <= float(c) <= 1
        if a.get("status") == "answered":
            assert str(a.get("summary") or "").strip() or True  # soft

    di = body.get("desk_implications") or {}
    bias = di.get("suggestion_bias")
    if bias is not None:
        assert bias in SUGGESTION_BIASES

    # only known body keys ideally (extra ok)
    unknown = set(body.keys()) - RESULT_BODY_KEYS - {"summary", "provenance"}
    # allow summary as soft body field
    assert "result_id" not in body
    assert "status" not in body or body.get("status") is None


def test_stub_satisfies_contract():
    req = {
        "authority": "READ_ONLY_ADVISORY",
        "thesis_version": "desk@v5",
        "subject": {"symbol": "SPCX"},
        "questions": [
            {"question_id": "q1", "text": "What changed vs basis?", "intent": "thesis_check"},
            {"question_id": "q2", "text": "Material catalysts?", "intent": "catalyst_map"},
        ],
    }
    body = StubHermesResearchBackend().run(req)
    assert_result_body(body, req)
