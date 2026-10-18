"""Retirement proof is observation, never scheduler mutation. Every fixture is hermetic."""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from scripts import nightly_cutover_controller as CTL
from scripts.lib import nightly_cutover as NC
from scripts.lib import n8n_output_verdict as OV
from tests.test_nightly_cutover_controller_20261016 import mk_world, run


def test_future_output_is_not_qualifying_cutover_proof():
    world = mk_world()
    receipt = run("alpha-lane", finished=world.now + timedelta(minutes=1))
    assert NC.qualify_run(world, "alpha-lane", receipt) == "proof_from_future"


def test_other_lane_output_is_not_qualifying_cutover_proof():
    world = mk_world()
    receipt = run("beta-lane")
    assert NC.qualify_run(world, "alpha-lane", receipt) == "proof_lane_mismatch"


START = datetime(2026, 10, 18, 23, tzinfo=timezone.utc)
NOW = datetime(2026, 10, 20, 23, 30, tzinfo=timezone.utc)
LANE, WORKFLOW = "alpha-lane", "tradeai-dispatcher"


def facts(*, now=NOW, start=START, cron="10 6 * * *", instants=None, calendar="all"):
    world = mk_world()
    world.now = now
    row = world.registry[LANE]
    row["scheduler"].update(kind="n8n", stage="cutover", cadence=cron)
    row["dispatch"]["cron"] = [cron]
    row["dispatch"]["tz"] = "America/New_York"
    world.registry_root_rows = copy.deepcopy(world.registry)
    world.contracts[LANE]["stage"] = "cutover"
    world.allowlist[LANE]["output_receipt"] = "v2"
    world.contracts[LANE]["expected_output"] = {
        "schema": "N8nExpectedOutput@v1", "rule": "min_produced", "unit": "items", "min_produced": 1,
        "produced_field": "produced_count", "fatal_skip_reasons": ["no_runner", "lock_busy"],
        "evidence": [{"kind": "receipt_field", "ref": "produced_count"}]}
    world.workflow_git = world.workflow_live = {WORKFLOW: "1" * 64}
    world.owners = {LANE: "n8n"}
    world.owner_epochs = {LANE: 5}
    world.config["downstream_evidence"] = {LANE: {"kind": "receipt_field", "path": "consumed_by"}}
    before = "10 6 * * * $PY scripts/alpha.py"
    after = "# RETIRED 2026-10-18 n8n-cutover alpha-lane " + before
    world.crontab = "SHELL=/bin/bash\nCRON_TZ=America/New_York\n# unrelated operator edit\n" + after + "\n"
    instants = instants if instants is not None else [datetime(2026, 10, d, 10, 10, tzinfo=timezone.utc) for d in (19, 20)]
    world.runs = {LANE: []}
    for at in instants:
        slot = at.astimezone(NC.ET).strftime("%Y%m%dT%H%M")
        receipt = run(LANE, rid=f"d:{LANE}:live:{slot}", finished=at + timedelta(seconds=2))
        receipt["requested_at"] = (at + timedelta(seconds=1)).isoformat()
        receipt["receipt"]["consumed_by"] = "consumer:input-watermark-" + slot
        receipt["receipt"]["output_verdict"].update(contract_id=LANE, produced_count=1)
        world.runs[LANE].append(receipt)
    record = {"schema": "CutoverReceipt@v1", "lane_id": LANE, "action": "cutover", "applied": True,
              "problems": [], "line_before": before, "line_after": after,
              "scheduler_before": {"kind": "cron", "expression": cron},
              "retirement": {"schema": NC.RETIREMENT_SCHEMA, "lane_id": LANE,
                             "campaign_id": "n8n-maturity-20261018", "state": "soaking",
                             "legacy_source": "user-crontab:exact-alpha-line", "legacy_before_image_ref": "before.json",
                             "legacy_before_image_sha256": "2" * 64, "rollback_ref": "tested-rollback.json",
                             "commented_at": start.isoformat(), "soak_started_at": start.isoformat(),
                             "minimum_continuous_hours": 48, "minimum_natural_cycles": 2,
                             "stronger_policy_requirements": [], "deletion_execution_enabled": False,
                             "schedule": {"cron": [cron], "tz": "America/New_York", "calendar": calendar},
                             **NC.retirement_identity(world, LANE, WORKFLOW)}}
    coverage = {"schema": NC.RETIREMENT_COVERAGE_SCHEMA, "lane_id": LANE,
                "campaign_id": "n8n-maturity-20261018", "issued_at": now.isoformat(),
                "identity_digest": NC.retirement_identity_digest(NC.retirement_identity(world, LANE, WORKFLOW)),
                "from": start.isoformat(), "through": now.isoformat(), "complete": True, "continuous": True,
                "covered_natural_slots": [r["run_id"].split(":")[3] for r in world.runs[LANE]],
                "source_refs": ["heartbeat-history:exact-interval", "ledger-query:full-window"],
                "provenance": {"producer": "host:n8n-evidence-collector", "artifact_ref": "source-report.json",
                               "artifact_sha256": "3" * 64, "served_sha": world.current_sha},
                "findings": {key: [] for key in NC.RETIREMENT_FINDINGS}, "requirements": {}}
    coverage["freeze_digest"] = NC.retirement_freeze_digest(record)
    return world, record, coverage


