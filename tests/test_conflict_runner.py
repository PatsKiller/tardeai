from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from scripts import n8n_run_executor as ex
from scripts import conflict_resolver as resolver
from scripts.conflict_resolver import fixture_inputs, run
from scripts.lib import n8n_output_verdict as ov
from scripts.lib.conflicts.adapters import security_inputs
from scripts.lib.conflicts.engine import Input
from scripts.lib.conflicts.ledger import ConflictLedger

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 23, 19, tzinfo=timezone.utc)
SHA = "a" * 40


def _live_rule():
    rules = ex.parse_expected_outputs((REPO / "config/n8n_health_contracts.json").read_bytes())
    return rules["conflict-resolver"]


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


def test_zero_bundle_shadow_run_grades_produced_against_the_live_contract(tmp_path, monkeypatch):
    """LQ-20261107-134: produced/attempted count the report written, not the bundles evaluated.

    A slot where the watch universe and the re-entry desk are both empty still writes its one comparison report.
    The receipt used to say produced 1 / attempted 0 (``len(bundles)``), which the live contract's verdict rejects
    as ``counts_inconsistent`` — RUN_FAILED output_unverifiable, and three such slots open the breaker.
    """
    run_id = "shadow-empty-bundles"
    monkeypatch.setenv("TRADEAI_RUN_ID", run_id)
    monkeypatch.setenv("TRADEAI_RUN_ATTEMPT", "1")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")
    monkeypatch.setenv("TRADEAI_CODE_SHA", SHA)
    started = datetime.now(timezone.utc) - timedelta(seconds=1)
    # the receipt's own started_at/ok_at must sit inside the executor's attempt window, so this one run is "now"
    result = run(tmp_path, [], now=started, shadow=True, run_id=run_id, memory_writer=lambda event: True)
    finished = datetime.now(timezone.utc) + timedelta(seconds=1)
    report = tmp_path / "data/conflicts/reports" / (hashlib.sha256(run_id.encode()).hexdigest() + ".json")
    assert report.exists(), "a zero-bundle run still writes its one comparison report"
    assert result["findings_count"] == 0 and result["comparison"] == {"before": 0, "after": 0}
    last = json.loads((tmp_path / "data/runtime/conflict-resolver_last.json").read_text())
    assert (last["produced_count"], last["attempted_count"]) == (1, 1)
    assert last["summary"]["bundles_evaluated"] == 0
    attempt = json.loads((tmp_path / "data/runtime/lane_attempts/conflict-resolver" / f"{run_id}.json").read_text())
    verdict = ov.evaluate(_live_rule(), attempt, run_id=run_id, lane_id="conflict-resolver", mode="live", attempt=1,
                          started_at=started.isoformat(), finished_at=finished.isoformat(), code_sha=SHA)
    assert verdict["verdict"] == "produced", verdict


def test_a_failed_shadow_run_still_reads_as_a_typed_failure_not_green(tmp_path, monkeypatch):
    """The counter fix must not turn a real failure green: exit 2 writes 0/0 and stays RUN_FAILED."""
    run_id = "shadow-bad-input"
    monkeypatch.setenv("TRADEAI_RUN_ID", run_id)
    monkeypatch.setenv("TRADEAI_RUN_ATTEMPT", "1")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")
    monkeypatch.setenv("TRADEAI_CODE_SHA", SHA)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert resolver.main(["--shadow", "--state-root", str(tmp_path), "--input-file", str(bad)]) == 2
    last = json.loads((tmp_path / "data/runtime/conflict-resolver_last.json").read_text())
    assert (last["status"], last["produced_count"], last["attempted_count"]) == ("failed", 0, 0)
    assert last["empty_reason"] == "run_failed"
    attempt = json.loads((tmp_path / "data/runtime/lane_attempts/conflict-resolver" / f"{run_id}.json").read_text())
    verdict = ov.evaluate(_live_rule(), attempt, run_id=run_id, lane_id="conflict-resolver", mode="live", attempt=1,
                          started_at=attempt["started_at"], finished_at=attempt["finished_at"], code_sha=SHA)
    assert (verdict["verdict"], verdict["why"]) == ("empty_violation", "receipt_status_failed"), verdict
