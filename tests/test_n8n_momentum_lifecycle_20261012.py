"""Offline lifecycle failures and authority boundaries; no provider/business execution."""

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib import n8n_momentum_lifecycle as M

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
NOW = datetime.fromisoformat("2026-10-12T06:20:00-04:00")


def reviewed_fixture_contract(lane):
    path = ROOT / "docs/implementation/n8n-maturity/reconciliation-20261012/MOMENTUM_HEALTH_CONTRACT_PROPOSALS.json"
    contract = copy.deepcopy(
        next(c for c in json.loads(path.read_text())["contracts"] if c["id"] == "momentum-lifecycle-monitor")
    )
    contract.update(id=lane, status="REVIEWED", owner="fixture-owner", ownership_confirmation="OWNER_ACCEPTED")
    contract["review"] = {"reviewed_by": "fixture-owner", "decision_ref": "fixture://operator-decision"}
    contract["review"]["contract_body_sha256"] = M.contract_body_digest(contract)
    return contract


@pytest.fixture
def setup(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (tmp_path / "SOURCE_COMMIT").write_text(SHA)
    candidate = {
        "enabled": False,
        "watch": [{"lane_id": "early-source", "role": "WATCH_ONLY_PROTECTED", "completion_allowance_s": 300}],
        "products": [
            {"id": "latest_scan_package", "max_age_s": 14400},
            {"id": "served_scan_cache", "max_age_s": 14400, "upstream": "latest_scan_package"},
        ],
        "recovery": {
            "armed": False,
            "actions": [
                {
                    "lane_id": "momentum-cache-reconcile",
                    "product": "served_scan_cache",
                    "dependencies": ["latest_scan_package"],
                }
            ],
        },
    }
    registry = {
        "lanes": [
            {"lane_id": "early-source", "state": "ACTIVE", "scheduler": {"expression": "*/5 6-11 * * 1-5"}},
            {
                "lane_id": "momentum-cache-reconcile",
                "state": "ACTIVE",
                "scheduler": {"stage": "cutover"},
                "dispatch": {"class": "report", "retry_policy": "transient-2"},
            },
        ]
    }
    contract = reviewed_fixture_contract("momentum-cache-reconcile")
    allow = {
        "lanes": {"momentum-cache-reconcile": {"live_arg": [], "lock_kind": "flock", "lock": "/fixture/cache.lock"}}
    }
    for name, doc in [
        ("lane_registry", registry),
        ("n8n_health_contracts", {"contracts": [contract]}),
        ("n8n_run_allowlist", allow),
    ]:
        (cfg / f"{name}.json").write_text(json.dumps(doc))
    (cfg / "n8n_retry_policies.json").write_bytes((ROOT / "config/n8n_retry_policies.json").read_bytes())
    admission = M.load_admission(tmp_path)
    return candidate, admission, tmp_path


def product(run="scan-0900", **extra):
    result = {
        "available": True,
        "run_id": run,
        "run_date": "2026-10-12",
        "source_sha": SHA,
        "finished_at": "2026-10-12T06:09:00-04:00",
        "basis": "REAL_BUSINESS_OUTPUT",
        "business_status": "ok",
        "populations": {"scanned_total": 67, "classified_total": 44, "manual_total": 23},
        "population_contract": "scan_partition",
    }
    result.update(extra)
    return result


def evaluate(setup, snapshot, now=NOW):
    c, a, _ = setup
    return M.evaluate(
        c,
        snapshot,
        a,
        now=now,
        trading_day_fn=lambda d: d.weekday() < 5,
        session_fn=lambda d: "regular" if 9 <= d.hour < 16 else "premarket",
    )


def run(slot="20261012T0600", **extra):
    result = {
        "lane_id": "early-source",
        "slot_local": slot,
        "run_id": "natural-1",
        "trigger_kind": "NATURAL_SCHEDULE",
        "state": "RUN_DONE",
        "exit_code": 0,
        "requested_at": "2026-10-12T06:00:01-04:00",
        "started_at": "2026-10-12T06:00:02-04:00",
        "finished_at": "2026-10-12T06:00:30-04:00",
        "receipt": {
            "run_id": "natural-1",
            "lane_id": "early-source",
            "slot_local": slot,
            "source_sha": SHA,
            "exit_code": 0,
        },
    }
    result.update(extra)
    return result


def repair_snapshot():
    return {
        "storage_health": {"status": "PROVEN"},
        "recovery_runs": [
            {
                "lane_id": "momentum-cache-reconcile",
                "slot_key": "d:momentum-cache-reconcile:live:20261012T0600",
                "attempt": 1,
                "state": "RUN_FAILED",
                "exit_code": 75,
                "reason": "executor_lost",
                "requested_at": "2026-10-12T06:00:01-04:00",
                "finished_at": "2026-10-12T06:01:00-04:00",
                "source_sha": SHA,
            }
        ],
    }


def repair_report():
    return {
        "source_sha": SHA,
        "products": {"served_scan_cache": {"status": "UNPROVEN"}, "latest_scan_package": {"status": "PROVEN"}},
    }


def armed(candidate):
    c = copy.deepcopy(candidate)
    c["enabled"] = True
    c["recovery"]["armed"] = True
    return c


def test_six_am_expected_fires_detect_requests_never_created(setup):
    report = evaluate(setup, {"runs": []})
    assert report["lanes"][0]["expected_due"] == 4
    assert report["lanes"][0]["observed_requested"] == 0
    assert "expected_fire_without_request" in report["lanes"][0]["requirements_missing"]
    assert report["scalp_cycle_metrics"] is None
    assert report["natural_cutover_proof"] == "NOT_MEASURED"


def test_absent_run_census_is_not_a_fabricated_zero(setup):
    report = evaluate(setup, {})
    assert report["lanes"][0]["observed_requested"] is None
    assert "not_measured" in report["lanes"][0]["requirements_missing"]


def test_missing_schedule_has_no_invented_expected_fire_denominator(setup):
    _, admission, _ = setup
    admission.registry.pop("early-source")
    lane = evaluate(setup, {"runs": []})["lanes"][0]
    assert lane["expected_due"] is None and lane["observed_requested"] is None
    assert "schedule_not_measured" in lane["requirements_missing"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"trigger_kind": "MANUAL_CANARY"}, "manual_or_unknown_trigger"),
        ({"state": "RUN_SKIPPED_LOCK"}, "lock_skipped"),
        ({"state": "RUN_FAILED", "exit_code": 73, "reason_code": "LOCKFILE_CREATE_ENOSPC"}, "lockfile_create_no_space"),
        ({"receipt": {}}, "receipt_identity_missing"),
        ({"finished_at": None}, "durable_chain_incomplete"),
        (
            {
                "receipt": {
                    "run_id": "natural-1",
                    "lane_id": "early-source",
                    "slot_local": "20261012T0600",
                    "source_sha": "b" * 40,
                    "exit_code": 0,
                }
            },
            "receipt_sha_or_verdict_mismatch",
        ),
    ],
)
def test_incomplete_or_unaccepted_run_never_closes_slot(setup, change, reason):
    report = evaluate(setup, {"runs": [run(**change)]})
    assert report["lanes"][0]["slot_states"]["20261012T0600"] == reason


