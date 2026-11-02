"""Non-broker conflict receipt engineering: guarded synthetic _run only, never collector/main."""
from __future__ import annotations

import builtins
import copy
import hashlib
import importlib.util
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
END = "2026-11-02T18:00:01Z"
SHA = "a" * 40
RUN = "fixture-conflict-output-attempt"


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def protected_imports_unreachable(monkeypatch):
    original = builtins.__import__
    denied = ("brokers", "schwab", "alpaca", "moomoo", "positions_sync", "schwab_transport",
              "db_adapter", "psycopg", "scripts.brokers", "scripts.active_trader",
              "scripts.positions_sync", "scripts.lib.conflicts.producers", "scripts.lib.cio_truth",
              "scripts.lib.ips_policy", "scripts.lib.data_broker.watch_intelligence",
              "scripts.lib.data_broker.watch_decision", "scripts.lib.data_broker.watch_domains",
              "scripts.lib.portfolio_positions")
    def guarded(name, *args, **kwargs):
        fromlist = args[2] if len(args) > 2 else kwargs.get("fromlist")
        candidates = [name, *(name + "." + part for part in (fromlist or ()) if isinstance(part, str))]
        for candidate in candidates:
            parts = candidate.lower().split(".")
            if any(candidate == p or candidate.startswith(p + ".") for p in denied) or any(
                    p.startswith(("broker", "schwab", "alpaca", "moomoo", "positions", "portfolio_positions"))
                    or "transport" in p or p in {"watch_intelligence", "watch_decision", "watch_domains", "cio_truth"}
                    for p in parts):
                raise AssertionError(f"protected import refused: {candidate}")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)


@pytest.fixture
def bench(tmp_path, monkeypatch):
    producer = load("guarded_conflict_output_producer", "scripts/conflict_resolver.py")
    verifier = load("guarded_conflict_output_verifier", "scripts/lib/n8n_output_verdict.py")
    from scripts.lib import lane_last_receipt as receipts
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(END.replace("Z", "+00:00"))
    monkeypatch.setattr(producer, "datetime", Clock)
    monkeypatch.setattr(receipts, "now_iso", lambda: END)
    def forbidden(*args, **kwargs):
        pytest.fail("protected production collector or CLI was reached")
    monkeypatch.setattr(producer, "collect_inputs", forbidden)
    monkeypatch.setattr(producer, "main", forbidden)
    monkeypatch.setenv("TRADEAI_RUN_ID", RUN)
    monkeypatch.setenv("TRADEAI_RUN_ATTEMPT", "1")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")
    monkeypatch.setenv("TRADEAI_CODE_SHA", SHA)
    contracts = json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]
    rule = next(r["expected_output"] for r in contracts if r["id"] == "conflict-resolver")
    assert verifier.validate_expected_output(rule) == []
    return producer, verifier, receipts, rule, tmp_path / "state"


def run(bench, bundles=(), *, shadow=True, run_id=RUN):
    producer, _, _, _, root = bench
    return producer._run(root, bundles, now=START, shadow=shadow, run_id=run_id,
                         memory_writer=lambda event: True, pg_writer=None, pg_enabled=False)


def attempt(bench):
    _, _, receipts, _, root = bench
    return json.loads(receipts.attempt_receipt_path("conflict-resolver", RUN, root).read_text())


def verdict(bench, receipt):
    _, verifier, _, rule, _ = bench
    return verifier.evaluate(rule, receipt, run_id=RUN, lane_id="conflict-resolver", mode="live",
                             attempt=1, code_sha=SHA, started_at=START.isoformat(), finished_at=END)


def bundle(index):
    from scripts.lib.conflicts.adapters import security_inputs
    from scripts.lib.conflicts.engine import Input
    return security_inputs(security_guid=f"fixture-guid-{index}", symbol=f"FIX{index}", held=False,
                           canonical={"stance": "WATCH", "as_of": START.isoformat()},
                           extras=[Input("fixture_desk", "ADD", START)])