def observe(world, record, coverage, previous=None):
    return NC.evaluate_retirement(world, record, coverage, previous=previous)["retirement"]


def refreeze(world, record, coverage):
    identity = NC.retirement_identity(world, LANE, WORKFLOW)
    record["retirement"].update(identity)
    coverage.update(identity_digest=NC.retirement_identity_digest(identity),
                    freeze_digest=NC.retirement_freeze_digest(record))


def test_48_continuous_hours_and_two_natural_consumed_cycles_enable_only_a_flag():
    world, record, coverage = facts()
    original = copy.deepcopy((record, coverage, world.crontab))
    result = observe(world, record, coverage)
    assert result["state"] == "deletion_eligible"
    assert result["natural_cycles"] == result["expected_slots"] == 2
    assert result["deletion_eligible"] is True and result["deletion_execution_enabled"] is False
    assert result["deletion_eligible_at"] == NOW.isoformat()
    assert (record, coverage, world.crontab) == original


def test_two_cycles_before_48_hours_remain_soaking():
    world, record, coverage = facts(start=START + timedelta(hours=1))
    result = observe(world, record, coverage)
    assert result["state"] == "soaking" and result["natural_cycles"] == 2
    assert result["blocking_reasons"] == ["minimum_continuous_hours_pending"]


def test_weekly_lane_cannot_qualify_in_two_days_and_later_needs_two_real_cycles():
    world, record, coverage = facts(cron="0 6 * * 0", instants=[])
    result = observe(world, record, coverage)
    assert result["state"] == "soaking" and result["natural_cycles"] == 0
    assert result["deletion_not_before"] == "2026-11-01T11:10:00+00:00"
    later = datetime(2026, 11, 1, 22, tzinfo=timezone.utc)
    world, record, coverage = facts(now=later, cron="0 6 * * 0", instants=[
        datetime(2026, 10, 25, 10, tzinfo=timezone.utc), datetime(2026, 11, 1, 11, tzinfo=timezone.utc)])
    result = observe(world, record, coverage)
    assert result["state"] == "deletion_eligible" and result["natural_cycles"] == 2


@pytest.mark.parametrize("name", sorted(NC.RETIREMENT_FINDINGS))
def test_any_interruption_holds_and_clears_elapsed_observation(name):
    world, record, coverage = facts()
    coverage["findings"][name] = ["event:incident-or-gap"]
    result = observe(world, record, coverage)
    assert result["state"] == "held" and result["soak_started_at"] is None
    assert "coverage_" + name in result["blocking_reasons"]
    assert result["deletion_eligible"] is False