def test_duplicate_finished_runs_require_business_effect_inspection(setup):
    second = run(run_id="natural-2")
    second["receipt"] = {**second["receipt"], "run_id": "natural-2"}
    report = evaluate(setup, {"runs": [run(), second]})
    assert report["lanes"][0]["slot_states"]["20261012T0600"] == "duplicate_completed_run_effects_not_proven"


def test_business_output_and_served_cache_are_independent(setup):
    report = evaluate(
        setup,
        {
            "runs": [],
            "products": {
                "latest_scan_package": product(),
                "served_scan_cache": product("friday", run_date="2026-10-09", derived_from_run_id="friday"),
            },
        },
    )
    assert report["products"]["latest_scan_package"]["status"] == "PROVEN"
    assert report["products"]["served_scan_cache"]["status"] == "UNPROVEN"
    assert "upstream_run_binding_drift" in report["products"]["served_scan_cache"]["requirements_missing"]


def test_classified_manual_and_overlay_populations_are_not_forced_equal():
    assert M.product_proof(product(), day="2026-10-12", now=NOW, sha=SHA, max_age_s=14400) == []
    overlay = product(population_contract="separate_overlay", populations={"universe_total": 70, "go_total": 1})
    assert M.product_proof(overlay, day="2026-10-12", now=NOW, sha=SHA, max_age_s=14400) == []
    broken = product(populations={"scanned_total": 67, "classified_total": 44, "manual_total": 0})
    assert "population_partition_drift" in M.product_proof(broken, day="2026-10-12", now=NOW, sha=SHA, max_age_s=14400)


def test_health_autoheal_anchor_does_not_prove_business_success():
    p = product(basis="HEALTH_AUTOHEAL", finished_at=NOW.isoformat())
    assert "business_output_not_proven" in M.product_proof(p, day="2026-10-12", now=NOW, sha=SHA, max_age_s=14400)


def test_notification_subject_binding_drift_never_copies_body_symbols_into_incident(setup):
    c, a, root = setup
    c = copy.deepcopy(c)
    c["products"] = [{"id": "notification_lineage", "max_age_s": 14400}]
    p = product(notification_binding={"body_subject": "WFF", "link_subject": "TROW", "footer_subject": "TROW"})
    report = evaluate((c, a, root), {"products": {"notification_lineage": p}})
    assert "notification_source_binding_drift" in report["products"]["notification_lineage"]["requirements_missing"]
    assert "WFF" not in json.dumps(report["incidents"]) and "TROW" not in json.dumps(report["incidents"])


def test_incident_payload_and_key_stay_stable_across_polls(setup):
    one = evaluate(setup, {"runs": []})
    two = evaluate(setup, {"runs": []}, NOW + timedelta(minutes=1))
    assert one["incidents"] == two["incidents"]


def test_before_six_am_and_weekends_have_no_business_deadline(setup):
    before = evaluate(setup, {}, datetime.fromisoformat("2026-10-12T05:59:00-04:00"))
    weekend = evaluate(setup, {}, datetime.fromisoformat("2026-10-11T12:00:00-04:00"))
    assert all(p["status"] == "NOT_APPLICABLE" for p in before["products"].values())
    assert weekend["lanes"][0]["expected_due"] == 0


def test_disabled_candidate_never_arms_recovery(setup):
    c, a, _ = setup
    assert M.plan_recovery(c, repair_report(), a, snapshot=repair_snapshot(), now=NOW) == {
        "intents": [],
        "held": [{"reason": "retry_disarmed"}],
    }


def test_recovery_uses_actual_policy_and_stable_budget_slot_attempt(setup):
    c, a, _ = setup
    one = M.plan_recovery(armed(c), repair_report(), a, snapshot=repair_snapshot(), now=NOW)
    two = M.plan_recovery(armed(c), repair_report(), a, snapshot=repair_snapshot(), now=NOW + timedelta(seconds=1))
    assert one == two
    assert len(one["intents"]) == 1 and one["intents"][0]["attempt"] == 2
    assert one["intents"][0]["operation"] == "coordination/run"


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("state", "RUN_SKIPPED_LOCK", "existing_retry_policy_terminal"),
        ("state", "RUN_REFUSED", "existing_retry_policy_terminal"),
        ("exit_code", 2, "existing_retry_policy_terminal"),
        ("attempt", 3, "retry_budget_exhausted"),
        ("source_sha", "b" * 40, "budget_slot_or_receipt_not_proven"),
    ],
)
def test_recovery_cannot_retry_skips_refusals_exhausted_or_wrong_sha(setup, field, value, reason):
    c, a, _ = setup
    s = repair_snapshot()
    s["recovery_runs"][0][field] = value
    result = M.plan_recovery(armed(c), repair_report(), a, snapshot=s, now=NOW)
    assert result["intents"] == [] and result["held"][0]["reason"] == reason


def test_retry_window_is_original_slot_not_later_attempt_timestamp(setup):
    c, a, _ = setup
    s = repair_snapshot()
    s["recovery_runs"][0].update(requested_at="2026-10-12T06:59:00-04:00", finished_at="2026-10-12T06:59:01-04:00")
    result = M.plan_recovery(armed(c), repair_report(), a, snapshot=s, now=NOW.replace(hour=7, minute=1))
    assert result["held"][0]["reason"] == "retry_backoff_or_window"


def test_missing_durable_attempt_is_held_instead_of_zero_or_manual_retry(setup):
    c, a, _ = setup
    s = repair_snapshot()
    s["recovery_runs"][0]["attempt"] = None
    result = M.plan_recovery(armed(c), repair_report(), a, snapshot=s, now=NOW)
    assert result["intents"] == [] and result["held"][0]["reason"] == "budget_slot_or_receipt_not_proven"


def test_storage_failure_holds_recovery_without_deletion(setup):
    c, a, _ = setup
    s = repair_snapshot()
    s["storage_health"] = {"status": "ENOSPC"}
    result = M.plan_recovery(armed(c), repair_report(), a, snapshot=s, now=NOW)
    assert result["intents"] == [] and result["held"][0]["reason"] == "storage_or_lock_creation_not_proven"