@pytest.mark.parametrize("subjects", [0, 2])
def test_completed_report_is_real_fresh_identity_bound_output_even_with_zero_subjects(bench, subjects):
    *_, root = bench
    report = run(bench, [bundle(i) for i in range(subjects)])
    receipt = attempt(bench)
    path = root / "data/conflicts/reports" / (hashlib.sha256(RUN.encode()).hexdigest() + ".json")
    actual = json.loads(path.read_text())
    assert actual["schema"] == "ConflictResolverReceipt@v1" and actual["run_id"] == receipt["run_id"] == RUN
    assert actual["started_at"] == START.isoformat() and actual["finished_at"] == END.replace("Z", "+00:00")
    assert report["notifications"] == actual["notifications"] == 0
    assert receipt["produced_count"] == receipt["attempted_count"] == 1
    assert receipt["summary"]["subjects_evaluated"] == subjects
    assert receipt["summary"]["empty_inputs"] is (subjects == 0)
    assert receipt["summary"]["input_manifest_sha256"] == actual["input_manifest_sha256"]
    evidence = receipt["output_evidence"][0]
    assert root / evidence["ref"] == path and evidence["kind"] == "file_artifact"
    assert evidence["artifact_schema"] == actual["schema"]
    assert evidence["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    if subjects == 0:
        assert actual["input_manifest_sha256"] == hashlib.sha256(b"[]").hexdigest()
        assert actual["findings_count"] == actual["events_written"] == 0
        assert actual["comparison"] == {"before": 0, "after": 0}
    assert verdict(bench, receipt)["verdict"] == "produced"


def test_wrong_explicit_run_id_is_refused_before_any_report_or_ledger_effect(bench):
    *_, root = bench
    with pytest.raises(ValueError, match="identity differs"):
        run(bench, run_id="different-run")
    assert not root.exists()


def test_duplicate_attempt_never_creates_a_second_report_or_vote(bench):
    *_, root = bench
    run(bench)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="duplicate or uncertain"):
        run(bench)
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_dry_run_cannot_reach_receipt_or_file_writers(bench, monkeypatch):
    _, _, receipts, _, root = bench
    original = Path.open
    def no_write(path, mode="r", *args, **kwargs):
        if any(letter in mode for letter in "wax+"):
            pytest.fail("dry-run reached a file writer")
        return original(path, mode, *args, **kwargs)
    def forbidden(*args, **kwargs):
        pytest.fail("dry-run reached shared receipt writer")
    monkeypatch.setattr(Path, "open", no_write)
    monkeypatch.setattr(receipts, "write_lane_receipt", forbidden)
    report = run(bench, shadow=False)
    assert report["phase"] == "dry_run" and not root.exists()


def test_no_real_report_means_no_successful_attempt_even_if_json_dump_returns(bench, monkeypatch):
    _, _, receipts, _, root = bench
    original = Path.open
    def dropped_report(path, mode="r", *args, **kwargs):
        if path.parent.name == "reports" and mode == "x":
            return io.StringIO()
        return original(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", dropped_report)
    with pytest.raises(FileNotFoundError):
        run(bench)
    assert not receipts.attempt_receipt_path("conflict-resolver", RUN, root).exists()
    assert verdict(bench, None)["why"] == "attempt_receipt_missing"


@pytest.mark.parametrize(("field", "value", "why"), [
    ("run_id", "old-run", "receipt_identity_mismatch"),
    ("lane_id", "another-lane", "receipt_identity_mismatch"),
    ("attempt", 2, "receipt_attempt_mismatch"),
    ("code_sha", "b" * 40, "receipt_code_mismatch"),
    ("run_mode", "dry_run", "receipt_mode_mismatch"),
    ("finished_at", "2026-11-02T18:10:00Z", "receipt_outside_attempt_window"),
])
def test_real_verifier_refuses_wrong_or_stale_identity(bench, field, value, why):
    run(bench)
    receipt = copy.deepcopy(attempt(bench))
    receipt[field] = value
    if field == "finished_at":
        receipt["ok_at"] = value
    assert verdict(bench, receipt)["why"] == why


def test_exit_zero_with_no_produced_report_remains_failed(bench):
    run(bench)
    receipt = attempt(bench)
    receipt["produced_count"] = 0
    receipt["empty_reason"] = "no_subjects"
    assert verdict(bench, receipt)["verdict"] == "empty_violation"
    assert verdict(bench, receipt)["why"] == "below_min_produced"
