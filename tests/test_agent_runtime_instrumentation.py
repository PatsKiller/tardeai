"""AIF runtime instrumentation — flag-gated material-wake observability tests.

Proves the OFF parity contract, the ON lineage contract (single wake_id/
trace_id propagated downstream), fail-soft behavior, and zero decision mutation.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_runtime_instrumentation import (  # noqa: E402
    instrument_material_wake,
)
from scripts.lib.agent_feature_flags import load_feature_flags  # noqa: E402


def _flags(**kw):
    base = load_feature_flags({})
    base.update(kw)
    return base


class _BrokenMemory:
    name = "BrokenMemory"

    def health(self):
        return True

    def search(self, **kw):
        raise RuntimeError("boom")


def test_flags_off_parity():
    res = instrument_material_wake(
        {"wake_id": "w1"},
        flags=_flags(AGENT_CONTEXT_ENVELOPE=0, AGENT_RUN_TRACE=0),
    )
    assert res["instrumented"] is False
    assert res["trace_id"] is None
    assert res["envelope"] is None
    assert res["trace"] is None
    assert res["trace_appended"] is False
    assert res["errors"] == []


def test_context_envelope_on_builds_envelope():
    res = instrument_material_wake(
        {"wake_id": "w1"},
        flags=_flags(AGENT_CONTEXT_ENVELOPE=1, AGENT_RUN_TRACE=0),
    )
    assert res["instrumented"] is True
    assert res["envelope"] is not None
    assert res["envelope"]["wake_id"] == "w1"
    assert res["trace"] is None
    assert res["trace_appended"] is False


def test_run_trace_on_builds_and_appends(tmp_path):
    tp = tmp_path / "traces.jsonl"
    res = instrument_material_wake(
        {"wake_id": "w1"},
        flags=_flags(AGENT_CONTEXT_ENVELOPE=0, AGENT_RUN_TRACE=1),
        trace_path=tp,
    )
    assert res["instrumented"] is True
    assert res["trace"] is not None
    assert res["trace"]["wake_id"] == "w1"
    assert res["trace"]["trace_id"] == res["trace_id"]
    assert res["trace_appended"] is True
    assert tp.exists()
    assert res["trace_id"] in tp.read_text()


def test_same_wake_and_trace_lineage_downstream(tmp_path):
    tp = tmp_path / "traces.jsonl"
    res = instrument_material_wake(
        {"wake_id": "w1"},
        flags=_flags(AGENT_CONTEXT_ENVELOPE=1, AGENT_RUN_TRACE=1),
        trace_path=tp,
    )
    assert res["instrumented"] is True
    assert res["envelope"]["wake_id"] == "w1"
    assert res["trace"]["wake_id"] == "w1"
    assert res["trace"]["trace_id"] == res["trace_id"]
    # The envelope's provenance carries the same trace lineage.
    assert res["envelope"]["trace_id"] == res["trace_id"]
    assert res["trace_appended"] is True


def test_context_failure_fails_soft():
    # A broken memory provider must never crash the hook. get_context_for_agent
    # fail-softs internally, so the envelope is still built but its episodic
    # memory section honestly reports ERROR (never fabricates truth).
    from scripts.lib.agent_context_envelope import RETRIEVAL_ERROR  # noqa: E402

    res = instrument_material_wake(
        {"wake_id": "w1"},
        flags=_flags(AGENT_CONTEXT_ENVELOPE=1, AGENT_RUN_TRACE=0),
        memory_provider=_BrokenMemory(),
    )
    assert res["instrumented"] is True
    assert res["envelope"] is not None
    assert res["envelope"]["episodic_memory"]["retrieval_status"] == RETRIEVAL_ERROR


def test_trace_failure_fails_soft(tmp_path):
    # A trace path whose parent is a regular file cannot be created; append_trace
    # must fail soft (return False) and never raise.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    bad_path = blocker / "traces.jsonl"
    res = instrument_material_wake(
        {"wake_id": "w1"},
        flags=_flags(AGENT_CONTEXT_ENVELOPE=0, AGENT_RUN_TRACE=1),
        trace_path=bad_path,
    )
    # build_trace itself succeeds; append_trace fails soft and returns False.
    assert res["trace"] is not None
    assert res["trace_appended"] is False


def test_no_decision_mutation():
    decision = {
        "decision_id": "dec_1",
        "action": "HOLD",
        "delta_usd": 0.0,
        "current_action": "HOLD",
    }
    original = dict(decision)
    instrument_material_wake(
        {"wake_id": "w1"},
        flags=_flags(AGENT_CONTEXT_ENVELOPE=1, AGENT_RUN_TRACE=1),
        decision_ids=["dec_1"],
    )
    assert decision == original


def test_canonical_flags_off_by_default():
    # No environment overrides => both observability flags off, influence off.
    flags = load_feature_flags({})
    assert flags["AGENT_CONTEXT_ENVELOPE"] == 0
    assert flags["AGENT_RUN_TRACE"] == 0
    assert flags["MEMORY_BEHAVIOR_INFLUENCE"] == 0


def test_scan_hook_returns_none_when_flags_off(monkeypatch):
    from scripts.lib import cio_material_scan as ms  # noqa: E402

    for k in ("AGENT_CONTEXT_ENVELOPE", "AGENT_RUN_TRACE"):
        monkeypatch.delenv(k, raising=False)
    assert ms._instrument_scan([], at="2026-08-17T00:00:00+00:00") is None