def test_dependencies_and_review_cannot_be_armed_by_candidate_boolean(setup):
    c, a, _ = setup
    c = armed(c)
    c["dependencies_healthy"] = True
    report = repair_report()
    report["products"]["latest_scan_package"]["status"] = "UNPROVEN"
    assert (
        M.plan_recovery(c, report, a, snapshot=repair_snapshot(), now=NOW)["held"][0]["reason"]
        == "dependency_output_not_proven"
    )
    a.contracts["momentum-cache-reconcile"]["review"] = {}
    assert (
        M.plan_recovery(c, repair_report(), a, snapshot=repair_snapshot(), now=NOW)["held"][0]["reason"]
        == "operative_admission_not_proven"
    )


def test_proposal_and_credential_targets_never_recover_even_if_config_arms_them(setup):
    c, a, _ = setup
    c = armed(c)
    for target in ["auto-proposal-general", "proposal-promoter", "sm-render", "cookie-refresh", "trade-ai-scalp-live"]:
        c["recovery"]["actions"][0]["lane_id"] = target
        result = M.plan_recovery(c, repair_report(), a, snapshot=repair_snapshot(), now=NOW)
        assert result["intents"] == [] and result["held"][0]["reason"] == "protected_or_unknown_recovery_lane"


def test_gateway_rejects_caller_supplied_arming_or_authority(setup):
    c, a, _ = setup
    r = M.gateway_view(
        {"armed": True, "reviewed": True},
        candidate=c,
        server_snapshot={},
        admission=a,
        now=NOW,
        trading_day_fn=lambda _: True,
        session_fn=lambda _: "regular",
    )
    assert r == {"state": "REFUSED", "reason": "unexpected_field"}


def test_bitwarden_cookie_recovery_is_an_operator_task_only(setup):
    report = evaluate(setup, {"credential_health": {"secret_name": "FINVIZ_COOKIE", "status": "expired"}})
    assert report["credential_tasks"][0]["source_of_truth"] == "Bitwarden Secrets Manager"
    assert report["credential_tasks"][0]["automatic_cookie_or_secret_action"] is False
    assert report["recovery_intents"] == []


def test_snapshot_cli_is_readonly_and_fixture_root_is_explicit(setup, tmp_path, capsys):
    from scripts.n8n_momentum_lifecycle import main

    c, _, code_root = setup
    snapshot = tmp_path / "observation.json"
    candidate = tmp_path / "candidate.json"
    snapshot.write_text(json.dumps({"runs": []}))
    candidate.write_text(json.dumps(c))
    original = snapshot.read_bytes()
    assert (
        main(
            [
                "--snapshot",
                str(snapshot),
                "--code-root",
                str(code_root),
                "--candidate",
                str(candidate),
                "--now",
                NOW.isoformat(),
                "--exit-code",
            ]
        )
        == 2
    )
    result = json.loads(capsys.readouterr().out)
    assert result["authority"] == "READ_ONLY_ADVISORY"
    assert result["recovery"]["intents"] == [] and snapshot.read_bytes() == original


