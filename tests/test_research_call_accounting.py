from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from scripts.lib.research_call_accounting import (
    add_reservation_only_events,
    append_event,
    call_id_for,
    read_events,
    summarize,
)


def _event(path, event, *, call_id="rc_1", family="A", producer="research_scheduler", **extra):
    return append_event(
        event,
        producer=producer,
        family=family,
        run_id="run_1",
        call_id=call_id,
        symbol="NOC",
        lane="deepseek",
        trigger="research_scheduler",
        path=path,
        **extra,
    )


def test_complete_call_reconciles_without_double_counting_events(tmp_path):
    path = tmp_path / "calls.jsonl"
    _event(path, "SCHEDULED")
    _event(path, "SCHEDULED")  # producer and choke point may both assert intent
    _event(path, "ATTEMPTED", attempt_no=1)
    _event(path, "COMPLETED", attempt_no=1)
    report = summarize(read_events(path, hours=24))
    assert report["calls"] == 1
    assert report["calls_scheduled"] == 1
    assert report["calls_actually_attempted"] == 1
    assert report["completed"] == 1
    assert report["family_a"] == 1
    assert report["unresolved_call_ids"] == []
    assert report["reconciled"] is True


def test_second_no_change_call_is_deduped_not_attempted(tmp_path):
    path = tmp_path / "calls.jsonl"
    first = call_id_for("run_1", "NOC", "deepseek")
    second = call_id_for("run_2", "NOC", "deepseek")
    _event(path, "SCHEDULED", call_id=first)
    _event(path, "ATTEMPTED", call_id=first, attempt_no=1)
    _event(path, "COMPLETED", call_id=first, attempt_no=1)
    append_event(
        "SCHEDULED", producer="research_scheduler", family="A", run_id="run_2",
        call_id=second, symbol="NOC", lane="deepseek", trigger="research_scheduler", path=path,
    )
    append_event(
        "DEDUPED", producer="research_scheduler", family="A", run_id="run_2",
        call_id=second, symbol="NOC", lane="deepseek", trigger="research_scheduler",
        reason="hash_match_in_window", path=path,
    )
    report = summarize(read_events(path, hours=24))
    assert report["calls_scheduled"] == 2
    assert report["calls_actually_attempted"] == 1
    assert report["deduped"] == 1
    assert report["completed"] == 1
    assert report["reconciled"] is True


def test_retry_and_family_b_are_attributed(tmp_path):
    path = tmp_path / "calls.jsonl"
    _event(path, "SCHEDULED", family="B", producer="hermes_top20_external_intel")
    _event(path, "ATTEMPTED", family="B", producer="hermes_top20_external_intel", attempt_no=1)
    _event(
        path, "RETRY", family="B", producer="hermes_top20_external_intel",
        attempt_no=3, metadata={"retry_count": 2},
    )
    _event(path, "ERROR", family="B", producer="hermes_top20_external_intel", attempt_no=3)
    report = summarize(read_events(path, hours=24))
    assert report["family_b"] == 1
    assert report["retry"] == 2
    assert report["error"] == 1
    assert report["reconciled"] is True


def test_cost_cap_before_provider_is_not_an_attempt(tmp_path):
    path = tmp_path / "calls.jsonl"
    _event(path, "SCHEDULED")
    _event(path, "COST_CAP_EXCEEDED", reason="daily request cap")
    report = summarize(read_events(path, hours=24))
    assert report["calls_scheduled"] == 1
    assert report["cost_cap_exceeded"] == 1
    assert report["calls_actually_attempted"] == 0
    assert report["reconciled"] is True


def test_reservation_without_consumption_gets_stable_terminal_classification():
    now = datetime.now(timezone.utc)
    reservations = [{
        "id": 77,
        "created_at": now - timedelta(hours=2),
        "process_id": "hermes_external_research",
        "status": "released",
        "metadata_json": json.dumps({"lane": "fast"}),
    }]
    out = add_reservation_only_events([], reservations, [], now=now)
    assert out[0]["event"] == "RESERVATION_ONLY"
    assert out[0]["call_id"] == "reservation:77"
    assert out[0]["family"] == "A"
    report = summarize(out)
    assert report["reservation_only"] == 1
    assert report["reconciled"] is True


def test_inflight_reservation_is_not_prematurely_classified():
    now = datetime.now(timezone.utc)
    reservations = [{
        "id": 88,
        "created_at": now - timedelta(minutes=5),
        "process_id": "hermes_external_research",
        "status": "reserved",
        "metadata_json": {},
    }]
    assert add_reservation_only_events([], reservations, [], now=now) == []


def test_authority_and_no_financial_writes_are_immutable(tmp_path):
    path = tmp_path / "calls.jsonl"
    row = _event(path, "DRY_RUN", apply=False)
    assert row["authority"] == "READ_ONLY_ADVISORY"
    assert row["financial_writes"] == 0
    assert row["apply"] is False
