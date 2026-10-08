"""N6 observed schedules and fail-closed proposed external contracts; no live calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import lane_registry as L  # noqa: E402
from scripts.n8n_run_executor import load_allowlist  # noqa: E402
from scripts.pipelines.cutover._cutover import load_registry_exact  # noqa: E402

REMINDERS = {
    "openclaw-reminder-claude-plan-1": "openclaw-claude-plan-reminder-week-before",
    "openclaw-reminder-claude-plan-2": "openclaw-claude-plan-reminder-last-day",
    "openclaw-reminder-supergrok-expiry": "openclaw-supergrok-promo-expiry",
    "openclaw-reminder-sentinelone-earnings": "openclaw-sentinelone-earnings-reminder",
}
DOF = {"dof-run-pipeline": "0 20 * * 6", "dof-rescan-tickets": "0 18 * * *"}


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
    assert not n6 & load_allowlist(path).keys()
    assert all(doc["blocked_reasons"].get(lane) for lane in n6)
    for lane, cadence in DOF.items():
        proposal = doc["proposed_external_contracts"][lane]
        assert proposal["runnable"] is False
        assert proposal["observed_schedule"] == cadence
        assert proposal["observed_cwd"] == "$HOME/nyc-dof-auction"
        assert proposal["observed_command"][0] == ".venv/bin/python3"
        assert proposal["observed_lock"] is None and proposal["dry_run_arg"] is None
        assert "23.3" in doc["blocked_reasons"][lane]