def test_monitor_evaluation_completion_does_not_stop_scheduling_on_watched_p1(setup, tmp_path, capsys):
    from scripts.n8n_momentum_lifecycle import main

    c, _, root = setup
    snapshot = tmp_path / "snapshot.json"
    candidate = tmp_path / "candidate.json"
    snapshot.write_text('{"runs":[]}')
    candidate.write_text(json.dumps(c))
    assert (
        main(
            [
                "--snapshot",
                str(snapshot),
                "--code-root",
                str(root),
                "--candidate",
                str(candidate),
                "--now",
                NOW.isoformat(),
                "--dry-run",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert any(f["severity"] == "P1" for f in report["incidents"])
    assert report["acceptance"] == "NOT_MEASURED"


def test_candidate_config_is_disabled_and_not_an_operative_review():
    c = json.loads((ROOT / "config/n8n_momentum_lifecycle_candidate.json").read_text())
    assert c["status"] == "DRAFT_FOR_OWNER_REVIEW" and c["review"] is None
    assert c["enabled"] is False and c["recovery"]["armed"] is False
    assert c["credential_recovery"]["automatic"] is False


def test_host_collector_reads_exact_ledger_without_mutating_or_exposing_payload(setup):
    import sqlite3
    from types import SimpleNamespace

    c, _, root = setup
    path = root / M.LEDGER_REL
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE runs (run_id TEXT, lane_id TEXT, state TEXT, mode TEXT, requested_at TEXT, "
        "started_at TEXT, finished_at TEXT, exit_code INTEGER, slot_key TEXT, attempt INTEGER, receipt_json TEXT)"
    )
    receipt = {
        "run_id": "d:early-source:dry_run:20261012T0600",
        "lane_id": "early-source",
        "code_sha": SHA,
        "exit_code": 73,
        "stderr_tail": "flock: cannot open lock file: No space left on device PRIVATE_PAYLOAD",
        "cookie": "NEVER_COPY",
        "prompt": "NEVER_COPY",
        "account": "NEVER_COPY",
    }
    conn.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            receipt["run_id"],
            "early-source",
            "RUN_FAILED",
            "dry_run",
            "2026-10-12T10:00:01+00:00",
            "2026-10-12T10:00:02+00:00",
            "2026-10-12T10:00:03+00:00",
            73,
            "d:early-source:dry_run:20261012T0600",
            1,
            json.dumps(receipt),
        ),
    )
    conn.commit()
    conn.close()
    before = path.read_bytes()
    snapshot = M.collect_server_snapshot(
        root, c, now=NOW, statvfs_fn=lambda _: SimpleNamespace(f_bavail=20, f_frsize=4096, f_favail=0)
    )
    assert snapshot["collection"]["ledger"] == "READ_ONLY_SANITIZED"
    assert snapshot["runs"][0]["reason_code"] == "LOCKFILE_CREATE_ENOSPC"
    assert snapshot["runs"][0]["trigger_kind"] == "NOT_MEASURED"
    assert snapshot["storage_health"]["status"] == "FAILED"
    assert snapshot["runs"][0]["slot_local"] == "20261012T0600"
    assert "NEVER_COPY" not in json.dumps(snapshot) and "PRIVATE_PAYLOAD" not in json.dumps(snapshot)
    assert path.read_bytes() == before


def test_positive_capacity_is_not_an_invented_reviewed_reserve(setup):
    from types import SimpleNamespace

    c, _, root = setup
    snapshot = M.collect_server_snapshot(
        root, c, now=NOW, statvfs_fn=lambda _: SimpleNamespace(f_bavail=1000, f_frsize=4096, f_favail=1000)
    )
    assert snapshot["storage_health"]["status"] == "NOT_MEASURED"
    assert snapshot["runs"] is None and "latest_scan_package" not in snapshot["products"]
    assert snapshot["products"]["shared_signal_projection"]["basis"] == "NOT_MEASURED"
    report = evaluate(setup, snapshot)
    assert report["lanes"][0]["observed_requested"] is None


def test_empty_storage_is_independent_p1_and_no_automatic_deletion(setup):
    report = evaluate(setup, {"storage_health": {"status": "FAILED"}})
    f = next(f for f in report["incidents"] if f["item"] == "momentum-storage:STORAGE_CAPACITY_EXHAUSTED")
    assert f["severity"] == "P1" and f["notification_dedupe_minutes"] == 0
    assert report["recovery_intents"] == []


def test_actual_cache_mapping_preserves_unmeasured_sha_and_business_proof(setup):
    c, a, root = setup
    runtime = root / "data/runtime"
    runtime.mkdir(parents=True)
    cache = {
        "run_id": "2026-10-09::1730",
        "run_date": "2026-10-12",
        "tickers": [],
        "stale": False,
        "setup_run_summary": {"run_id": "2026-10-09::1730", "run_date": "2026-10-09", "scanned_count": 44},
    }
    (runtime / "trade_ai_cache.json").write_text(json.dumps(cache))
    snapshot = M.collect_server_snapshot(root, c, now=NOW)
    served = snapshot["products"]["served_scan_cache"]
    assert served["run_date"] == "2026-10-09" and served["source_sha"] == "UNKNOWN"
    assert served["basis"] == "NOT_MEASURED" and served["business_status"] == "NOT_MEASURED"
    assert served["populations"]["summary_scanned_total"] == 44
    reasons = M.product_proof(served, day="2026-10-12", now=NOW, sha=a.deployed_sha, max_age_s=14400)
    assert "wrong_business_day" in reasons and "output_source_sha_mismatch" in reasons
    assert "business_output_not_proven" in reasons


def test_unaccepted_input_declarations_cannot_promote_business_or_credential_proof(setup):
    c, a, root = setup
    runtime = root / "data/runtime"
    runtime.mkdir(parents=True)
    declared = {
        "products": {spec["id"]: product(accepted_producer="PROVEN") for spec in c["products"]},
        "credential_health": {"secret_name": "FINVIZ_COOKIE", "status": "expired", "cookie": "NEVER_COPY"},
    }
    path = root / M.INPUT_REL
    path.write_text(json.dumps(declared))
    before = path.read_bytes()
    snapshot = M.collect_server_snapshot(root, c, now=NOW, admission=a)
    report = evaluate(setup, snapshot)
    assert snapshot["collection"]["accepted_input_producer"] == "NOT_MEASURED"
    assert snapshot["products"]["latest_scan_package"]["source_sha"] == SHA
    assert snapshot["products"]["latest_scan_package"]["populations"]["scanned_total"] == 67
    for spec in c["products"]:
        row = report["products"][spec["id"]]
        assert row["status"] == "UNPROVEN" and row["accepted_producer"] == "NOT_MEASURED"
        assert set(row["requirements_missing"]) & {"business_output_not_proven", "output_not_measured"}
    assert snapshot["credential_health"]["declared_status"] == "expired"
    assert snapshot["credential_health"]["status"] == "NOT_MEASURED" and report["credential_tasks"] == []
    assert "NEVER_COPY" not in json.dumps(snapshot) and path.read_bytes() == before
    # Explicit isolated evaluator fixtures remain useful; no runtime declaration flag arms them.
    assert (
        evaluate(setup, {"products": {"latest_scan_package": product()}})["products"]["latest_scan_package"]["status"]
        == "PROVEN"
    )


def test_cache_metadata_retains_nested_identity_without_borrowing_newer_timestamp(setup):
    import hashlib

    c, a, root = setup
    runtime = root / "data/runtime"
    runtime.mkdir(parents=True)
    cache = {
        "run_id": "new-cache-wrapper",
        "run_date": "2026-10-12",
        "latest_run_timestamp": NOW.isoformat(),
        "code_sha": SHA,
        "tickers": [],
        "stale": False,
        "setup_run_summary": {
            "contract_version": "SetupRunSummary@v1",
            "run_id": "2026-10-09::1730",
            "run_date": "2026-10-09",
            "scanned_count": 44,
        },
    }
    path = runtime / "trade_ai_cache.json"
    path.write_text(json.dumps(cache))
    raw = path.read_bytes()
    snapshot = M.collect_server_snapshot(root, c, now=NOW, admission=a)
    observed = snapshot["products"]["served_scan_cache"]
    assert observed["run_id"] == "2026-10-09::1730" and observed["finished_at"] is None
    assert observed["source_sha"] == SHA and observed["basis"] == "NOT_MEASURED"
    evidence = observed["source_evidence"]
    assert evidence["provenance"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert evidence["provenance"]["schema"] == "SetupRunSummary@v1"
    assert evidence["field_provenance"]["run_id"]["field"] == "setup_run_summary.run_id"
    assert evidence["field_provenance"]["finished_at"]["field"] == "NOT_MEASURED"
    assert evidence["independent_output_corroboration"] == "NOT_MEASURED"
    assert path.read_bytes() == raw


def test_readonly_cache_observation_overrides_declaration_counts_without_inheriting_acceptance(setup):
    c, a, root = setup
    runtime = root / "data/runtime"
    runtime.mkdir(parents=True)
    (root / M.INPUT_REL).write_text(json.dumps({"products": {"served_scan_cache": product()}}))
    (runtime / "trade_ai_cache.json").write_text(
        json.dumps(
            {
                "run_id": "actual",
                "run_date": "2026-10-12",
                "tickers": [],
                "stale": False,
                "setup_run_summary": {"run_id": "actual", "run_date": "2026-10-12", "scanned_count": 44},
            }
        )
    )
    snapshot = M.collect_server_snapshot(root, c, now=NOW, admission=a)
    observed = snapshot["products"]["served_scan_cache"]
    assert observed["run_id"] == "actual" and observed["source_sha"] == "UNKNOWN"
    assert observed["populations"] == {"candidate_union_total": 0, "summary_scanned_total": 44}
    assert observed["declared_metadata"]["populations"]["scanned_total"] == 67
    assert observed["accepted_producer"] == "NOT_MEASURED"


def test_existing_registry_receipt_metadata_is_sanitized_and_not_output_acceptance(setup):
    import hashlib

    c, a, root = setup
    relative = "data/runtime/early-source_last.json"
    a.registry["early-source"]["output_signal"] = {"path": relative, "kind": "json_key", "key": "ok_at"}
    runtime = root / "data/runtime"
    runtime.mkdir(parents=True)
    path = root / relative
    path.write_text(
        json.dumps(
            {
                "schema": "LaneRunReceipt@v1",
                "lane_id": "early-source",
                "mode": "live",
                "status": "ok",
                "exit": 0,
                "finished_at": NOW.isoformat(),
                "source_sha": SHA,
                "summary": {"run_id": "scan-0900", "cookie": "NEVER_COPY"},
                "prompt": "NEVER_COPY",
                "account": "NEVER_COPY",
            }
        )
    )
    before = path.read_bytes()
    snapshot = M.collect_server_snapshot(root, c, now=NOW, admission=a)
    observed = snapshot["host_receipts"]["early-source"]
    assert observed["fields"]["business_run_id"] == "scan-0900"
    assert observed["field_provenance"]["business_run_id"]["field"] == "summary.run_id"
    assert observed["provenance"]["sha256"] == hashlib.sha256(before).hexdigest()
    assert observed["accepted_output_proof"] == observed["producer_binding"] == "NOT_MEASURED"
    assert "NEVER_COPY" not in json.dumps(snapshot) and path.read_bytes() == before
    assert evaluate(setup, snapshot)["host_receipt_metadata"] == snapshot["host_receipts"]


@pytest.mark.parametrize(
    "relative",
    [
        "logs/early-source.log",
        "data/runtime/raw_cookie.json",
        "data/runtime/../../cookie_last.json",
        "data/secrets/early-source_last.json",
    ],
)
def test_host_receipt_adapter_never_reads_nonreceipt_paths(setup, relative):
    c, a, root = setup
    a.registry["early-source"]["output_signal"] = {"path": relative}
    assert M.collect_server_snapshot(root, c, now=NOW, admission=a)["host_receipts"] == {}


def test_bounded_public_run_summary_skips_healer_and_never_inherits_deployed_sha(setup):
    c, a, root = setup
    reports = root / "reports/2026-10-12"
    real = reports / "0400/run_summary.json"
    real.parent.mkdir(parents=True)
    real.write_text(
        json.dumps(
            {
                "schema": "ScannerRunSummary@v1",
                "date": "2026-10-12",
                "run_label": "0400",
                "generated_at": "2026-10-12T06:09:00-04:00",
                "ticker_count": 21,
            }
        )
    )
    heal = reports / "HEALTH_AUTOHEAL/run_summary.json"
    heal.parent.mkdir()
    heal.write_text(json.dumps({"run_label": "HEALTH_AUTOHEAL", "generated_at": NOW.isoformat(), "ticker_count": 999}))
    snapshot = M.collect_server_snapshot(root, c, now=NOW, admission=a, code_root=root)
    observed = snapshot["products"]["latest_scan_package"]
    assert observed["run_id"] == "2026-10-12::0400" and observed["source_sha"] == "UNKNOWN"
    assert observed["populations"] == {"published_ticker_count": 21}
    assert observed["source_evidence"]["provenance"]["path"] == "reports/2026-10-12/0400/run_summary.json"
    report = evaluate(setup, snapshot)
    assert report["products"]["latest_scan_package"]["status"] == "UNPROVEN"
    assert report["products"]["latest_scan_package"]["source_evidence"] == observed["source_evidence"]


def test_metadata_adapter_rejects_malformed_and_oversized_documents(tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text("{")
    assert M._metadata_document(path, "public/metadata.json")[1]["status"] == "MALFORMED"
    path.write_text(json.dumps({"payload": "x" * 100}))
    document, evidence = M._metadata_document(path, "public/metadata.json", limit=20)
    assert document is None and evidence["status"] == "OVERSIZED" and evidence["sha256"] is None


@pytest.mark.parametrize(
    "filename,field",
    [
        ("scalp_cycle_monitor_last.json", "scalp_cycle_monitor"),
        ("n8n_failure_diagnosis_last.json", "diagnosis"),
    ],
)
def test_host_health_metadata_has_bounded_reads_and_preserves_missing_proof(setup, filename, field):
    candidate, admission, root = setup
    path = root / "data/runtime" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "fixture", "payload": "x" * 131073}))
    snapshot = M.collect_server_snapshot(root, candidate, now=NOW, admission=admission)
    assert snapshot["collection"][field]["status"] == "OVERSIZED"
    if field == "scalp_cycle_monitor":
        assert snapshot["scalp_cycle_monitor"] is None
    else:
        assert snapshot["diagnosis_status"] == {}


