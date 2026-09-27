"""Thesis evidence excludes the house's own conclusions and off-subject rows (2026-09-27).

DELL's v1 thesis was synthesized from 16 cio_decision rows reading "DELL CIO:
MORE_RESEARCH"; with those removed, RAG returned posts about MSFT and AAPL. Hermetic.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import symbol_thesis_evidence as ste  # noqa: E402

ROWS = [
    {"source_type": "cio_decision", "source_id": 1, "title": "DELL CIO: MORE_RESEARCH"},
    {"source_type": "agent_synthesis", "source_id": 2, "title": "DELL synthesis: hold"},
    {"source_type": "social_post", "source_id": 3, "title": "$MSFT Nadella says AI pacing"},
    {"source_type": "social_post", "source_id": 4, "title": "$DELL ripping on AI servers"},
    {"source_type": "news", "source_id": 5, "title": "Dell Rises 7% as Morgan Stanley Lifts Odds"},
    {"source_type": "hermes_research", "source_id": 6, "title": "DELL: backlog and guidance review"},
]


def _fake_rag(monkeypatch):
    mod = types.ModuleType("rag_retrieval")
    mod.get_rag_context = lambda symbol, query_text=None, limit=7, conn=None: list(ROWS)[:limit]
    monkeypatch.setitem(sys.modules, "rag_retrieval", mod)


def test_circular_and_off_subject_rows_are_dropped_and_sourced_rows_first(monkeypatch):
    _fake_rag(monkeypatch)
    monkeypatch.setattr(ste, "_company_tokens", lambda symbol, conn=None: ["dell"])
    monkeypatch.setattr(ste, "excluded_evidence_source_types", lambda: frozenset(ste.DEFAULT_EXCLUDED_SOURCE_TYPES))
    out = ste.retrieve_rag_for_gap("DELL", question="thesis?", limit_each=3)
    for bucket in ("supporting", "contradictory"):
        types_ = [x["source_type"] for x in out[bucket]]
        assert "cio_decision" not in types_ and "agent_synthesis" not in types_
        assert types_ == ["news", "hermes_research", "social_post"]
    assert out["skipped_circular"] == 4 and out["skipped_off_subject"] == 2


def test_config_can_change_the_exclusions(monkeypatch):
    _fake_rag(monkeypatch)
    monkeypatch.setattr(ste, "_company_tokens", lambda symbol, conn=None: ["dell"])
    monkeypatch.setattr(ste, "excluded_evidence_source_types", lambda: frozenset())
    out = ste.retrieve_rag_for_gap("DELL", question="thesis?", limit_each=10)
    assert "cio_decision" in [x["source_type"] for x in out["supporting"]]


def test_default_exclusions_read_from_portfolio_intent():
    assert {"cio_decision", "agent_result", "agent_synthesis", "fused_signal"} <= ste.excluded_evidence_source_types()