def test_recovery_from_a_hold_restarts_continuous_time():
    world, record, coverage = facts()
    failed = copy.deepcopy(coverage)
    failed["findings"]["paused_intervals"] = ["pause:one-second"]
    previous = NC.evaluate_retirement(world, record, failed)
    world.now += timedelta(minutes=1)
    coverage.update(through=world.now.isoformat(), issued_at=world.now.isoformat(), covered_natural_slots=[])
    result = observe(world, record, coverage, previous)
    assert result["state"] == "soaking" and result["natural_cycles"] == 0
    assert result["soak_started_at"] == NOW.isoformat()
    assert result["reset_reasons"] == ["previous_hold_or_identity_change"]


@pytest.mark.parametrize("key,value", [("served_sha", "f" * 40), ("owner_epoch", 6),
                                       ("replacement_graph_digest", "4" * 64), ("config_contract_digest", "5" * 64)])
def test_changed_frozen_identity_requires_review_before_observation(key, value):
    world, record, coverage = facts()
    record["retirement"][key] = value
    result = observe(world, record, coverage)
    assert result["state"] == "held" and result["blocking_reasons"] == ["frozen_identity_changed:review_new_freeze_required"]


def test_new_reviewed_owner_epoch_resets_previous_eligibility():
    world, record, coverage = facts()
    previous = NC.evaluate_retirement(world, record, coverage)
    world.owner_epochs[LANE] = 6
    identity = NC.retirement_identity(world, LANE, WORKFLOW)
    record["retirement"].update(identity)
    coverage.update(identity_digest=NC.retirement_identity_digest(identity), covered_natural_slots=[],
                    freeze_digest=NC.retirement_freeze_digest(record))
    result = observe(world, record, coverage, previous)
    assert result["state"] == "soaking" and result["soak_started_at"] == NOW.isoformat()
    assert result["deletion_eligible"] is False


@pytest.mark.parametrize("mutation,expected", [
    (lambda w, r, c: c.update(continuous=False), "coverage_incomplete"),
    (lambda w, r, c: c.update(complete=False), "coverage_incomplete"),
    (lambda w, r, c: c.update(covered_natural_slots=["20261019T0610"]), "coverage_natural_slots_not_complete"),
    (lambda w, r, c: c.update(source_refs=[]), "coverage_source_refs_missing"),
    (lambda w, r, c: c.update(issued_at=(NOW + timedelta(seconds=1)).isoformat()), "coverage_issue_time_invalid_or_stale"),
    (lambda w, r, c: c.update(through=(NOW - timedelta(minutes=16)).isoformat()), "coverage_stale"),
    (lambda w, r, c: c.update(attested=True), "coverage_missing_or_unsupported"),
    (lambda w, r, c: c["findings"].pop("ambiguous_effects"), "coverage_findings_unknown"),
    (lambda w, r, c: w.ambiguous_claims.update({LANE: [("effect", "UNKNOWN")]}), "ambiguous_effect_claims"),
    (lambda w, r, c: w.in_flight.update({LANE: [{"state": "RUNNING"}]}), "in_flight_work"),
    (lambda w, r, c: w.owners.update({LANE: "cron"}), "owner_or_epoch_unavailable"),
    (lambda w, r, c: setattr(w, "crontab", w.crontab + r["line_before"] + "\n"), "legacy_comment_missing_or_original_live"),
    (lambda w, r, c: setattr(w, "crontab", w.crontab.replace(r["line_after"], "# operator changed legacy line")), "legacy_comment_missing_or_original_live"),
])
def test_unknown_stale_or_conflicting_evidence_holds(mutation, expected):
    world, record, coverage = facts()
    mutation(world, record, coverage)
    result = observe(world, record, coverage)
    assert result["state"] == "held" and expected in result["blocking_reasons"]


@pytest.mark.parametrize("receipt_change", [
    {"mode": "dry_run"}, {"state": "RUN_SKIPPED_LOCK"}, {"exit_code": 1},
    {"receipt": {"stage_clamp": {"effective_mode": "dry_run"}}},
])
def test_unqualified_output_cannot_cover_a_natural_slot(receipt_change):
    world, record, coverage = facts()
    if "receipt" in receipt_change:
        world.runs[LANE][0]["receipt"].update(receipt_change["receipt"])
    else:
        world.runs[LANE][0].update(receipt_change)
    result = observe(world, record, coverage)
    assert result["state"] == "held"
    assert any(x.startswith("missed_or_unproven_natural_slots") for x in result["blocking_reasons"])