def test_diagnosis_projection_uses_actual_producer_counts_and_excludes_raw_actions(setup):
    candidate, admission, root = setup
    path = root / "data/runtime/n8n_failure_diagnosis_last.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "N8nFailureDiagnosis@v1",
                "mode": "apply",
                "ok": True,
                "as_of": NOW.isoformat(),
                "counts": {"eligible": 2, "diagnosed": 1, "model_called": 1, "execute": False, "no_diagnosis": -1},
                "consecutive_blind": 0,
                "actions": [{"text": "RAW_ACTION_NEVER_FORWARD"}],
                "results": [{"model_answer": "RAW_MODEL_NEVER_FORWARD"}],
                "status": "RAW_STATUS_NEVER_FORWARD",
            }
        )
    )
    snapshot = M.collect_server_snapshot(root, candidate, now=NOW, admission=admission)
    assert snapshot["diagnosis_status"] == {
        "schema": "N8nFailureDiagnosis@v1",
        "mode": "apply",
        "ok": True,
        "as_of": NOW.astimezone(timezone.utc).isoformat(),
        "eligible": 2,
        "diagnosed": 1,
        "model_called": 1,
        "consecutive_blind": 0,
    }
    assert "NEVER_FORWARD" not in json.dumps(snapshot)


def test_shared_projection_consumer_generation_and_verdicts_are_preserved():
    p = product(
        population_contract="shared_signal_union",
        projection_hash="hash-1",
        source_verdicts_preserved=True,
        consumer_views={
            surface: {"projection_hash": "hash-1", "run_id": "scan-0900", "run_date": "2026-10-12"}
            for surface in ("active_trader", "trade_ai")
        },
    )
    assert M.product_proof(p, day="2026-10-12", now=NOW, sha=SHA, max_age_s=14400) == []
    p["consumer_views"]["active_trader"]["projection_hash"] = "old"
    assert "shared_projection_consumer_identity_drift" in M.product_proof(
        p, day="2026-10-12", now=NOW, sha=SHA, max_age_s=14400
    )


