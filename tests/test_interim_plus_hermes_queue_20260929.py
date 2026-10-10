"""2026-09-29: thin llm_curation + Hermes queue must open a pending follow-up.

NFLX incident: gap resolver returned partial (llm_curation) WITH hermes eta_seconds.
_resolve_blocking_gaps classified it answered-only, the desk returned without writing
cio_operator_pending_replies, and the completed Hermes thesis never came back.
"""
from __future__ import annotations

from scripts.lib import cio_operator_desk_loop as desk


class _Res:
    def __init__(self, *, answered=False, outcome="no_coverage", answer=None, eta_seconds=None, vector=None):
        self.answered = answered
        self.outcome = outcome
        self.answer = answer
        self.eta_seconds = eta_seconds
        self.vector = vector
        self.attempts = []

    def to_dict(self):
        return {
            "answered": self.answered,
            "outcome": self.outcome,
            "answer": self.answer,
            "eta_seconds": self.eta_seconds,
            "vector": self.vector,
            "domain": "hermes_research",
            "subject": "NFLX",
            "attempts": [],
        }


def test_partial_with_eta_is_both_answered_and_queued(monkeypatch):
    """Classification must put interim+Hermes into BOTH buckets."""
    calls = {"n": 0}

    def fake_resolve(gap, ctx=None):
        calls["n"] += 1
        return _Res(
            answered=False,
            outcome="partial",
            answer={"source": "llm_curation", "model": "deepseek-flash", "text": "thin"},
            eta_seconds=1800,
            vector="llm_curation",
        )

    class FakeCtx:
        def __init__(self, **kw):
            pass

    class FakeGap:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    monkeypatch.setattr(
        "scripts.lib.gap_resolver.resolve",
        fake_resolve,
        raising=False,
    )
    # Import path used inside the function
    import scripts.lib.gap_resolver as gr

    monkeypatch.setattr(gr, "resolve", fake_resolve)
    monkeypatch.setattr(gr, "Context", FakeCtx)
    monkeypatch.setattr(gr, "DataGap", FakeGap)

    out = desk._resolve_blocking_gaps(
        [{"domain": "hermes_research", "symbol": "NFLX", "reason": "no promoted research"}],
        intent={"symbols": ["NFLX"]},
        text="how is nexflix as a long position",
        chat_id="100000001",
        pending_id="opr_testnflx001",
    )
    assert out["answered"], "thin interim must still surface as answered"
    assert out["queued"], "Hermes eta must surface as queued so a pending opens"
    assert out["eta_seconds"] == 1800