def test_no_manual_or_dry_run_can_inflate_natural_cycles():
    world, record, coverage = facts()
    world.runs[LANE][0]["run_id"] = "nc:alpha-lane:forced"
    result = observe(world, record, coverage)
    assert result["state"] == "held" and result["natural_cycles"] == 1


def test_output_without_explicit_downstream_consumption_does_not_qualify():
    world, record, coverage = facts()
    world.runs[LANE][0]["receipt"].pop("consumed_by")
    result = observe(world, record, coverage)
    assert result["state"] == "held" and "downstream_missing:receipt.consumed_by" in result["blocking_reasons"]


def test_any_existing_policy_hold_wins_over_long_observation():
    world, record, coverage = facts()
    world.policy["holds"][LANE] = "operator_hold:separate-proof-required"
    refreeze(world, record, coverage)
    result = observe(world, record, coverage)
    assert result["state"] == "held" and any(x.startswith("operator_hold:") for x in result["blocking_reasons"])


def test_p1_full_session_requirement_cannot_be_supplied_as_a_boolean():
    start = datetime(2026, 10, 23, 21, tzinfo=timezone.utc)  # Friday after close
    now = start + timedelta(hours=49)                     # Sunday, no complete session
    world, record, coverage = facts(start=start, now=now, instants=[
        datetime(2026, 10, 24, 10, 10, tzinfo=timezone.utc), datetime(2026, 10, 25, 10, 10, tzinfo=timezone.utc)])
    world.policy["p1_last"] = {LANE}
    refreeze(world, record, coverage)
    result = observe(world, record, coverage)
    assert result["state"] == "soaking" and result["coverage"]["completed_nyse_sessions"] == 0
    assert "stronger_nyse_session_requirement_pending" in result["blocking_reasons"]


def test_reviewed_extra_policy_requirements_need_evidence():
    world, record, coverage = facts()
    record["retirement"]["stronger_policy_requirements"] = ["special-family-hold"]
    coverage["freeze_digest"] = NC.retirement_freeze_digest(record)
    assert observe(world, record, coverage)["state"] == "held"
    coverage["requirements"]["special-family-hold"] = {"satisfied": True, "evidence_refs": ["reviewed-proof:1"]}
    assert observe(world, record, coverage)["state"] == "deletion_eligible"


def test_dst_fold_and_holiday_slots_follow_existing_dispatch_calendar():
    start = datetime(2026, 11, 1, 4, tzinfo=timezone.utc)
    end = datetime(2026, 11, 1, 8, tzinfo=timezone.utc)
    schedule = {"cron": ["30 1 * * *"], "tz": "America/New_York", "calendar": "all"}
    assert NC._retirement_slots(schedule, start, end) == {"20261101T0130": datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)}
    schedule = {"cron": ["10 6 * * 1-5"], "tz": "America/New_York", "calendar": "nyse"}
    start, end = datetime(2026, 11, 25, 22, tzinfo=timezone.utc), datetime(2026, 11, 27, 22, tzinfo=timezone.utc)
    assert set(NC._retirement_slots(schedule, start, end)) == {"20261127T0610"}  # Thanksgiving excluded


def test_old_receipts_and_unsupported_versions_remain_readable_but_ineligible():
    world, record, coverage = facts()
    record.pop("retirement")
    result = NC.evaluate_retirement(world, record, coverage)
    assert result["retirement"]["state"] == "held" and result["line_before"] == record["line_before"]
    world, record, coverage = facts()
    record["schema"] = "CutoverReceipt@v2"
    assert observe(world, record, coverage)["blocking_reasons"] == ["unsupported_cutover_receipt_version"]