def test_llm_diagnosis_coverage_uses_existing_exclusion_and_no_model_selection(setup):
    c, a, _ = setup
    c = copy.deepcopy(c)
    c["watch"] = [{"lane_id": "trade-ai-scalp-live"}, {"lane_id": "data-lane"}]
    a.diagnosis_catalogue.update(status="PROPOSED", lanes=[{"lane_id": "data-lane"}])
    projection = M.diagnosis_coverage(c, a)
    assert projection["process_id"] == "n8n_lane_failure_diagnosis"
    assert projection["model_selection_by_n8n"] is False
    assert projection["lanes"][0]["mode"] == "EXCLUDED_ESCALATE_ONLY"
    assert projection["lanes"][1]["mode"] == "CATALOGUE_REVIEW_HELD"


def admitted_monitor(admission):
    lid = "momentum-lifecycle-monitor"
    admission.registry[lid] = {"state": "ACTIVE", "scheduler": {"stage": "canary"}, "dispatch": {"class": "monitor"}}
    admission.contracts[lid] = reviewed_fixture_contract(lid)
    admission.allowlist[lid] = {
        "live_arg": ["--write-monitor"],
        "lock_kind": "flock",
        "lock": "/tmp/tradeai_momentum_lifecycle.lock",
    }


def test_monitor_admission_is_operative_and_content_bound(setup):
    _, a, _ = setup
    assert M.monitor_admitted(a) is False
    admitted_monitor(a)
    assert M.monitor_admitted(a) is True
    a.contracts["momentum-lifecycle-monitor"]["baseline"]["completion_allowance_s"] = 999
    assert M.monitor_admitted(a) is False


def test_unadmitted_canary_never_becomes_a_shadow_readback(setup):
    _, _, root = setup
    (root / "config/n8n_momentum_lifecycle_candidate.json").write_text('{"enabled":true}')
    path = root / "config/lane_registry.json"
    rows = json.loads(path.read_text())
    row = {"lane_id": "momentum-lifecycle-monitor", "state": "ACTIVE", "scheduler": {"stage": "shadow"}}
    rows["lanes"].append(row)
    path.write_text(json.dumps(rows))
    shadow = M.durable_view(root, root, now=NOW)
    assert shadow["state"] == "REFUSED" and shadow["monitor_stage"] == "shadow"
    row["scheduler"]["stage"] = "canary"
    path.write_text(json.dumps(rows))
    drift = M.durable_view(root, root, now=NOW)
    assert drift["state"] == "REFUSED" and drift["monitor_stage"] == "canary"


def test_contract_digest_has_no_release_sha_or_review_self_reference():
    contract = reviewed_fixture_contract("momentum-lifecycle-monitor")
    digest = M.contract_body_digest(contract)
    contract["review"]["reviewed_sha"] = "b" * 40
    contract["review"]["contract_body_sha256"] = digest
    assert M.contract_body_digest(contract) == digest and M.contract_review_proven(contract)
    contract["purpose"]["text"] += " changed body"
    assert not M.contract_review_proven(contract)


def test_review_requires_real_decision_reference_not_digest_proposal():
    contract = reviewed_fixture_contract("momentum-lifecycle-monitor")
    contract["review"]["decision_ref"] = None
    assert not M.contract_review_proven(contract)
    contract["review"]["decision_ref"] = "fixture://operator-decision"
    contract["status"] = "DRAFT"
    assert not M.contract_review_proven(contract)


def test_owner_confirmation_cannot_be_promoted_by_digest_alone():
    contract = reviewed_fixture_contract("momentum-lifecycle-monitor")
    contract["ownership_confirmation"] = "NOT_MEASURED"
    contract["review"]["contract_body_sha256"] = M.contract_body_digest(contract)
    assert not M.contract_review_proven(contract)


@pytest.mark.parametrize("confirmation", [None, "", False, "CONFIRMED_BY_AGENT", "NOT_MEASURED", "UNRESOLVED"])
def test_owner_acceptance_requires_the_explicit_accepted_value(confirmation):
    contract = reviewed_fixture_contract("momentum-lifecycle-monitor")
    contract["ownership_confirmation"] = confirmation
    contract["review"]["contract_body_sha256"] = M.contract_body_digest(contract)
    assert not M.contract_review_proven(contract)
    contract.pop("ownership_confirmation")
    contract["review"]["contract_body_sha256"] = M.contract_body_digest(contract)
    assert not M.contract_review_proven(contract)


def test_durable_monitor_refuses_alternate_policy_and_fixture_provenance(setup, monkeypatch):
    _, admission, root = setup
    admitted_monitor(admission)
    monkeypatch.setattr(M, "load_admission", lambda code_root: admission)
    policy = {"enabled": True, "watch": [{"lane_id": "early-source"}]}
    (root / "config/n8n_momentum_lifecycle_candidate.json").write_text(json.dumps(policy))
    report = {
        "schema": M.SCHEMA,
        "as_of": NOW.isoformat(),
        "source_sha": admission.deployed_sha,
        "collection_source": "HOST_SNAPSHOT",
        "candidate_sha256": M.contract_body_digest(policy),
    }
    path = root / M.MONITOR_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report))
    assert M.durable_view(root, root, now=NOW)["schema"] == M.SCHEMA
    for change in ({"collection_source": "EXPLICIT_FIXTURE"}, {"candidate_sha256": "0" * 64}):
        path.write_text(json.dumps({**report, **change}))
        assert M.durable_view(root, root, now=NOW)["reason"] == "momentum_monitor_policy_or_collection_drift"


def test_deployed_sha_gate_is_independent_of_content_review(setup):
    from dataclasses import replace

    c, a, _ = setup
    admitted_monitor(a)
    different_release = replace(a, deployed_sha="b" * 40)
    assert M.monitor_admitted(different_release)
    result = M.plan_recovery(armed(c), repair_report(), different_release, snapshot=repair_snapshot(), now=NOW)
    assert result["held"][0]["reason"] == "deployed_sha_drift"


