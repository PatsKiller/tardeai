import json
from pathlib import Path

import pytest

from scripts.agent_runtime.monitoring import (
    CANONICAL_AGENT_IDS,
    MonitoringContractError,
    fixture_snapshot,
    fleet_summary,
    load_maturity_catalog,
    watch_context_panel,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "agent_maturity_catalog.json"


def _payload():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _write(tmp_path, payload):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_maturity_catalog_is_complete_shadow_only_and_authority_denied():
    catalog = load_maturity_catalog(CATALOG)

    assert set(catalog) == CANONICAL_AGENT_IDS
    assert {record.deployment_state for record in catalog.values()} == {
        "DESIGNED",
        "SHADOW",
    }
    assert {
        agent_id
        for agent_id, record in catalog.items()
        if record.deployment_state == "SHADOW"
    } == {"sentinel", "darwin", "iris", "reflection", "argus"}
    assert all(
        set(record.authority.values()) == {"DENIED"}
        for record in catalog.values()
    )
    assert all(record.stop_conditions for record in catalog.values())
    assert all(record.disable_control for record in catalog.values())
    assert all(record.rollback_control for record in catalog.values())


def test_monitoring_summary_and_fixture_are_honest_about_unavailable_runtime():
    catalog = load_maturity_catalog(CATALOG)
    summary = fleet_summary(
        catalog,
        runs=[
            {"status": "RUNNING"},
            {"status": "FAILED"},
            {"status": "DEADLINE_EXCEEDED"},
            {"status": "provider_specific_unknown"},
        ],
        artifacts=[
            {"reviewed": True, "scored": False},
            {"reviewed": False, "scored": False},
        ],
    )

    assert summary["agent_count"] == 16
    assert summary["lifecycle_counts"]["SHADOW"] == 5
    assert summary["lifecycle_counts"]["DESIGNED"] == 11
    assert summary["run_counts"]["RUNNING"] == 1
    assert summary["run_counts"]["FAILED"] == 1
    assert summary["run_counts"]["DEADLINE_EXCEEDED"] == 1
    assert summary["unknown_run_count"] == 1
    assert summary["artifact_counts"] == {
        "total": 2,
        "unreviewed": 1,
        "unscored": 2,
    }
    assert summary["authority"]["all_forbidden_capabilities_denied"] is True

    snapshot = fixture_snapshot(catalog, as_of="2026-07-25T00:00:00+00:00")
    assert snapshot["source_kind"] == "FIXTURE"
    assert snapshot["data_state"] == "NOT_RUN"
    assert snapshot["runs"] == []
    assert snapshot["artifacts"] == []
    assert snapshot["summary"]["run_counts"]["RUNNING"] == 0
    assert len(snapshot["snapshot_hash"]) == 64
    assert "fixture data does not prove operational agent activity" in snapshot["limitations"]


def test_watch_context_is_read_only_and_cannot_mutate_sovereign_decision():
    catalog = load_maturity_catalog(CATALOG)
    panel = watch_context_panel(catalog)

    assert panel["read_only"] is True
    assert panel["sovereign_decision_mutation"] is False
    assert panel["actions"] == []
    assert [agent["agent_id"] for agent in panel["agents"]] == [
        "sentinel",
        "argus",
        "darwin",
        "reflection",
        "iris",
    ]
    assert all(
        agent["authority"]["broker_authority"] == "DENIED"
        for agent in panel["agents"]
    )


def test_catalog_rejects_missing_stop_control(tmp_path):
    payload = _payload()
    del payload["agents"]["sentinel"]["stop_conditions"]

    with pytest.raises(MonitoringContractError, match="missing fields"):
        load_maturity_catalog(_write(tmp_path, payload))


def test_catalog_rejects_any_forbidden_authority(tmp_path):
    payload = _payload()
    payload["agents"]["sentinel"]["authority"]["broker_authority"] = "ALLOW"

    with pytest.raises(MonitoringContractError, match="forbidden authority"):
        load_maturity_catalog(_write(tmp_path, payload))


def test_catalog_cannot_claim_operational_before_acceptance(tmp_path):
    payload = _payload()
    payload["agents"]["sentinel"]["deployment_state"] = "OPERATIONAL"

    with pytest.raises(MonitoringContractError, match="cannot be represented as OPERATIONAL"):
        load_maturity_catalog(_write(tmp_path, payload))
