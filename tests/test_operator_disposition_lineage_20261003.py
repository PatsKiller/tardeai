"""Flight recorder: operator_disposition stage wiring (Phase C).

operator_disposition was MISSING: decision_dispositions.jsonl was read-only advisory
with no producer persisting operator decisions to cio_workflow_lineage, leaving the
stage UNKNOWN instead of LIVE during decision lineage projection.

This test verifies that DispositionRecorder.record() writes disposition records
that the lineage projection can match by decision_id and derive LIVE.
"""
from pathlib import Path

import pytest

from scripts.lib.cio_decision_disposition import (
    DispositionRecorder,
    record_disposition,
)


def test_record_disposition_persists_fields(tmp_path: Path):
    """Disposition fields persist to file."""
    path = tmp_path / "dispositions.jsonl"
    decision_id = "decision_op_1"

    recorder = DispositionRecorder(path)
    result = recorder.record(
        decision_id=decision_id,
        disposition="APPROVED",
        rationale="Aligns with portfolio strategy",
        disposed_by="operator_alice",
        metadata={"confidence": "high", "tags": ["reviewed"]},
    )

    assert result is True
    assert path.exists()

    # Verify persisted record
    latest = recorder.latest_for_decision(decision_id)
    assert latest is not None
    assert latest.get("disposition") == "APPROVED"
    assert latest.get("rationale") == "Aligns with portfolio strategy"
    assert latest.get("disposed_by") == "operator_alice"
    assert latest.get("decision_id") == decision_id
    assert latest.get("confidence") == "high"


def test_record_disposition_module_function(tmp_path: Path):
    """Module-level record_disposition function works."""
    path = tmp_path / "dispositions.jsonl"
    decision_id = "decision_op_2"

    result = record_disposition(
        decision_id=decision_id,
        disposition="REJECTED",
        rationale="Risk exceeds mandate",
        disposed_by="operator_bob",
        path=path,
    )

    assert result is True

    # Verify with DispositionRecorder
    recorder = DispositionRecorder(path)
    latest = recorder.latest_for_decision(decision_id)
    assert latest is not None
    assert latest.get("disposition") == "REJECTED"


def test_disposition_with_multiple_decisions(tmp_path: Path):
    """Multiple dispositions for different decisions are tracked separately."""
    path = tmp_path / "dispositions.jsonl"
    recorder = DispositionRecorder(path)

    # Record dispositions for two different decisions
    result1 = recorder.record(
        decision_id="decision_1",
        disposition="APPROVED",
        disposed_by="alice",
    )
    result2 = recorder.record(
        decision_id="decision_2",
        disposition="HOLD_FOR_REVIEW",
        disposed_by="bob",
    )

    assert result1 is True
    assert result2 is True

    # Retrieve each disposition
    d1 = recorder.latest_for_decision("decision_1")
    d2 = recorder.latest_for_decision("decision_2")

    assert d1 is not None and d1.get("disposition") == "APPROVED"
    assert d2 is not None and d2.get("disposition") == "HOLD_FOR_REVIEW"


def test_disposition_idempotent_on_semantic_duplicate(tmp_path: Path):
    """Same disposition (same decision + disposition + rationale) returns False on duplicate."""
    path = tmp_path / "dispositions.jsonl"
    recorder = DispositionRecorder(path)

    result1 = recorder.record(
        decision_id="decision_dup_1",
        disposition="APPROVED",
        rationale="Good decision",
        disposed_by="alice",
    )

    # Exact duplicate should return False
    result2 = recorder.record(
        decision_id="decision_dup_1",
        disposition="APPROVED",
        rationale="Good decision",
        disposed_by="charlie",  # Different operator, same semantic content
    )

    assert result1 is True
    assert result2 is False, "Semantic duplicate should not be written"


def test_disposition_requires_decision_id(tmp_path: Path):
    """Cannot record disposition without decision_id."""
    path = tmp_path / "dispositions.jsonl"
    recorder = DispositionRecorder(path)

    result = recorder.record(
        decision_id="",
        disposition="APPROVED",
        rationale="Something",
    )

    assert result is False


def test_disposition_requires_disposition(tmp_path: Path):
    """Cannot record disposition without disposition field."""
    path = tmp_path / "dispositions.jsonl"
    recorder = DispositionRecorder(path)

    result = recorder.record(
        decision_id="decision_test",
        disposition="",
    )

    assert result is False


def test_disposition_timestamp_defaulting(tmp_path: Path):
    """disposed_at defaults to now if not provided."""
    path = tmp_path / "dispositions.jsonl"
    recorder = DispositionRecorder(path)

    result = recorder.record(
        decision_id="decision_ts_1",
        disposition="APPROVED",
    )

    assert result is True

    latest = recorder.latest_for_decision("decision_ts_1")
    assert latest is not None
    assert latest.get("disposed_at") is not None
    # Should be recent timestamp
    assert "T" in latest.get("disposed_at", "")
