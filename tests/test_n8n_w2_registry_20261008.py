"""N6 observed schedules and fail-closed proposed external contracts; no live calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_coordination_gateway as SERVER  # noqa: E402
from scripts import n8n_run_executor as EXECUTOR  # noqa: E402
from scripts import n8n_run_relay as RELAY  # noqa: E402
from scripts.lib import lane_registry as L  # noqa: E402
from scripts.lib import n8n_coordination_gateway as GATEWAY  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402
from scripts.n8n_run_executor import load_allowlist  # noqa: E402
from scripts.pipelines.cutover._cutover import load_registry_exact  # noqa: E402

REMINDERS = {
    "openclaw-reminder-claude-plan-1": "openclaw-claude-plan-reminder-week-before",
    "openclaw-reminder-claude-plan-2": "openclaw-claude-plan-reminder-last-day",
    "openclaw-reminder-supergrok-expiry": "openclaw-supergrok-promo-expiry",
    "openclaw-reminder-sentinelone-earnings": "openclaw-sentinelone-earnings-reminder",
}
DOF = {"dof-run-pipeline": "0 20 * * 6", "dof-rescan-tickets": "0 18 * * *"}
N6 = sorted(set(REMINDERS) | set(DOF))
N6_REQUEST_IDS = sorted(set(N6) | set(REMINDERS.values()))
ALLOWLIST_PATH = ROOT / "config/n8n_run_allowlist.json"


def _rows():
    registry = L.load_registry(ROOT / "config/lane_registry.json")
    assert L.validate_registry(registry) == []
    return {row["lane_id"]: row for row in registry["lanes"]}


def test_all_six_canonical_n6_ids_exist_without_serialisation_churn():
    rows = _rows()
    tranches = json.loads((ROOT / "config/n8n_migration_tranches.json").read_text())
    n6 = {row["lane_id"] for row in tranches["tranches"]["N6"]["lanes"]}
    assert n6 == set(REMINDERS) | set(DOF)
    assert n6 <= rows.keys()
    assert load_registry_exact(ROOT / "config/lane_registry.json")[2] is None


def test_dof_cron_provenance_is_observed_not_n8n_activated():
    rows = _rows()
    for lane, cadence in DOF.items():
        row = rows[lane]
        assert row["scheduler"]["kind"] == "cron"
        assert row["scheduler"]["expression"] == cadence
        assert "nyc-dof-auction" in row["scheduler"]["match"]
        assert row["state"] == "ACTIVE"
        assert "SQL" in row["note"] and "Observed crontab" in row["note"]
    assert rows["dof-run-pipeline"]["output_signal"]["kind"] == "none"
    assert "NO_SIGNAL" in rows["dof-run-pipeline"]["note"]


def test_rescan_signal_is_a_bounded_read_of_the_actual_updated_column():
    signal = _rows()["dof-rescan-tickets"]["output_signal"]
    queries = []

    def read_only(sql):
        queries.append(sql)
        return [("2026-10-08T18:01:00+00:00",)]

    result = L.observe_signal(signal, db_query=read_only)
    assert result["readable"] is True
    assert queries == ["SELECT max(lookup_at) FROM dof_ticket_lookups WHERE rescan_count > 0"]
    assert L.observe_signal(signal)["readable"] is False


def test_native_reminders_link_existing_generated_ids_but_remain_unscheduled():
    rows = _rows()
    index = json.loads((ROOT / "docs/implementation/n8n-parallel/workflows/generated/INDEX.json").read_text())
    generated = {row["lane_id"]: row for row in index["lanes"]}
    for lane, alias in REMINDERS.items():
        row = rows[lane]
        assert row["scheduler"]["kind"] == "n8n"
        assert row["scheduler"]["expression"] == generated[alias]["live_workflow_id"]
        assert alias in row["note"]
        assert row["state"] == "NEVER_SCHEDULED"
        assert row["reason_confidence"] == "ESTABLISHED"
        assert "NO_SIGNAL" in row["state_reason"]
        assert row["output_signal"]["kind"] == "none"


def test_calendar_and_delivery_defects_are_explicit_not_silently_accepted():
    rows = _rows()
    assert "not equivalent" in rows["openclaw-reminder-claude-plan-2"]["note"]
    for lane in ("openclaw-reminder-supergrok-expiry", "openclaw-reminder-sentinelone-earnings"):
        assert "one-shot/deactivation" in rows[lane]["note"]
    assert "lastDeliveryStatus=not-requested" in rows["openclaw-reminder-claude-plan-1"]["note"]


def test_pending_foreign_commands_are_not_loaded_as_executable_allowlist_entries():
    path = ROOT / "config/n8n_run_allowlist.json"
    doc = json.loads(path.read_text())
    n6 = set(REMINDERS) | set(DOF)
    assert set(doc["pending_tranches"]["N6"]) == n6
    assert not set(N6_REQUEST_IDS) & load_allowlist(path).keys()
    assert not set(N6_REQUEST_IDS) & SERVER.load_run_allowlist(path)
    assert all(doc["blocked_reasons"].get(lane) for lane in n6)
    for lane, cadence in DOF.items():
        proposal = doc["proposed_external_contracts"][lane]
        assert proposal["runnable"] is False
        assert proposal["observed_schedule"] == cadence
        assert proposal["observed_cwd"] == "$HOME/nyc-dof-auction"
        assert proposal["observed_command"][0] == ".venv/bin/python3"
        assert proposal["observed_lock"] is None and proposal["dry_run_arg"] is None
        assert "23.3" in doc["blocked_reasons"][lane]


@pytest.mark.parametrize("lane_id", N6_REQUEST_IDS)
@pytest.mark.parametrize("mode", ["dry_run", "live"])
def test_gateway_refuses_each_n6_lane_without_recording_a_run(tmp_path, lane_id, mode):
    """A signed request cannot promote documentation-only proposals into executable lanes."""
    key = b"fixture-only-w2-key-" + b"x" * 32
    now = 1_791_000_000.0
    claim = {
        "v": 1,
        "caller_id": "n8n-relay",
        "project": "trade-ai",
        "iat": now,
        "exp": now + 120,
        "nonce": "w2-fixture-nonce-0001",
        "scope": GATEWAY.SCOPE_RUN,
    }
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    try:
        run_id = "w2-fixture-request-0001"
        result = GATEWAY.handle_request(
            {
                "claim": claim,
                "signature": GATEWAY.sign_claim(claim, key),
                "route": "coordination/run",
                "operation": "run",
                "lane_id": lane_id,
                "mode": mode,
                "idempotency_key": run_id,
                "requested_by": "n8n:workflow:w2-test",
            },
            key=key,
            now=now,
            nonce_store={},
            idempotency_store={},
            expected_origin_sha="f" * 40,
            caller_keys=GATEWAY.build_caller_keys(key, n8n_key=key),
            run_store=LedgerRunStore(ledger),
            run_allowlist=SERVER.load_run_allowlist(ALLOWLIST_PATH),
        )
        assert result["state"] == "REFUSED"
        assert result["reason"] == "run_lane_not_allowlisted"
        assert LedgerRunStore(ledger).get(run_id) is None
    finally:
        ledger.close()


@pytest.mark.parametrize("lane_id", N6_REQUEST_IDS)
@pytest.mark.parametrize("mode", ["dry_run", "live"])
def test_relay_and_executor_refuse_n6_without_transport_or_spawn(tmp_path, lane_id, mode):
    """Neither live-canary flags nor an existing queued row widen the executable set."""

    def forbidden_call(*args, **kwargs):
        pytest.fail("a blocked N6 lane reached network transport or subprocess execution")

    bearer = "w2-fixture-bearer-" + "x" * 32
    relay = RELAY.Relay(
        environ={
            RELAY.BEARER_ENV: bearer,
            RELAY.N8N_KEY_ENV: "w2-fixture-signing-key-" + "x" * 32,
            RELAY.LIVE_LANES_ENV: " ".join(N6_REQUEST_IDS),
            "TRADEAI_STATE_ROOT": str(tmp_path / "state"),
        },
        allowlist=SERVER.load_run_allowlist(ALLOWLIST_PATH),
        transport=forbidden_call,
    )
    status, body = relay.run(
        "Bearer " + bearer,
        json.dumps({"lane_id": lane_id, "mode": mode, "idempotency_key": "w2-fixture-request-0001"}).encode(),
    )
    assert status == 403 and body["reason"] == "relay_lane_not_allowlisted"
    assert bearer not in relay.log_path.read_text()
    receipt = EXECUTOR.execute(
        {"run_id": "w2-fixture-request-0001", "lane_id": lane_id, "mode": mode},
        load_allowlist(ALLOWLIST_PATH).get(lane_id),
        env={},
        state_root=tmp_path / "state",
        code_root=ROOT,
        runner=forbidden_call,
    )
    assert receipt["state"] == "RUN_REFUSED"
    assert receipt["reason"] == "lane_not_allowlisted"
    assert receipt["argv"] is None


def test_existing_n3_n4_contracts_keep_explicit_cron_side_lock_provenance():
    entries = {row["lane_id"]: row for row in json.loads(ALLOWLIST_PATH.read_text())["lanes"]}
    shared_locks = {
        "generate-analyst-daily-digest": "/tmp/analyst_daily_digest.lock",
        "catalyst-calibration-monitor": "/tmp/catalyst_calibration_monitor.lock",
        "source-attribution-monitor": "/tmp/source_attribution_monitor.lock",
        "watch-directives-monitor": "/tmp/watch_directives_monitor.lock",
    }
    for lane, lock in shared_locks.items():
        assert entries[lane]["lock"] == lock
        assert "flock -n " + lock in entries[lane]["source"]
    for lane in ("desk-suggestions-digest", "job-coverage-monitor", "finviz-view-contracts"):
        assert "no lock" in entries[lane]["source"] or "no cron lock" in entries[lane]["source"]
        assert "canary" in entries[lane]["source"]
