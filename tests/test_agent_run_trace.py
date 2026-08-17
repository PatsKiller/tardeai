"""Phase 1 — AgentRunTrace@v1 unit/adversarial tests.

No broker, no network. Uses a tmp JSONL path; never writes to production store.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_run_trace import (  # noqa: E402
    TRACE_VERSION,
    append_trace,
    build_trace,
    close_trace,
    new_trace_id,
    query_traces,
    sanitize_trace,
    trace_digest,
    validate_trace,
)


def _tmp_path(tmp_path: Path) -> Path:
    return tmp_path / "traces.jsonl"


def test_trace_start_valid():
    t = build_trace(trace_id="tr_w1", wake_id="w1", agent="alex", role="cio_synthesis")
    ok, errs = validate_trace(t)
    assert ok, errs
    assert t["status"] == "started"


def test_trace_parent_child_linkage():
    parent = build_trace(trace_id="tr_p", wake_id="w1", agent="alex", role="cio_synthesis")
    child = build_trace(
        trace_id="tr_c",
        wake_id="w1",
        parent_trace_id="tr_p",
        agent="guardian",
        role="risk_guardian",
    )
    assert child["parent_trace_id"] == parent["trace_id"]
    assert child["wake_id"] == parent["wake_id"]


def test_trace_error_path():
    t = close_trace(
        build_trace(trace_id="tr_e", wake_id="w1", agent="alex", role="cio_synthesis"),
        status="error",
        decision={"decision_id": "dec_1", "blocker": "sizing_unavailable"},
    )
    assert t["status"] == "error"
    assert t["decision"]["blocker"] == "sizing_unavailable"


def test_trace_redaction_strips_cot_and_secrets():
    t = build_trace(
        trace_id="tr_r",
        wake_id="w1",
        agent="alex",
        role="cio_synthesis",
        chain_of_thought="the model privately thinks X",
        api_key="sk-1234567890",
    )
    clean = sanitize_trace(t)
    assert "chain_of_thought" not in clean
    assert clean.get("api_key") == "[REDACTED]"


def test_trace_no_chain_of_thought_nested():
    t = build_trace(
        trace_id="tr_n",
        wake_id="w1",
        agent="alex",
        role="cio_synthesis",
        reasoning_runtime={"internal_monologue": "hidden", "model": "gpt"},
    )
    clean = sanitize_trace(t)
    assert "internal_monologue" not in clean.get("reasoning_runtime", {})
    assert clean["reasoning_runtime"]["model"] == "gpt"


def test_validate_rejects_cot():
    t = build_trace(trace_id="tr_v", wake_id="w1", agent="alex", role="cio_synthesis")
    t["chain_of_thought"] = "should not persist"
    ok, errs = validate_trace(t)
    assert not ok
    assert any("chain-of-thought" in x for x in errs)


def test_append_and_query_by_wake(tmp_path):
    p = _tmp_path(tmp_path)
    t = close_trace(
        build_trace(trace_id=new_trace_id("w1"), wake_id="w1", agent="alex", role="cio_synthesis"),
        decision={"decision_id": "dec_1"},
    )
    assert append_trace(t, path=p)
    rows = query_traces(wake_id="w1", path=p)
    assert len(rows) == 1
    assert rows[0]["decision"]["decision_id"] == "dec_1"


def test_query_by_decision_id(tmp_path):
    p = _tmp_path(tmp_path)
    append_trace(
        close_trace(
            build_trace(trace_id=new_trace_id("w1"), wake_id="w1", agent="alex", role="cio_synthesis"),
            decision={"decision_id": "dec_abc"},
        ),
        path=p,
    )
    rows = query_traces(decision_id="dec_abc", path=p)
    assert len(rows) == 1


def test_query_by_case_id(tmp_path):
    p = _tmp_path(tmp_path)
    append_trace(
        close_trace(
            build_trace(trace_id=new_trace_id("w1"), wake_id="w1", agent="alex", role="cio_synthesis"),
            learning={"case_id": "case_1"},
        ),
        path=p,
    )
    rows = query_traces(case_id="case_1", path=p)
    assert len(rows) == 1


def test_query_by_top_level_case_id(tmp_path):
    # Regression: the documented top-level case_id fallback must work even when
    # there is no ``learning.case_id`` (empty learning section).
    p = _tmp_path(tmp_path)
    append_trace(
        close_trace(
            build_trace(trace_id=new_trace_id("w1"), wake_id="w1", agent="alex", role="cio_synthesis"),
            case_id="case_top",
        ),
        path=p,
    )
    rows = query_traces(case_id="case_top", path=p)
    assert len(rows) == 1


def test_query_by_case_id_rejects_unrelated(tmp_path):
    p = _tmp_path(tmp_path)
    append_trace(
        close_trace(
            build_trace(trace_id=new_trace_id("w1"), wake_id="w1", agent="alex", role="cio_synthesis"),
            learning={"case_id": "case_1"},
        ),
        path=p,
    )
    append_trace(
        close_trace(
            build_trace(trace_id=new_trace_id("w2"), wake_id="w2", agent="alex", role="cio_synthesis"),
            case_id="case_top",
        ),
        path=p,
    )
    assert query_traces(case_id="case_none", path=p) == []
    assert len(query_traces(case_id="case_1", path=p)) == 1
    assert len(query_traces(case_id="case_top", path=p)) == 1


def test_append_persists_no_secrets(tmp_path):
    p = _tmp_path(tmp_path)
    t = build_trace(
        trace_id=new_trace_id("w1"),
        wake_id="w1",
        agent="alex",
        role="cio_synthesis",
        security={"api_key": "sk-secret-key-123"},
    )
    assert append_trace(t, path=p)
    raw = p.read_text()
    assert "sk-secret-key-123" not in raw
    assert "[REDACTED]" in raw


def test_append_fail_soft_bad_path():
    assert not append_trace(build_trace(trace_id="t", wake_id="w", agent="a", role="r"), path="/nonexistent_dir_zz/x.jsonl")


def test_stable_trace_digest():
    a = build_trace(trace_id="tr_1", wake_id="w1", agent="alex", role="cio_synthesis")
    b = build_trace(trace_id="tr_1", wake_id="w1", agent="alex", role="cio_synthesis")
    assert trace_digest(a) == trace_digest(b)


def test_trace_version():
    t = build_trace(trace_id="tr_1", wake_id="w1", agent="alex", role="cio_synthesis")
    assert t["trace_version"] == TRACE_VERSION
