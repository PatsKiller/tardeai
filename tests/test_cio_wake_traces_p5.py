"""P5 lightweight wake traces — fail-soft JSONL + list/filter."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def trace_path(tmp_path: Path) -> Path:
    return tmp_path / "cio_wake_traces.jsonl"


def test_open_update_close_merge(trace_path: Path):
    from scripts.lib.cio_wake_traces import close_trace, list_traces, open_trace, update_trace

    tid = open_trace(
        wake_id="wake_op_alex_1",
        source="OPERATOR_MESSAGE",
        agent_id="alex",
        path=trace_path,
    )
    assert tid
    update_trace(
        "wake_op_alex_1",
        llm="blocked_cap",
        plan_id="plan_x",
        path=trace_path,
    )
    close_trace(
        "wake_op_alex_1",
        outcome="deferred",
        duration_ms=12,
        path=trace_path,
    )
    rows = list_traces(limit=5, path=trace_path)
    assert len(rows) == 1
    m = rows[0]
    assert m["wake_id"] == "wake_op_alex_1"
    assert m["llm"] == "blocked_cap"
    assert m["plan_id"] == "plan_x"
    assert m["outcome"] == "deferred"
    assert m["source"] == "OPERATOR_MESSAGE"
    assert m.get("flags", {}).get("enrich_on") in (True, False)


def test_write_failure_does_not_raise(trace_path: Path, monkeypatch):
    from scripts.lib import cio_wake_traces as wt

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(wt, "_append_row", boom)
    # open_trace catches and returns None — must not raise
    assert wt.open_trace(wake_id="w1", source="heartbeat", path=trace_path) is None
    assert wt.update_trace("w1", llm="invoked", path=trace_path) is False
    assert wt.close_trace("w1", outcome="ok", path=trace_path) is False
    assert wt.emit_closed_trace(
        wake_id="hb_1", source="heartbeat", llm="skipped_non_material", path=trace_path
    ) is False


def test_append_row_oserror_swallowed(trace_path: Path, monkeypatch):
    from scripts.lib.cio_wake_traces import open_trace

    real_open = open

    def bad_open(path, *a, **k):
        if str(path).endswith(".jsonl"):
            raise OSError("ENOSPC")
        return real_open(path, *a, **k)

    with patch("builtins.open", bad_open):
        # open_trace uses open via _append_row — fail soft
        r = open_trace(wake_id="w_disk", source="other", path=trace_path)
        assert r is None or isinstance(r, str)


def test_blocked_cap_recorded_via_enrich(tmp_path: Path, monkeypatch):
    from scripts.lib.cio_plan_enrichment import enrich_plan
    from scripts.lib.cio_wake_traces import list_traces

    trace = tmp_path / "traces.jsonl"
    monkeypatch.setenv("CIO_LLM_ENRICH", "1")

    plan = {
        "plan_id": "plan_cap_1",
        "situation_type": "S1_POSITION_LIFECYCLE",
        "symbols": ["SPACEX_TEST"],
        "summary": "basis=210 last=138",
        "options": [{"id": "hold", "label": "Hold", "pros": "", "cons": ""}],
        "recommendation": "Review",
        "risks": ["dd"],
        "evidence_refs": [
            {
                "domain": "holdings_detail",
                "fields_used": ["basis", "last"],
                "basis": 210.0,
                "last": 138.0,
            }
        ],
        "owner_agent": "alex",
        "authority": "READ_ONLY_ADVISORY",
    }
    # Force local hour cap
    monkeypatch.setattr(
        "scripts.lib.cio_plan_enrichment._local_hour_calls",
        lambda *a, **k: 999,
    )
    # Point traces at tmp
    monkeypatch.setattr(
        "scripts.lib.cio_wake_traces.DEFAULT_TRACE_PATH",
        trace,
    )
    # Also open path used by safe_* via DEFAULT
    from scripts.lib import cio_wake_traces as wt

    monkeypatch.setattr(wt, "DEFAULT_TRACE_PATH", trace)

    res = enrich_plan(
        plan,
        source="S1_POSITION_LIFECYCLE",
        wake_id="wake_sit_cap",
        force_template=False,
        force_llm=False,
    )
    assert res["llm"] == "blocked_cap"
    assert res.get("narrative_source") == "template"

    rows = list_traces(limit=5, path=trace, llm="blocked_cap")
    assert rows, "expected blocked_cap trace"
    assert rows[0]["llm"] == "blocked_cap"
    assert rows[0]["outcome"] in ("deferred", "ok")
    assert rows[0].get("plan_id") == "plan_cap_1"


def test_skipped_non_material(tmp_path: Path, monkeypatch):
    from scripts.lib.cio_plan_enrichment import enrich_plan
    from scripts.lib.cio_wake_traces import list_traces
    from scripts.lib import cio_wake_traces as wt

    trace = tmp_path / "t.jsonl"
    monkeypatch.setattr(wt, "DEFAULT_TRACE_PATH", trace)
    monkeypatch.setattr(
        "scripts.lib.cio_wake_traces.DEFAULT_TRACE_PATH",
        trace,
    )

    res = enrich_plan(
        {"plan_id": "p_nm", "situation_type": "X", "owner_agent": "alex"},
        source="system.heartbeat_ok",
        wake_id="wake_hb_nm",
    )
    assert res["llm"] == "skipped_non_material"
    rows = list_traces(limit=5, path=trace)
    assert any(r.get("llm") == "skipped_non_material" for r in rows)


def test_emit_heartbeat_closed(tmp_path: Path):
    from scripts.lib.cio_wake_traces import emit_closed_trace, list_traces

    p = tmp_path / "hb.jsonl"
    ok = emit_closed_trace(
        wake_id="hb_snap_1",
        source="heartbeat",
        llm="skipped_non_material",
        outcome="ok",
        duration_ms=5,
        path=p,
    )
    assert ok
    rows = list_traces(limit=3, path=p, source="heartbeat")
    assert len(rows) == 1
    assert rows[0]["llm"] == "skipped_non_material"


def test_list_filter_plan_and_format(trace_path: Path):
    from scripts.lib.cio_wake_traces import (
        close_trace,
        format_traces,
        list_traces,
        open_trace,
    )

    open_trace(wake_id="w1", source="GOAL_DUE", plan_id="plan_a", path=trace_path)
    close_trace("w1", llm="invoked", plan_id="plan_a", outcome="ok", path=trace_path)
    open_trace(wake_id="w2", source="OPERATOR_MESSAGE", plan_id="plan_b", path=trace_path)
    close_trace("w2", llm="blocked_cap", plan_id="plan_b", outcome="deferred", path=trace_path)

    only_b = list_traces(limit=10, plan_id="plan_b", path=trace_path)
    assert len(only_b) == 1
    assert only_b[0]["llm"] == "blocked_cap"

    caps = list_traces(limit=10, llm="blocked_cap", path=trace_path)
    assert len(caps) == 1

    text = format_traces(list_traces(limit=10, path=trace_path), max_chars=500)
    assert "wake traces" in text.lower() or "CIO" in text
    assert "blocked_cap" in text


def test_safe_open_from_wake_payload(trace_path: Path, monkeypatch):
    from scripts.lib.cio_wake_traces import list_traces, safe_open_from_wake_payload

    safe_open_from_wake_payload(
        {
            "wake_job_id": "wake_op_alex_99",
            "trigger_type": "OPERATOR_MESSAGE",
            "reason_codes": ["OPERATOR_MESSAGE"],
            "context": {"target_agent": "alex", "plan_id": None},
        },
        path=trace_path,
    )
    rows = list_traces(limit=5, path=trace_path)
    assert rows
    assert rows[0]["source"] == "OPERATOR_MESSAGE"


def test_enqueue_opens_trace(tmp_path: Path, monkeypatch):
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore
    from scripts.lib.cio_wake_traces import list_traces
    from scripts.lib import cio_wake_traces as wt

    monkeypatch.setattr(wt, "DEFAULT_TRACE_PATH", tmp_path / "traces.jsonl")
    store = CIOWakeJobStore(event_store_path=tmp_path / "wakes.jsonl")
    store.enqueue(
        {
            "wake_job_id": "wake_op_alex_test_p5",
            "trigger_type": "OPERATOR_MESSAGE",
            "trigger_ref": "m1",
            "trigger_hash": "abc",
            "reason_codes": ["OPERATOR_MESSAGE"],
            "wake_intent": "NEW_RUN",
            "idempotency_key": "wake_op_alex_test_p5",
            "context": {"target_agent": "alex"},
        },
        actor_id="test",
        authority="READ_ONLY_ADVISORY",
    )
    rows = list_traces(limit=5, path=tmp_path / "traces.jsonl")
    assert any(r.get("wake_id") == "wake_op_alex_test_p5" for r in rows)