def cli_inputs(tmp_path):
    world, record, coverage = facts()
    source = tmp_path / "source-report.json"
    source.write_text('{"schema":"HostEvidenceSnapshot@v1","coverage":"full-history"}')
    before = tmp_path / "before.txt"
    before.write_text("SHELL=/bin/bash\n" + record["line_before"] + "\n")
    record["retirement"]["legacy_before_image_ref"] = before.name
    record["retirement"]["legacy_before_image_sha256"] = hashlib.sha256(before.read_bytes()).hexdigest()
    coverage["freeze_digest"] = NC.retirement_freeze_digest(record)
    coverage["provenance"]["artifact_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    receipt, cov = tmp_path / "receipt.json", tmp_path / "coverage.json"
    receipt.write_text(json.dumps(record))
    cov.write_text(json.dumps(coverage))
    config = tmp_path / "config.json"
    config.write_text(json.dumps(NC.DEFAULT_CONFIG))
    args = CTL.parser().parse_args(["retirement", "--receipt", str(receipt), "--coverage", str(cov),
                                   "--coverage-sha256", hashlib.sha256(cov.read_bytes()).hexdigest(),
                                   "--evidence-root", str(tmp_path), "--config", str(config),
                                   "--receipt-dir", str(tmp_path / "receipts"), "--out", str(tmp_path / "output.json")])
    return world, args


def test_cli_uses_host_snapshot_writes_only_new_report_and_preserves_evidence(tmp_path, monkeypatch):
    world, args = cli_inputs(tmp_path)
    originals = {p: p.read_bytes() for p in tmp_path.glob("*.json")}
    calls = []

    def build(a, config, **kwargs):
        calls.append(kwargs)
        return world, tmp_path

    monkeypatch.setattr(CTL, "build_world", build)
    monkeypatch.setattr(CTL, "run", lambda *a, **k: pytest.fail("retirement reached mutation controller"))
    code, report = CTL.retirement_report(args)
    assert code == 0 and report["retirement"]["deletion_execution_enabled"] is False
    assert calls[0]["observed_lanes"] == [LANE] and calls[0]["observation_since"] == START
    assert all(p.read_bytes() == data for p, data in originals.items())
    assert json.loads((tmp_path / "output.json").read_text()) == report


def test_cli_rejects_duplicate_fields_digest_mismatch_and_evidence_overwrite(tmp_path, monkeypatch):
    world, args = cli_inputs(tmp_path)
    monkeypatch.setattr(CTL, "build_world", lambda *a, **k: (world, tmp_path))
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"one","schema":"two"}')
    with pytest.raises(ValueError, match="duplicate_json_field"):
        CTL._retirement_json(duplicate)
    args.coverage_sha256 = "f" * 64
    code, report = CTL.retirement_report(args)
    assert code == 2 and "coverage_artifact_digest_mismatch" in report["retirement"]["blocking_reasons"][0]
    args.out = args.receipt
    with pytest.raises(ValueError, match="cannot_overwrite"):
        CTL.retirement_report(args)


def test_cli_production_actions_and_projection_overrides_are_refused():
    assert CTL.main(["retirement", "--apply"]) == 1
    assert CTL.main(["retirement", "--served-root", "/tmp/pretend-host"]) == 1


def test_freeze_requirements_change_cannot_reuse_prior_coverage():
    world, record, coverage = facts()
    record["retirement"]["minimum_continuous_hours"] = 72
    result = observe(world, record, coverage)
    assert result["state"] == "held" and "coverage_freeze_mismatch" in result["blocking_reasons"]


def test_stronger_session_counts_are_computed_from_the_existing_calendar():
    world, record, coverage = facts()
    record["retirement"]["stronger_policy_requirements"] = ["completed_nyse_sessions:3"]
    coverage["freeze_digest"] = NC.retirement_freeze_digest(record)
    result = observe(world, record, coverage)
    assert result["state"] == "soaking" and result["coverage"]["required_nyse_sessions"] == 3


