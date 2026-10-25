"""Native Jobs integration with the frozen owner producer, on disposable roots only."""
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import quote

import pytest

API = pytest.importorskip("scripts.lib.conflicts.api", reason="W10 canonical producer dependency must be integrated first")
from scripts.lib.conflicts import adapters as A
from scripts.lib.conflicts.ledger import ConflictLedger
from scripts.lib import jobs_conflict_errors as C, jobs_health as J

NOW = datetime(2026, 10, 24, 22, tzinfo=timezone.utc)


def snapshot(root):
    return {str(p.relative_to(root)): (sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()} if root.exists() else {}


def populated(root):
    # The canonical engine produces the DATA_ERROR; W4 does not classify this fixture.
    bundle = A.numeric_inputs("fixture-count", {"source": "Canonical fixture count", "value": 10,
        "as_of": NOW.isoformat(), "subject_id": "fixture-count"},
        [{"source": "Reader fixture count", "value": 20, "as_of": NOW.isoformat(), "subject_id": "fixture-count"}], unit="count")
    findings = A.evaluate_inputs(bundle, now=NOW)
    assert findings and all(f.kind == "DATA_ERROR" for f in findings)
    ledger = ConflictLedger(root)
    ledger.reconcile(bundle.subject, findings, at=NOW, apply=True)
    return ledger, findings


def refuse_writers(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A read attempted to enter an owner writer")
    for name in ("locked", "_append", "drain", "reconcile", "transition"):
        monkeypatch.setattr(ConflictLedger, name, forbidden)


def test_native_missing_ledger_preserves_named_gap_without_creating_state(tmp_path, monkeypatch):
    root = tmp_path / "absent-state-root"
    refuse_writers(monkeypatch)
    expected = API.data_error_section(root=root)
    result = C.get_data_errors(root)
    assert result["section"] == expected and result["unavailable_reason"] is None
    assert result["section"]["gap"]["reason"] == "conflict ledger not yet produced"
    assert result["section"]["headline"] is None
    assert not root.exists()


def test_native_engine_section_is_unchanged_and_read_never_calls_writer(tmp_path, monkeypatch):
    ledger, findings = populated(tmp_path)
    before = snapshot(tmp_path)
    refuse_writers(monkeypatch)
    expected = API.data_error_section(root=tmp_path)
    result = C.get_data_errors(tmp_path)
    assert result == {"section": expected, "unavailable_reason": None}
    assert [f["key"] for f in result["section"]["findings"]] == [f["key"] for f in expected["findings"]]
    assert result["section"]["headline"]
    assert result["section"]["findings"][0]["rule"] == findings[0].rule
    assert result["section"]["source"] == "conflict_events.jsonl"
    assert snapshot(tmp_path) == before


def test_native_selected_get_returns_full_matching_history_without_poll_write(tmp_path, monkeypatch):
    ledger, findings = populated(tmp_path)
    key = findings[0].key
    before = snapshot(tmp_path)
    refuse_writers(monkeypatch)
    status, record = API.handle("/api/v3/conflicts/" + quote(key, safe=""), "GET", root=tmp_path)
    assert status == 200 and record["schema"] == "ConflictRecord@v1" and record["key"] == key
    assert record["state"] == "OPEN" and record["decision"] is None
    assert record["history"] and all(event["key"] == key for event in record["history"])
    assert record["summary"] == findings[0].summary
    assert snapshot(tmp_path) == before


def test_native_corrupt_ledger_is_a_canonical_gap_and_remains_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "data/conflicts/conflict_events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"truncated fixture event\n")
    before = snapshot(tmp_path)
    refuse_writers(monkeypatch)
    result = C.get_data_errors(tmp_path)
    assert result["unavailable_reason"] is None
    assert result["section"]["gap"]["reason"] == "conflict ledger unavailable or invalid"
    assert result["section"]["headline"] is None
    assert snapshot(tmp_path) == before


def test_native_public_jobs_read_passes_canonical_section_separate_from_job_failures(tmp_path, monkeypatch):
    populated(tmp_path)
    registry = tmp_path / "fixture-registry.json"
    registry.write_bytes(b'{"lanes":[]}')
    expected = API.data_error_section(root=tmp_path)
    before = snapshot(tmp_path)
    refuse_writers(monkeypatch)
    result = J.get_jobs_health({"filter": "all", "limit": 1}, state_root=tmp_path, registry_path=registry, now=NOW)
    assert result["data_errors"] == {"section": expected, "unavailable_reason": None}
    assert result["summary"]["failed"] == 0 and result["summary"]["missed"] == 0
    assert result["rows"] == [] and result["total"] == 0
    assert snapshot(tmp_path) == before
