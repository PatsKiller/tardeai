"""Shared result-body contract for any HermesResearchBackend success path."""
from __future__ import annotations

from lib.hermes_research_backend import StubHermesResearchBackend
from hermes_contract import assert_result_body


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
