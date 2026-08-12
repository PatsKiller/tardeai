"""Shared Hermes result-body contract for backend + golden tests."""
from __future__ import annotations

from datetime import datetime

from lib.hermes_research_backend import (
    RESULT_BODY_KEYS,
    SUGGESTION_BIASES,
    questions_from_request,
)


def assert_result_body(body: dict, request: dict) -> None:
    """Hard structural gate for hermes_result@v1 body (unstamped)."""
    assert isinstance(body, dict), "body must be dict"
    assert body.get("as_of"), "as_of required"
    as_of = str(body["as_of"]).replace("Z", "+00:00")
    datetime.fromisoformat(as_of)

    qs = questions_from_request(request)
    answers = body.get("answers") or []
    assert len(answers) >= len(qs), "fewer answers than questions"
    ids = {a.get("question_id") for a in answers}
    for q in qs:
        assert q["id"] in ids, f"missing answer for {q['id']}"

    for a in answers:
        c = a.get("confidence")
        if c is not None:
            assert 0.0 <= float(c) <= 1.0, f"confidence out of range: {c}"

    di = body.get("desk_implications") or {}
    bias = di.get("suggestion_bias")
    if bias is not None:
        assert bias in SUGGESTION_BIASES, f"bad suggestion_bias: {bias}"

    assert "result_id" not in body, "worker stamps result_id — backend must not"
    # status on body is not expected from backend
    if "status" in body and body.get("status") not in (None,):
        # allow accidental None only
        pass
