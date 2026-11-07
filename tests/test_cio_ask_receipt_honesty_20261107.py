"""LQ-20261107-183: the cio-ask-material-events receipt must not call a failed source "no new events"."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.lib import cio_ask_lifecycle as life
from scripts.lib.cio_ask_material_sources import SecFilingEventsFile
from tests.test_cio_ask_hourly_20261026 import fixture, provider, run

SINCE = datetime(2026, 11, 6, tzinfo=timezone.utc)


def test_missing_sec_file_is_an_error_but_an_empty_file_is_empty(tmp_path):
    with pytest.raises(FileNotFoundError):
        SecFilingEventsFile(tmp_path / "absent.jsonl").fetch({"g"}, SINCE)
    present = tmp_path / "empty.jsonl"
    present.write_text("")
    assert SecFilingEventsFile(present).fetch({"g"}, SINCE) == []


def _boom(*_a, **_k):
    raise RuntimeError("feed down")


def test_missing_file_lands_in_source_errors_and_not_no_new_events(tmp_path):
    d = fixture(tmp_path, provider=provider([]))
    src = SecFilingEventsFile(tmp_path / "absent.jsonl")
    result = run(d, events_only=True, event_sources=[src])
    assert result["ok"] is False
    assert result["source_errors"] == ["sec_filing_events:FileNotFoundError"]
    assert life.receipt_empty_reason(result, events_only=True, has_outputs=False) == "source_error"


def test_one_source_erroring_and_another_empty_is_still_not_no_new_events(tmp_path):
    d = fixture(tmp_path, provider=provider([]))
    empty = SimpleNamespace(name="material_changes", fetch=lambda g, s: [])
    bad = SimpleNamespace(name="sec_filing_events", fetch=_boom)
    result = run(d, events_only=True, event_sources=[empty, bad])
    assert result["source_errors"] == ["sec_filing_events:RuntimeError"]
    assert result["ok"] is False
    assert life.receipt_empty_reason(result, events_only=True, has_outputs=False) == "source_error"


def test_happy_path_empty_reason_is_unchanged(tmp_path):
    d = fixture(tmp_path, provider=provider([]))
    empty = SimpleNamespace(name="material_changes", fetch=lambda g, s: [])
    result = run(d, events_only=True, event_sources=[empty])
    assert result["ok"] is True and result["source_errors"] == []
    assert life.receipt_empty_reason(result, events_only=True, has_outputs=False) == "no_new_events"
    assert life.receipt_empty_reason(result, events_only=False, has_outputs=False) == "no_due_threads"
    assert life.receipt_empty_reason({"tracked_threads": 0}, events_only=True, has_outputs=False) == "no_tracked_threads"
    assert life.receipt_empty_reason(result, events_only=True, has_outputs=True) is None
