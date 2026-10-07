"""Comparison labels. A green execution without an artifact is not consumption."""
from __future__ import annotations

from scripts.lib.n8n_pilot_compare import NOT_MEASURED, compare_chain


def test_green_execution_without_output_is_unconsumed():
    report = compare_chain(event={"event_id": "evt-1"}, artifact=None, consumer=None, execution_green=True)
    assert report["state"] == "UNCONSUMED"
    assert report["reason"] == "n8n_success_without_durable_output"
    assert report["execution_green_is_receipt"] is False
    assert report["natural_opportunities"] == NOT_MEASURED
    assert report["sends"] is False


def test_artifact_without_consumer_and_expected_silence():
    report = compare_chain(
        event={"event_id": "evt-1", "source_timestamp": "2026-10-07T11:30:00+00:00"},
        artifact={"path": "data/runtime/x.json", "written_at": "2026-10-07T11:31:00+00:00"},
        consumer=None,
    )
    assert report["state"] == "ARTIFACT_WRITTEN"
    assert report["cost"] == NOT_MEASURED
    silent = compare_chain(
        event={"event_id": "evt-2"},
        artifact={"path": "data/runtime/x.json", "expected_silent": True},
        consumer=None,
    )
    assert silent["state"] == "EXPECTED_SILENT"


def test_consumer_hash_mismatch_is_visible():
    report = compare_chain(
        event={"event_id": "evt-3", "duplicate": True},
        artifact={"artifact_id": "a", "content_hash": "aaa", "cost_usd": 0},
        consumer={"consumer": "desk", "receipt_id": "r1", "content_hash": "bbb"},
    )
    assert report["state"] == "CONSUMED"
    assert report["content_delta"] == "different"
    assert report["duplicate"] is True
    assert report["cost"] == 0
