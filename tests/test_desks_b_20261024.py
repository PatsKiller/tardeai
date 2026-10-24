"""Research lineage projections: pinned evidence, paging, and no writer side effects."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from lib import desks_b as desk
from scripts import api_v3_intelligence as api

NOW = datetime(2026, 10, 24, 22, tzinfo=timezone.utc)


def event(stream, kind="ENQUEUED", *, age=24, payload=None, metadata=None):
    return {"stream_id": stream, "event_type": "HERMES_CHALLENGE_" + kind,
            "occurred_at": (NOW - timedelta(hours=age)).isoformat(),
            "payload": {"source": "fixture evidence", **(payload or {})},
            "metadata": {"symbols": ["FIXT"], **(metadata or {})}}


def write_sources(root, events):
    (root / "hermes_challenge_queue.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")
    (root / "intelligence_lineages.json").write_text(json.dumps({
        "generated_at": (NOW - timedelta(minutes=10)).isoformat(), "count": 1,
        "lineages": [{"lineage_id": "fixture-chain", "symbol": "FIXT", "status": "ADVISORY_USED"}],
    }), encoding="utf-8")


def test_projection_preserves_opening_age_evidence_and_terminal_reason(tmp_path):
    write_sources(tmp_path, [
        event("older", age=300, metadata={"research_id": "fixture-research"}),
        event("older", "CLAIMED", age=1, payload={"claimed_by": "fixture-reviewer"}, metadata={"symbols": []}),
        event("pending", age=20),
        event("done", age=50),
        event("done", "RESOLVED", age=2, payload={"resolution_note": "Evidence checked."}),
    ])
    out = desk.research_lineage(root=tmp_path, now=NOW)
    assert out["ok"] and out["total"] == 2
    assert out["items"][0]["stream_id"] == "older"
    assert out["items"][0]["age_hours"] == 300
    assert out["items"][0]["research_id"] == "fixture-research"
    assert out["items"][0]["reviewer"] == "fixture-reviewer"
    assert out["items"][0]["stuck_reason"] == "Claimed by a reviewer; no start is recorded."
    assert out["throughput"]["opened"] == 2
    assert out["throughput"]["closed"] == 1
    assert out["throughput"]["net_change"] == 1
    completed = desk.research_lineage({"view": "completed"}, root=tmp_path, now=NOW)
    assert completed["total"] == 1
    assert completed["items"][0]["resolution_reason"] == "Evidence checked."


def test_source_evidence_not_inferred_and_future_dates_not_counted(tmp_path):
    rows = [event("missing", payload={"source": None}), event("future", age=-10)]
    write_sources(tmp_path, rows)
    out = desk.research_lineage(root=tmp_path, now=NOW)
    by_id = {row["stream_id"]: row for row in out["items"]}
    assert by_id["missing"]["stuck_reason"] == "No source evidence is recorded."
    assert by_id["future"]["age_hours"] is None
    assert out["throughput"]["opened"] == 1


def test_pages_have_real_totals_and_maximum_50_rows(tmp_path):
    write_sources(tmp_path, [event(f"fixture-{i}", age=i + 1) for i in range(123)])
    first = desk.research_lineage({"per_page": 5000}, root=tmp_path, now=NOW)
    third = desk.research_lineage({"page": 3}, root=tmp_path, now=NOW)
    assert first["total"] == third["total"] == 123
    assert len(first["items"]) == first["per_page"] == 50 and first["has_more"]
    assert len(third["items"]) == 23 and not third["has_more"]
    assert set(row["stream_id"] for row in first["items"]).isdisjoint(row["stream_id"] for row in third["items"])


@pytest.mark.parametrize("contents", [None, "{bad-json}", '[]\n', json.dumps(event("bad", metadata={"symbols": []})) + '\n' + '{bad-json}\n'])
def test_missing_or_corrupt_history_is_unknown_and_never_written(tmp_path, contents):
    path = tmp_path / "hermes_challenge_queue.jsonl"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    out = desk.research_lineage(root=tmp_path, now=NOW)
    assert not out["ok"] and out["total"] is None
    assert out["backlog"]["pending"] is None and out["throughput"]["opened"] is None
    assert out["items"] == [] and out["gaps"]
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_empty_produced_history_is_measured_zero(tmp_path):
    write_sources(tmp_path, [])
    out = desk.research_lineage(root=tmp_path, now=NOW)
    assert out["ok"] and out["total"] == 0 and out["backlog"]["pending"] == 0


def test_unrecognized_lifecycle_or_malformed_evidence_fails_closed(tmp_path):
    for row in [event("unknown", "NEW_UNKNOWN_EVENT"), {**event("bad"), "metadata": ["invalid"]}]:
        write_sources(tmp_path, [row])
        out = desk.research_lineage(root=tmp_path, now=NOW)
        assert out["total"] is None and out["gaps"]


def test_authority_is_separate_and_auto_expiry_cannot_be_enabled_by_query(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    code, authority = api.handle_get("authority", {"auto_expire": "true", "days": "7"})
    assert code == 200 and "lineages" not in authority
    assert authority["auto_expire"] == {
        "enabled": False, "days": None, "editable": False,
        "reason": "Operator decision pending: choose an expiry age before enabling a rule.",
    }
    assert list(tmp_path.iterdir()) == []


def test_api_reads_paged_views_and_reports_missing_snapshot(tmp_path, monkeypatch):
    write_sources(tmp_path, [event("fixture")])
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    for route, view in [("backlog", "backlog"), ("research-lineage", "lineage"), ("completed", "completed")]:
        code, body = api.handle_get(route, {"per_page": "1"})
        assert code == 200 and body["view"] == view and body["per_page"] == 1
    code, body = api.handle_get("throughput")
    assert code == 200 and "items" not in body and "throughput" in body


def test_lineage_snapshot_wrong_shape_is_an_explicit_gap(tmp_path):
    write_sources(tmp_path, [])
    (tmp_path / "intelligence_lineages.json").write_text('{"count":4}', encoding="utf-8")
    out = desk.research_lineage({"view": "lineage"}, root=tmp_path, now=NOW)
    assert not out["ok"] and out["total"] is None and out["gaps"]


def test_lineage_list_excludes_large_evidence_and_does_not_invent_missing_counts(tmp_path):
    write_sources(tmp_path, [])
    path = tmp_path / "intelligence_lineages.json"
    snap = json.loads(path.read_text())
    snap["lineages"][0].update({"transitions": ["large evidence"] * 10000,
                                "advisory_use": [], "research_request_ids": "invalid"})
    path.write_text(json.dumps(snap))
    out = desk.research_lineage({"view": "lineage"}, root=tmp_path, now=NOW)
    row = out["items"][0]
    assert "transitions" not in row and row["research_request_count"] is None
    assert row["memory_count"] is None and row["decision_changed"] is None
    assert len(json.dumps(out)) < 4000