def test_retry_proposal_uses_existing_due_slot_and_never_host_manual_budget(setup):
    from scripts.lib.n8n_coordination_gateway import host_run_request

    c, a, _ = setup
    intent = M.plan_recovery(armed(c), repair_report(), a, snapshot=repair_snapshot(), now=NOW)["intents"][0]
    assert intent["run_id"] == "d:momentum-cache-reconcile:live:20261012T0600:a2"
    assert "due" in intent["submission_owner"]
    refusal = host_run_request(
        lane_id=intent["lane_id"],
        mode="live",
        run_id=intent["run_id"],
        requested_by="fixture",
        caller_id="fixture",
        run_store=None,
        run_allowlist=frozenset({intent["lane_id"]}),
        now=NOW.timestamp(),
    )
    assert refusal["reason"] == "run_slot_not_due"


def test_enabled_config_cannot_authorize_health_writer(setup, tmp_path):
    from scripts.n8n_momentum_lifecycle import main

    c, _, root = setup
    c["enabled"] = True
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(c))
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--host-snapshot",
                "--code-root",
                str(root),
                "--state-root",
                str(root),
                "--candidate",
                str(candidate),
                "--write-monitor",
                "--now",
                NOW.isoformat(),
            ]
        )
    assert exc.value.code == 2 and not (root / M.MONITOR_REL).exists()


def patched_sources():
    """Apply the proposed integration diff in memory; shared source never modified by tests."""
    import re

    patch = ROOT / "docs/implementation/n8n-maturity/reconciliation-20261012/MOMENTUM_GATEWAY_INTEGRATION.patch"
    result = {}
    integrated_markers = {
        "scripts/lib/n8n_coordination_gateway.py": 'if operation == "momentum_lifecycle":',
        "scripts/n8n_coordination_gateway.py": "from scripts.lib.n8n_momentum_lifecycle import durable_view",
        "scripts/n8n_run_relay.py": "def momentum_lifecycle(",
        "scripts/n8n_incident_fanin.py": "def _momentum_lifecycle_findings(",
        "scripts/incident_notifier.py": "momentum_host_watch",
    }
    for chunk in patch.read_text().split("--- a/")[1:]:
        path, rest = chunk.split("\n", 1)
        current = (ROOT / path).read_text()
        if integrated_markers[path] in current:
            result[path] = current
            continue  # integrator-applied source is tested directly; do not apply its proposal twice
        original = current.splitlines(True)
        output, cursor = [], 0
        for hunk in re.split(r"(?m)^@@ ", rest)[1:]:
            header, body = hunk.split("\n", 1)
            location = re.match(r"-(\d+)(?:,(\d+))?", header)
            start = int(location[1]) if location[2] == "0" else int(location[1]) - 1
            output.extend(original[cursor:start])
            cursor = start
            for line in body.splitlines(True):
                if line.startswith(" "):
                    assert original[cursor] == line[1:]
                    output.append(line[1:])
                    cursor += 1
                elif line.startswith("-"):
                    assert original[cursor] == line[1:]
                    cursor += 1
                elif line.startswith("+"):
                    output.append(line[1:])
        output.extend(original[cursor:])
        result[path] = "".join(output)
    return result


def test_integration_patch_authenticates_and_rejects_caller_authority():
    import ast
    from scripts.lib import n8n_coordination_gateway as gateway

    patched = patched_sources()["scripts/lib/n8n_coordination_gateway.py"]
    function = next(n for n in ast.parse(patched).body if isinstance(n, ast.FunctionDef) and n.name == "handle_request")
    namespace = dict(gateway.__dict__)
    exec(compile(ast.Module(body=[function], type_ignores=[]), "candidate-gateway", "exec"), namespace)
    key = b"fixture-gateway-only-no-secret-32-bytes"

    def request(**extra):
        claim = {
            "v": 1,
            "caller_id": "n8n-lab",
            "project": "trade-ai",
            "iat": NOW.timestamp(),
            "exp": NOW.timestamp() + 120,
            "nonce": "fixture-momentum-nonce",
            "scope": "coordination_read",
        }
        return {
            "route": "coordination/status",
            "operation": "momentum_lifecycle",
            "claim": claim,
            "signature": gateway.sign_claim(claim, key),
            **extra,
        }

    def call(req):
        return namespace["handle_request"](
            req,
            key=key,
            now=NOW,
            nonce_store={},
            idempotency_store={},
            expected_origin_sha=SHA,
            momentum_provider=lambda now: {"schema": M.SCHEMA},
        )

    assert call(request()) == {"schema": M.SCHEMA}
    assert call(request(armed=True))["reason"] == "unexpected_field"
    assert call({"route": "coordination/status", "operation": "momentum_lifecycle"})["reason"] == "missing_signature"
    for source in patched_sources().values():
        ast.parse(source)


def test_integration_patch_relay_uses_read_scope_and_fixture_transport(tmp_path):
    import ast
    from scripts import n8n_run_relay as relay_module

    source = patched_sources()["scripts/n8n_run_relay.py"]
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "Relay")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "momentum_lifecycle")
    namespace = dict(relay_module.__dict__)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "candidate-relay", "exec"), namespace)
    calls = []

    def transport(url, payload):
        calls.append(payload)
        return 200, {"schema": M.SCHEMA}

    relay = relay_module.Relay(
        environ={
            relay_module.BEARER_ENV: "fixture-bearer-32-bytes-long-ONLY!",
            relay_module.N8N_KEY_ENV: "fixture-hmac-32-bytes-long-ONLY!!",
            "TRADEAI_STATE_ROOT": str(tmp_path),
        },
        allowlist=frozenset(),
        transport=transport,
        clock=NOW.timestamp,
    )
    method = namespace["momentum_lifecycle"]
    assert method(relay, "Bearer fixture-bearer-32-bytes-long-ONLY!")[0] == 200
    assert calls[0]["claim"]["scope"] == "coordination_read"
    assert set(calls[0]) == {"route", "operation", "claim", "signature"}
    assert method(relay, "Bearer fixture-bearer-32-bytes-long-ONLY!", "armed=1")[0] == 400
    assert len(calls) == 1


def test_integration_patch_fanin_stale_deadman_is_independent_host_p1(setup):
    import ast
    from scripts import n8n_incident_fanin as fanin

    _, _, root = setup
    (root / "config/n8n_momentum_lifecycle_candidate.json").write_text('{"enabled":true}')
    source = patched_sources()["scripts/n8n_incident_fanin.py"]
    fn = next(
        n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_momentum_lifecycle_findings"
    )
    namespace = {**fanin.__dict__, "ROOT": root}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "candidate-fanin", "exec"), namespace)
    findings = namespace[fn.name](root, NOW)
    assert findings[0]["severity"] == "P1"
    assert findings[0]["operator_action"] is False
    assert findings[0]["notification_dedupe_minutes"] is None
    report = {
        "schema": M.SCHEMA,
        "as_of": NOW.isoformat(),
        "source_sha": SHA,
        "incidents": [M._finding("latest_scan_package", "wrong_business_day", "2026-10-12")],
    }
    M.write_monitor(report, root)
    assert namespace[fn.name](root, NOW) == report["incidents"]