def test_relevant_downstream_config_change_resets_the_frozen_identity():
    world, record, coverage = facts()
    world.config["downstream_evidence"][LANE]["path"] = "new_consumer"
    result = observe(world, record, coverage)
    assert result["state"] == "held" and result["blocking_reasons"] == ["frozen_identity_changed:review_new_freeze_required"]


def test_mtime_alone_cannot_prove_consumption_of_each_historical_output():
    world, record, coverage = facts()
    world.config["downstream_evidence"][LANE] = {"kind": "file_mtime_after", "path": "consumer.json"}
    world.downstream_mtimes = {"consumer.json": NOW.timestamp()}
    refreeze(world, record, coverage)
    assert "downstream_consumption_not_attempt_bound" in observe(world, record, coverage)["blocking_reasons"]


@pytest.mark.parametrize("skipped,empty_reason,expected", [({}, "no_ready_work", "deletion_eligible"),
                                                           ({"no_runner": 1}, "no_ready_work", "held"),
                                                           ({}, "unknown_empty", "held")])
def test_empty_work_reuses_the_real_versioned_output_validator(skipped, empty_reason, expected):
    world, record, coverage = facts()
    rule = {"schema": "N8nExpectedOutput@v1", "rule": "empty_allowed", "unit": "work_items", "min_produced": 1,
            "produced_field": "produced_count", "empty_allowed_reasons": ["no_ready_work"],
            "fatal_skip_reasons": ["no_runner", "lock_busy"], "evidence": [{"kind": "receipt_field", "ref": "produced_count"}]}
    world.contracts[LANE]["expected_output"] = rule
    refreeze(world, record, coverage)
    for receipt in world.runs[LANE]:
        doc = {"schema": "LaneRunReceipt@v2", "run_id": receipt["run_id"], "lane_id": LANE, "status": "ok",
               "produced_count": 0, "empty_reason": empty_reason, "skipped_reasons": skipped}
        verdict = OV.evaluate(rule, doc, run_id=receipt["run_id"], lane_id=LANE, mode="live")
        receipt["receipt"]["output_verdict"] = verdict
    assert observe(world, record, coverage)["state"] == expected


