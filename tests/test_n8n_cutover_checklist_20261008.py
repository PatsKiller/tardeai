"""Cutover checklist renders with and without evidence; every input is optional.

Evidence is planted under tmp_path only (check_test_host_paths forbids literal host paths).
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import n8n_cutover_checklist as cl

LANE = "n8n-lab-watchdog"
SHA = "a" * 40
NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)


def _lane() -> dict:
    return next(lane for lane in cl.LANES if lane["lane_id"] == LANE)


def test_renders_with_no_evidence_at_all(tmp_path):
    text = cl.render(tmp_path, tmp_path, [_lane()], LANE)
    assert f"# n8n cutover checklist — {LANE}" in text
    assert text.count("- [ ]") == 12 and "- [x]" not in text
    assert "NOT_MEASURED" in text
    assert "n8n_lane_readiness_last.json absent" in text
    assert "lane not in INDEX.json" in text or "INDEX.json absent" in text


def _plant(root: Path, rel: str, obj) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_legacy_receipts_do_not_establish_acceptance(tmp_path):
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    # workflows committed
    _plant(
        repo,
        "docs/implementation/n8n-parallel/workflows/generated/INDEX.json",
        {"lanes": [{"lane_id": LANE, "shadow_file": f"{LANE}-shadow.json", "live_file": f"{LANE}.json"}]},
    )
    _plant(repo, f"docs/implementation/n8n-parallel/workflows/generated/{LANE}-shadow.json", {})
    _plant(repo, f"docs/implementation/n8n-parallel/workflows/generated/{LANE}.json", {})
    # registry row flipped to n8n
    _plant(state, "config/lane_registry.json", {"lanes": [{"lane_id": LANE, "scheduler": {"kind": "n8n"}}]})
    # run receipts: one dry_run done, one live done, one unrelated lane
    _plant(
        state, "data/runtime/n8n_runs/a.json", {"lane_id": LANE, "mode": "dry_run", "state": "RUN_DONE", "exit_code": 0}
    )
    _plant(
        state, "data/runtime/n8n_runs/b.json", {"lane_id": LANE, "mode": "live", "state": "RUN_DONE", "exit_code": 0}
    )
    _plant(state, "data/runtime/n8n_runs/c.json", {"lane_id": "other", "mode": "live", "state": "RUN_FAILED"})
    # cutover receipts: dry + apply, rollback dry only
    _plant(state, "data/runtime/n8n_cutover/1.json", {"lane_id": LANE, "action": "cutover", "dry_run": True})
    _plant(state, "data/runtime/n8n_cutover/2.json", {"lane_id": LANE, "action": "cutover", "dry_run": False})
    _plant(state, "data/runtime/n8n_cutover/3.json", {"lane_id": LANE, "action": "rollback", "dry_run": True})
    # readiness + board
    _plant(state, "data/runtime/n8n_lane_readiness_last.json", {"lanes": [{"lane_id": LANE, "verdict": "READY"}]})
    _plant(
        state,
        "data/runtime/n8n_migration_board_last.json",
        {
            "rows": {
                LANE: {
                    "phase": "cutover",
                    "rollback_ready": True,
                    "output_signal_fresh": True,
                    "output_signal_age_h": 0.1,
                }
            }
        },
    )
    items = {i["step"]: i["done"] for i in cl.lane_items(state, repo, _lane())}
    assert items == {
        "workflows": True,
        "registry_row": True,
        "shadow": False,
        "canary": False,
        "readiness": True,
        "cutover_dry": False,
        "cutover_apply": False,
        "registry_n8n": True,
        "rollback_dry": False,
        "rollback_real": False,
        "board": True,
        "natural_fire": False,
    }
    text = cl.render(state, repo, [_lane()], LANE)
    assert text.count("- [x]") == 5 and text.count("- [ ]") == 7


def test_failed_live_receipt_blocks_canary_and_garbage_files_are_ignored(tmp_path):
    state = tmp_path
    _plant(state, "data/runtime/n8n_runs/ok.json", {"lane_id": LANE, "mode": "live", "state": "RUN_DONE"})
    _plant(
        state,
        "data/runtime/n8n_runs/bad.json",
        {"lane_id": LANE, "mode": "live", "state": "RUN_SKIPPED_LOCK", "exit_code": 0},
    )
    (state / "data/runtime/n8n_runs/junk.json").write_text("{not json", encoding="utf-8")
    items = {i["step"]: i for i in cl.lane_items(state, state, _lane())}
    assert items["canary"]["done"] is False
    assert "NOT_MEASURED" in items["canary"]["evidence"]


def _acceptance(tmp_path):
    _plant(tmp_path, "config/lane_registry.json", {"lanes": [{"lane_id": LANE,
           "scheduler": {"kind": "n8n"}, "dispatch": {"cron": ["*/5 * * * *"], "tz": "America/New_York"}}]})
    _plant(tmp_path, "data/runtime/n8n_cutover/applied.json", {"lane_id": LANE, "action": "cutover",
        "mode": "apply", "applied": True, "code_sha": SHA, "at": "2026-10-12T10:16:00Z", "problems": []})
    _plant(tmp_path, "config/n8n_health_contracts.json", {"contracts": [{
        "schema": "N8nHealthContract@v1", "id": LANE, "kind": "lane", "status": "REVIEWED",
        "workflow_id": "fixture-workflow", "owner": "platform", "purpose": {"text": "fixture monitor"},
        "connects_to": [{"name": "fixture-output", "direction": "read"}],
        "healthy": [{"check": "fresh", "text": "fresh fixture output"}],
        "degraded": [{"check": "late", "text": "late fixture output"}],
        "failed": [{"check": "missing", "text": "missing fixture output"}],
        "baseline": {"basis": "OPERATOR_SLO", "freshness_degraded_after_h": 24, "timeout_s": 60},
        "alerting": {"degraded": {"notifier_priority": "P2"}, "failed": {"notifier_priority": "P1"}},
        "remediation": {}, "evidence": {"verify": ["inspect fixture"]},
    }]})
    packet = {"tested_sha": SHA, "deployed_sha": SHA, "fixes_deployed_at": "2026-10-12T09:00:00Z",
              "observed_at": "2026-10-12T12:00:00Z", "lanes": {LANE: {"runs": []}}}
    for n, mode, klass in [(1, "dry_run", "NATURAL_SHADOW"), (2, "dry_run", "NATURAL_SHADOW"),
                           (3, "live", "MANUAL_CANARY"), (4, "live", "NATURAL_POST_CUTOVER")]:
        run_id = f"fixture-run-{n}"
        started = f"2026-10-12T10:{n * 5:02d}:00Z"
        finished = f"2026-10-12T10:{n * 5:02d}:10Z"
        slot_key = f"d:{LANE}:{mode}:20261012T06{n * 5:02d}" if klass != "MANUAL_CANARY" else None
        receipt = {"schema": "RunReceipt@v2", "lane_id": LANE, "run_id": run_id, "mode": mode,
                   "state": "RUN_DONE", "exit_code": 0, "verdict": "ok", "code_sha": SHA,
                   "started_at": started, "finished_at": finished, "duration_s": 10, "slot_key": slot_key,
                   "lock_skipped": False, "timed_out": False, "output_signal_mtime_before": 1,
                   "output_signal_mtime_after": 1 if mode == "dry_run" else 2,
                   "lock": {"path": "fixture.lock.dryrun" if mode == "dry_run" else "fixture.lock",
                            "scope": "dryrun" if mode == "dry_run" else "live"}}
        _plant(tmp_path, f"data/runtime/n8n_runs/{n}.json", receipt)
        proof_ref = f"data/runtime/effect-proof/{n}.json"
        _plant(tmp_path, proof_ref, {"lane_id": LANE, "run_id": run_id, "code_sha": SHA,
               "observed_at": "2026-10-12T11:00:00Z", "business_effect_count": 0 if mode == "dry_run" else 1,
               "duplicate_effect_count": 0, "output_matches_contract": True, "consumer_correct": True})
        packet["lanes"][LANE]["runs"].append({
            "run_id": run_id, "evidence_class": klass, "legacy_authoritative": True,
            "legacy_lock": "fixture.lock", "effect_proof_ref": proof_ref,
            "n8n_execution": {"execution_id": f"fixture-execution-{n}", "workflow_id": "fixture-workflow",
                "run_id": run_id, "trigger_kind": "manual" if klass == "MANUAL_CANARY" else "schedule",
                "started_at": started, "finished_at": finished},
            "ledger_run": {**receipt, "requested_at": started, "caller_id": "n8n-relay"},
        })
    return packet


def _items(tmp_path, packet, **kwargs):
    return {it["step"]: it for it in cl.lane_items(tmp_path, tmp_path, _lane(),
            acceptance=packet, expected_sha=SHA, now=NOW, **kwargs)}


def test_two_correlated_natural_shadows_and_effect_checks_accept(tmp_path):
    packet = _acceptance(tmp_path)
    items = _items(tmp_path, packet)
    assert items["shadow"]["done"] and "2 distinct" in items["shadow"]["evidence"]
    assert items["canary"]["done"] and items["natural_fire"]["done"]
    assert "MANUAL_CANARY" in items["canary"]["evidence"]
    assert "flock proves" not in items["canary"]["label"]


@pytest.mark.parametrize("change", ["one_fire", "manual", "one_slot", "wrong_sha", "pre_fix",
    "stale", "missing_n8n", "wrong_workflow", "ledger_drift", "exit_drift", "lock_skip", "business_write"])
def test_shadow_rejects_insufficient_or_conflicting_evidence(tmp_path, change):
    packet = _acceptance(tmp_path)
    obs = packet["lanes"][LANE]["runs"]
    if change == "one_fire":
        del obs[1]
    elif change == "manual":
        obs[1]["evidence_class"] = "MANUAL_CANARY"
    elif change == "one_slot":
        obs[1]["ledger_run"]["slot_key"] = obs[0]["ledger_run"]["slot_key"]
        path = tmp_path / "data/runtime/n8n_runs/2.json"
        row = json.loads(path.read_text())
        row["slot_key"] = obs[0]["ledger_run"]["slot_key"]
        path.write_text(json.dumps(row))
    elif change == "wrong_sha":
        packet["deployed_sha"] = "b" * 40
    elif change == "pre_fix":
        packet["fixes_deployed_at"] = "2026-10-12T10:13:00Z"
    elif change == "stale":
        packet["observed_at"] = "2026-10-10T12:00:00Z"
    elif change == "missing_n8n":
        del obs[1]["n8n_execution"]
    elif change == "wrong_workflow":
        obs[1]["n8n_execution"]["workflow_id"] = "wrong-workflow"
    elif change == "ledger_drift":
        obs[1]["ledger_run"]["state"] = "RUN_FAILED"
    elif change in {"exit_drift", "lock_skip"}:
        path = tmp_path / "data/runtime/n8n_runs/2.json"
        row = json.loads(path.read_text())
        row["exit_code" if change == "exit_drift" else "lock_skipped"] = 7 if change == "exit_drift" else True
        path.write_text(json.dumps(row))
    elif change == "business_write":
        path = tmp_path / obs[1]["effect_proof_ref"]
        row = json.loads(path.read_text())
        row["business_effect_count"] = 1
        path.write_text(json.dumps(row))
    assert not _items(tmp_path, packet)["shadow"]["done"]


@pytest.mark.parametrize("change", ["lock_only", "duplicates", "wrong_receipt_sha", "unknown_contract",
                                  "stale_receipt", "outside_proof", "no_expected_sha"])
def test_canary_rejects_unproven_output_and_release_identity(tmp_path, change):
    packet = _acceptance(tmp_path)
    obs = packet["lanes"][LANE]["runs"][2]
    # Post-cutover evidence is not a substitute for a canary.
    packet["lanes"][LANE]["runs"].pop()
    if change == "lock_only":
        del obs["effect_proof_ref"]
    elif change == "duplicates":
        path = tmp_path / obs["effect_proof_ref"]
        row = json.loads(path.read_text())
        row["duplicate_effect_count"] = 1
        path.write_text(json.dumps(row))
    elif change in {"wrong_receipt_sha", "stale_receipt"}:
        path = tmp_path / "data/runtime/n8n_runs/3.json"
        row = json.loads(path.read_text())
        row["code_sha" if change == "wrong_receipt_sha" else "finished_at"] = (
            "b" * 40 if change == "wrong_receipt_sha" else "2026-10-10T10:03:10Z")
        path.write_text(json.dumps(row))
    elif change == "unknown_contract":
        path = tmp_path / "config/n8n_health_contracts.json"
        doc = json.loads(path.read_text())
        doc["contracts"][0]["purpose"]["text"] = "UNKNOWN — needs owner"
        path.write_text(json.dumps(doc))
    elif change == "outside_proof":
        obs["effect_proof_ref"] = "../../outside.json"
    kwargs = {"acceptance": packet, "expected_sha": None if change == "no_expected_sha" else SHA, "now": NOW}
    items = {it["step"]: it for it in cl.lane_items(tmp_path, tmp_path, _lane(), **kwargs)}
    assert not items["canary"]["done"]


def test_duplicate_receipt_files_and_manual_shadows_do_not_add_natural_fires(tmp_path):
    packet = _acceptance(tmp_path)
    packet["lanes"][LANE]["runs"] = [packet["lanes"][LANE]["runs"][0]]
    copied = json.loads((tmp_path / "data/runtime/n8n_runs/1.json").read_text())
    _plant(tmp_path, "data/runtime/n8n_runs/last.json", copied)
    packet["lanes"][LANE]["runs"].append(deepcopy(packet["lanes"][LANE]["runs"][0]))
    assert not _items(tmp_path, packet)["shadow"]["done"]


def test_refused_cutover_receipt_never_ticks_apply(tmp_path):
    packet = _acceptance(tmp_path)
    _plant(tmp_path, "data/runtime/n8n_cutover/applied.json", {})
    _plant(tmp_path, "data/runtime/n8n_cutover/refused.json", {"lane_id": LANE, "action": "cutover",
        "mode": "apply", "applied": False, "code_sha": SHA, "at": "2026-10-12T11:00:00Z",
        "problems": ["no authority"]})
    assert not _items(tmp_path, packet)["cutover_apply"]["done"]


def test_correlated_request_may_start_before_host_receipt(tmp_path):
    packet = _acceptance(tmp_path)
    packet["lanes"][LANE]["runs"][0]["ledger_run"]["finished_at"] = "2026-10-12T10:05:11Z"
    assert _items(tmp_path, packet)["shadow"]["done"]


@pytest.mark.parametrize("change", ["execution_reused", "current_failed_run", "off_schedule", "unknown_baseline",
                                  "malformed_contract", "pre_cutover_natural"])
def test_additional_drift_is_not_hidden_by_successful_receipts(tmp_path, change):
    packet = _acceptance(tmp_path)
    obs = packet["lanes"][LANE]["runs"]
    if change == "execution_reused":
        obs[1]["n8n_execution"]["execution_id"] = obs[0]["n8n_execution"]["execution_id"]
    elif change == "current_failed_run":
        failed = dict(obs[0]["ledger_run"], run_id="failed-current", state="RUN_FAILED", exit_code=1)
        _plant(tmp_path, "data/runtime/n8n_runs/failure.json", failed)
    elif change == "off_schedule":
        _plant(tmp_path, "config/lane_registry.json", {"lanes": [{"lane_id": LANE,
               "dispatch": {"cron": ["0 * * * *"], "tz": "America/New_York"}}]})
    elif change in {"unknown_baseline", "malformed_contract"}:
        path = tmp_path / "config/n8n_health_contracts.json"
        doc = json.loads(path.read_text())
        doc["contracts"][0]["baseline"] = {"basis": "OPERATOR_SLO"} if change == "unknown_baseline" else []
        path.write_text(json.dumps(doc))
    elif change == "pre_cutover_natural":
        _plant(tmp_path, "data/runtime/n8n_cutover/applied.json", {"lane_id": LANE, "action": "cutover",
            "mode": "apply", "applied": True, "code_sha": SHA, "at": "2026-10-12T11:00:00Z", "problems": []})
    items = _items(tmp_path, packet)
    assert not items["natural_fire" if change == "pre_cutover_natural" else "shadow"]["done"]


def test_acceptance_cli_reads_the_declared_packet_and_writes_no_state(tmp_path, monkeypatch, capsys):
    packet = _acceptance(tmp_path)
    _plant(tmp_path, "acceptance.json", packet)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(cl, "datetime", FixedDatetime)
    assert cl.main(["--lane", LANE, "--state-root", str(tmp_path), "--repo-root", str(tmp_path),
                    "--expected-sha", SHA, "--acceptance-evidence", str(tmp_path / "acceptance.json")]) == 0
    out = capsys.readouterr().out
    assert "[x] Shadow: two natural fires" in out
    assert not (tmp_path / f"data/runtime/n8n_cutover_checklist_{LANE}.md").exists()


def test_cli_lane_tranche_and_write(tmp_path, capsys):
    assert cl.main(["--lane", LANE, "--state-root", str(tmp_path), "--repo-root", str(tmp_path)]) == 0
    assert LANE in capsys.readouterr().out
    assert cl.main(["--tranche", "N1", "--state-root", str(tmp_path), "--repo-root", str(tmp_path), "--write"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["lanes"] == 9
    written = Path(out["wrote"])
    assert written == tmp_path / "data" / "runtime" / "n8n_cutover_checklist_N1.md"
    assert "across 9 lane(s)" in written.read_text(encoding="utf-8")
    assert cl.main(["--lane", "no-such-lane", "--state-root", str(tmp_path)]) == 2