def test_real_candidate_workflow_and_draft_contracts_are_safe_and_concrete():
    from scripts.lib.n8n_health_contracts import validate_contract

    base = ROOT / "docs/implementation/n8n-maturity"
    workflow = json.loads((base / "workflows/tradeai-momentum-lifecycle-candidate.json").read_text())
    assert workflow["active"] is False
    assert workflow["settings"]["saveDataSuccessExecution"] == "none"
    assert workflow["settings"]["errorWorkflow"] == "tradeai-incident-router"
    http = [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
    assert all(
        n["credentials"] == {"httpHeaderAuth": {"id": "tradeai-run-relay", "name": "tradeai-run-relay"}} for n in http
    )
    assert all(n["parameters"]["method"] == "GET" for n in http)
    assert any("/runs/momentum-lifecycle-monitor/last?mode=dry_run" in n["parameters"]["url"] for n in http)
    assert any("/momentum-lifecycle" in n["parameters"]["url"] for n in http)
    contractdoc = json.loads((base / "reconciliation-20261012/MOMENTUM_HEALTH_CONTRACT_PROPOSALS.json").read_text())
    assert len(contractdoc["contracts"]) == 15 and contractdoc["operative_changes"] is False
    for contract in contractdoc["contracts"]:
        assert contract["status"] == "DRAFT" and contract["review"]["reviewed_by"] is None
        assert validate_contract(contract) == []
        assert contract["review"]["contract_body_sha256"] == M.contract_body_digest(contract)
        assert contract["review"]["decision_ref"] is None


def test_activation_packet_registry_dispatch_and_executor_templates_are_machine_valid(tmp_path):
    from scripts.lib.lane_registry import validate_row
    from scripts.lib.lane_dispatch import parse_dispatch_block, validate_dispatch_block
    from scripts.n8n_run_executor import build_argv, build_child_env, validate_entry

    p = ROOT / "docs/implementation/n8n-maturity/reconciliation-20261012/MOMENTUM_ACTIVATION_PACKET.json"
    packet = json.loads(p.read_text())
    for key in ("new_monitor_proposal", "cache_reconcile_proposal"):
        spec = packet[key]
        assert validate_row(spec["registry_row"]) == []
        assert parse_dispatch_block(spec["registry_row"]) is not None
        assert validate_dispatch_block(spec["registry_row"], retry_policy_names=["none"]) == []
        entry = spec["allowlist"]
        assert validate_entry(entry) is None
        env, receipt = build_child_env({"TRADEAI_EXECUTOR_ENV_ALLOWLIST": "enforce"}, spec["lane_id"], entry)
        assert env is not None and receipt["reason"] is None
        argv = build_argv(entry, "dry_run", env={}, state_root=tmp_path / "state", code_root=tmp_path / "code")
        assert "--dry-run" in argv and not any("{" in arg or "$" in arg for arg in argv)
        assert entry["lock"] + ".dryrun" in argv
    assert any(g["scope"] == "release-write" for g in packet["grants_required"])


def test_staged_paused_proposals_cannot_emit_due_requests_even_when_allowlisted():
    from scripts.lib.n8n_due import compute_due
    from scripts.lib.n8n_retry_policy import load_policies

    p = ROOT / "docs/implementation/n8n-maturity/reconciliation-20261012/MOMENTUM_ACTIVATION_PACKET.json"
    packet = json.loads(p.read_text())
    specs = [packet[key] for key in ("new_monitor_proposal", "cache_reconcile_proposal")]
    rows = [spec["registry_row"] for spec in specs]
    allowlist = {spec["lane_id"]: spec["allowlist"] for spec in specs}
    policies = load_policies(ROOT / "config/n8n_retry_policies.json")
    assert all(row["state"] == "PAUSED" and row["dispatch"]["mode"] == "off" for row in rows)
    held = compute_due(rows, allowlist, policies, None, NOW)
    assert held["items"] == [] and held["errors"] == []
    # Demonstrate why the hold must be dispatch off rather than PAUSED alone.
    accidental_dry_run = copy.deepcopy(rows)
    for row in accidental_dry_run:
        row["dispatch"]["mode"] = "dry_run"
    unsafe = compute_due(accidental_dry_run, allowlist, policies, None, NOW)
    assert {item["lane_id"] for item in unsafe["items"]} == {row["lane_id"] for row in rows}


def test_host_notifier_candidate_operator_action_is_not_suppressed_or_double_counted():
    import ast
    from scripts import incident_notifier as notifier

    source = patched_sources()["scripts/incident_notifier.py"]
    functions = [
        n
        for n in ast.parse(source).body
        if isinstance(n, ast.FunctionDef) and n.name in {"open_incidents", "_due", "apply_result"}
    ]
    namespace = dict(notifier.__dict__)
    exec(compile(ast.Module(body=functions, type_ignores=[]), "candidate-notifier", "exec"), namespace)
    f = M._finding("finviz-credential", "credential_owner_action_required", "2026-10-12", operator_action=True)
    host = {**f, "momentum_host_watch": True}
    opened, _ = namespace["open_incidents"]({"incidents": [f, host]}, set())
    assert len(opened) == 1
    key, row = next(iter(opened.items()))
    assert row["momentum_host_watch"] is True and row["operator_action"] is True
    state = {"notified": {key: {"open": True, "severity": "P1", "last_notified_at": NOW.isoformat()}}}
    assert namespace["_due"](key, row, state, NOW, 24) is True
    namespace["apply_result"](state, {"kind": "p1", "incidents": [row], "identity": "fixture-alert"}, NOW)
    assert state["notified"][key]["momentum_host_watch"] is True


def test_lifecycle_p1_failure_preserves_priority_without_claiming_operator_decision():
    from scripts import incident_notifier as notifier

    finding = M._finding("served_scan_cache", "wrong_business_day", "2026-10-12")
    assert finding["severity"] == "P1"
    assert finding["operator_action"] is False
    assert finding["notification_dedupe_minutes"] is None
    opened, _ = notifier.open_incidents({"incidents": [finding]}, set())
    key, row = next(iter(opened.items()))
    assert notifier._due(key, row, {"notified": {}}, NOW, 24) is True
    state = {"notified": {key: {"open": True, "severity": "P1", "last_notified_at": NOW.isoformat()}}}
    assert notifier._due(key, row, state, NOW, 24) is False