def test_fencing_epochs_are_read_only_and_never_migrate_an_old_ledger(tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    with sqlite3.connect(ledger) as conn:
        conn.execute("CREATE TABLE effect_owners (process TEXT, owner TEXT, epoch INTEGER)")
        conn.execute("INSERT INTO effect_owners VALUES ('alpha-lane', 'n8n', 17)")
    before = ledger.read_bytes()
    assert NC.read_owner_epochs(ledger) == {LANE: 17}
    assert ledger.read_bytes() == before
    with pytest.raises(NC.CohortStop, match="owner_epochs_unreadable"):
        NC.read_owner_epochs(tmp_path / "missing.sqlite")
    assert not (tmp_path / "missing.sqlite").exists()


def test_missing_or_malformed_retirement_freeze_fails_closed():
    world, record, coverage = facts()
    record["retirement"] = None
    result = NC.evaluate_retirement(world, record, coverage)
    assert result["retirement"]["state"] == "held"
    world, record, coverage = facts()
    record["lines"] = "not-before-images"
    coverage["freeze_digest"] = NC.retirement_freeze_digest(record)
    assert "legacy_before_images_missing" in observe(world, record, coverage)["blocking_reasons"]


def test_provenance_path_escape_and_source_failure_are_held(tmp_path, monkeypatch):
    world, args = cli_inputs(tmp_path)
    monkeypatch.setattr(CTL, "build_world", lambda *a, **k: (world, tmp_path))
    doc = json.loads((tmp_path / "coverage.json").read_text())
    doc["provenance"]["artifact_ref"] = "../outside-evidence.json"
    outside = tmp_path.parent / "outside-evidence.json"
    outside.write_text("{}")
    (tmp_path / "coverage.json").write_text(json.dumps(doc))
    args.coverage_sha256 = hashlib.sha256((tmp_path / "coverage.json").read_bytes()).hexdigest()
    code, report = CTL.retirement_report(args)
    assert code == 2 and "outside_evidence_root" in report["retirement"]["blocking_reasons"][0]


def test_unavailable_host_state_produces_an_auditable_hold(tmp_path, monkeypatch):
    world, args = cli_inputs(tmp_path)

    def unavailable(*a, **kw):
        raise NC.CohortStop("ledger_unreadable")

    monkeypatch.setattr(CTL, "build_world", unavailable)
    code, report = CTL.retirement_report(args)
    assert code == 2 and report["retirement"]["blocking_reasons"] == ["observation_unavailable:ledger_unreadable"]
    assert report["retirement"]["deletion_execution_enabled"] is False


def test_declared_but_disabled_runtime_output_enforcement_is_ineligible():
    world, record, coverage = facts()
    world.allowlist[LANE].pop("output_receipt")
    refreeze(world, record, coverage)
    assert "runtime_output_enforcement_not_enabled" in observe(world, record, coverage)["blocking_reasons"]


@pytest.mark.parametrize("effect", [{}, {"owner": "n8n", "epoch": 4, "final_state": "DONE"},
                                    {"owner": "n8n", "epoch": 5, "final_state": "UNKNOWN"},
                                    {"owner": "n8n", "epoch": 5, "final_state": "DONE", "fenced_late": True}])
def test_effectful_lanes_need_attempt_commit_evidence_in_current_epoch(effect):
    world, record, coverage = facts()
    world.effect_lanes = {LANE: {"process": LANE}}
    for row in world.runs[LANE]:
        row["receipt"]["effect"] = effect
    refreeze(world, record, coverage)
    assert "natural_effect_commit_unproven" in observe(world, record, coverage)["blocking_reasons"]


@pytest.mark.parametrize("field,value", [("output_verdict", ["produced"]), ("stage_clamp", "live"),
                                         ("run_id", "other-attempt")])
def test_malformed_or_mismatched_attempt_evidence_is_a_hold(field, value):
    world, record, coverage = facts()
    world.runs[LANE][0]["receipt"][field] = value
    result = observe(world, record, coverage)
    assert result["state"] == "held" and result["deletion_execution_enabled"] is False


def test_new_receipt_extension_is_compatible_with_existing_named_field_reader(tmp_path):
    from scripts.n8n_cutover_checklist import CUTOVER_DIR, cutover_receipts

    world, record, coverage = facts()
    extended = NC.evaluate_retirement(world, record, coverage)
    destination = tmp_path / CUTOVER_DIR
    destination.mkdir(parents=True)
    (destination / "immutable-extended-receipt.json").write_text(json.dumps(extended))
    rows = cutover_receipts(tmp_path, LANE)
    assert len(rows) == 1 and rows[0]["action"] == "cutover" and rows[0]["applied"] is True
    assert rows[0]["line_before"] == record["line_before"]


def test_snapshot_reads_retired_lane_and_requested_full_history(tmp_path):
    from tests.test_nightly_cutover_controller_20261016 import _setup, args, reader

    served, ledger, text = _setup(tmp_path)
    for root in (served, tmp_path / "regroot"):
        path = root / "config/lane_registry.json"
        doc = json.loads(path.read_text())
        doc["lanes"][0]["scheduler"].update(kind="n8n", stage="cutover")
        path.write_text(json.dumps(doc))
    with sqlite3.connect(ledger) as conn:
        conn.execute("CREATE TABLE effect_owners (process TEXT, owner TEXT, epoch INTEGER)")
        conn.execute("INSERT INTO effect_owners VALUES ('alpha-lane', 'n8n', 17)")
    path = tmp_path / "crontab.txt"
    path.write_text(text)
    original = ledger.read_bytes()
    world, _ = CTL.build_world(args(tmp_path, served, ledger, path), NC.DEFAULT_CONFIG, now=NOW,
                               workflow_reader=reader, observed_lanes=[LANE],
                               observation_since=NOW - timedelta(days=30))
    assert len(world.runs[LANE]) == 1 and world.owner_epochs[LANE] == 17
    assert ledger.read_bytes() == original
