from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from scripts.conflict_resolver import fixture_inputs, run
from scripts.lib.conflicts.adapters import security_inputs
from scripts.lib.conflicts.engine import Input
from scripts.lib.conflicts.ledger import ConflictLedger

NOW = datetime(2026, 10, 23, 19, tzinfo=timezone.utc)


def bundle(stance="WATCH", extra="ADD"):
    return security_inputs(security_guid="guid", symbol="SYM", held=False,
        canonical={"stance": stance, "as_of": NOW.isoformat()}, extras=[Input("desk", extra, NOW)])


def test_dry_run_is_write_free_even_with_absent_root(tmp_path):
    root = tmp_path / "absent"
    result = run(root, [bundle()], now=NOW, run_id="dry")
    assert result["phase"] == "dry_run" and result["events_written"] == result["notifications"] == 0
    assert not root.exists()


def test_shadow_writes_real_report_standard_attempt_receipt_and_no_notifications(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_RUN_ID", "shadow-one")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")
    monkeypatch.setenv("TRADEAI_CODE_SHA", "fixture-sha")
    result = run(tmp_path, [bundle()], now=NOW, shadow=True, run_id="shadow-one", memory_writer=lambda event: True)
    assert result["notifications"] == 0 and result["events_written"] == 0
    report_path = tmp_path / "data/conflicts/reports" / (hashlib.sha256(b"shadow-one").hexdigest() + ".json")
    assert json.loads(report_path.read_text())["input_manifest_sha256"] == result["input_manifest_sha256"]
    receipt = json.loads((tmp_path / "data/runtime/lane_attempts/conflict-resolver/shadow-one.json").read_text())
    assert receipt["schema"] == "LaneRunReceipt@v2" and receipt["produced_count"] == 1
    assert receipt["mode"] == "live" and receipt["summary"]["phase"] == "shadow" and receipt["exit"] == 0
    assert receipt["output_evidence"][0]["sha256"] == hashlib.sha256(report_path.read_bytes()).hexdigest()


def test_two_distinct_runs_needed_and_duplicate_attempt_cannot_create_second_vote(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_RUN_ID", "one")
    run(tmp_path, [bundle()], now=NOW, shadow=True, run_id="one", memory_writer=lambda event: True)
    with pytest.raises(ValueError, match="duplicate"):
        run(tmp_path, [bundle()], now=NOW, shadow=True, run_id="one", memory_writer=lambda event: True)
    assert ConflictLedger(tmp_path).records() == {}
    monkeypatch.setenv("TRADEAI_RUN_ID", "two")
    run(tmp_path, [bundle()], now=NOW + timedelta(minutes=15), shadow=True, run_id="two", memory_writer=lambda event: True)
    assert len(ConflictLedger(tmp_path).records()) == 1


def test_agreement_poll_resets_hysteresis(tmp_path, monkeypatch):
    for run_id, extra in [("one", "ADD"), ("two", "WATCH"), ("three", "ADD")]:
        monkeypatch.setenv("TRADEAI_RUN_ID", run_id)
        run(tmp_path, [bundle(extra=extra)], now=NOW, shadow=True, run_id=run_id, memory_writer=lambda event: True)
    assert not ConflictLedger(tmp_path).records()


def test_fixture_invalid_timestamp_is_not_converted_to_current_evidence(tmp_path):
    path = tmp_path / "input.json"
    path.write_text(json.dumps({"subjects": [{"subject": {"kind": "security", "id": "guid", "label": "SYM",
        "context": {"held": False}}, "canonical": {"source": "CIO", "value": "ADD", "as_of": "invalid"}}]}))
    result = run(tmp_path, fixture_inputs(path), now=NOW)
    assert any(f["kind"] == "DATA_ERROR" for f in result["findings"])
