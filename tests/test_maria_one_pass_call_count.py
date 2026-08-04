"""Prove Maria worker path makes exactly one LLM call (not two-pass)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def test_maria_one_pass_single_llm_call(monkeypatch):
    import process_watchlist_agent_jobs as pwaj

    calls = {"n": 0}

    def fake_llm(prompt, max_tokens=800, task_type="agent_narrative", high_impact=False):
        calls["n"] += 1
        assert task_type == "agent_narrative"
        return (
            '{"sentiment":"neutral","catalyst_present":false,"catalyst":null,'
            '"recommendation":"HOLD","confidence":50,"summary":"ok",'
            '"full_narrative":"n","reasoning":"r","evidence":[],'
            '"data_i_doubt":"none","reason_codes":["x"],"next_action":"monitor"}'
        )

    monkeypatch.setattr(pwaj, "_llm", fake_llm)
    monkeypatch.setattr(pwaj, "_get_recent_intel", lambda s: "")
    monkeypatch.setattr(pwaj, "_get_peer_agent_notes", lambda s, a: "")
    # Avoid real RAG
    import types
    monkeypatch.setitem(
        sys.modules,
        "rag_retrieval",
        types.SimpleNamespace(
            get_rag_context=lambda **k: [],
            format_rag_context_for_prompt=lambda *a, **k: "",
        ),
    )

    two_pass = MagicMock(side_effect=AssertionError("two-pass must not run"))
    monkeypatch.setattr(pwaj, "_run_maria_two_pass", two_pass)

    out = pwaj._run_maria_one_pass("AAPL", "context about AAPL", note="")
    assert calls["n"] == 1
    assert two_pass.call_count == 0
    assert "HOLD" in out or "hold" in out.lower()
    assert "maria_call_count_contract" in out


def test_process_jobs_maria_branch_uses_one_pass_not_two(monkeypatch):
    """Source contract: process_jobs maria branch calls one-pass, not two-pass."""
    src = (ROOT / "scripts/process_watchlist_agent_jobs.py").read_text()
    # Call site in process_jobs
    assert "raw = _run_maria_one_pass" in src
    assert 'raw = _run_maria_two_pass' not in src
    # two-pass function may remain for reference/tests but must not be the call site
    assert "def _run_maria_two_pass" in src
    assert "def _run_maria_one_pass" in src
    # one-pass body must not *call* two-pass (docstring may mention it)
    i = src.index("def _run_maria_one_pass")
    j = src.index("\ndef ", i + 1)
    body = src[i:j]
    assert "_run_maria_two_pass(" not in body
    assert body.count("_llm(") == 1
