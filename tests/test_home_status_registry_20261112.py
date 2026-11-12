"""HOME_STATUS_REGISTRY_20261112 — the incident-class map, requires_stop and stop_exempt_accounts the spec (LQ-2149)
puts in config/home_status_registry.json (REVIEW-2164b C1). Synthetic fixtures; no database."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import home_diagnostics as hd  # noqa: E402
from lib import home_v010_api as api  # noqa: E402

# The 15 alert_type values seen open on 2026-11-11 (fixture list, not a production read).
OPEN_ALERT_TYPES = [
    "job_telemetry", "paper_proposal", "scanner_candidate", "orphaned_stop", "stop_warning", "research_update",
    "data_integrity", "proposal_blocked_or_rebuild", "siem_without_trading_impact", "emergency_kill_or_revoke",
    "cio_entry_state", "thesis_update", "position_unprotected", "platform_availability", "trading_impact_outage"]

RAW = json.loads((ROOT / "config" / "home_status_registry.json").read_text(encoding="utf-8"))


def test_every_open_alert_type_is_mapped():
    assert len(OPEN_ALERT_TYPES) == 15
    assert set(OPEN_ALERT_TYPES) <= set(RAW["incident_classes"])


def test_class_fields_and_the_p0_blockers():
    classes = RAW["incident_classes"]
    for key, c in classes.items():
        assert {"category", "priority", "blocks_trading_default", "owner", "ttl_h", "proof_window_h", "home_visible"} <= set(c), key
        assert c["owner"] in RAW["owners"]
    assert classes["position_unprotected"]["priority"] == "P0" and classes["position_unprotected"]["blocks_trading_default"]
    assert classes["data_integrity"]["priority"] == "P1" and not classes["data_integrity"]["blocks_trading_default"]
    assert classes["job_telemetry"]["priority"] == "INFO" and not classes["job_telemetry"]["home_visible"]


def test_the_map_is_marked_a_proposal_until_the_operator_approves_it():
    assert RAW["incident_classes_approved"] is False and "operator" in RAW["incident_classes_note"].lower()


def test_requires_stop_and_exempt_accounts():
    assert {"equity", "etf"} <= set(RAW["requires_stop"]["asset_types"])
    assert isinstance(RAW["stop_exempt_accounts"], list)


def test_every_cause_key_the_code_can_emit_exists():
    emitted = {"NO_SOURCE", "READ_TIMEOUT", "READ_FAILURE", "COLLECTOR_STALE"} | {s["cause_category"] for s in RAW["sources"]}
    assert emitted <= set(RAW["causes"])


def test_every_lane_and_authority_domain_exists():
    lanes = {l["id"] if "id" in l else l.get("lane_id") for l in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]}
    for s in RAW["sources"]:
        if s.get("owner_lane"):
            assert s["owner_lane"] in lanes, s["source_id"]


@pytest.mark.parametrize("mutate,match", [
    (lambda d: d.pop("incident_classes"), "incident_classes"),
    (lambda d: d["incident_classes"]["job_telemetry"].update(priority="P9"), "priority"),
    (lambda d: d["incident_classes"]["job_telemetry"].update(owner="nobody"), "owner"),
    (lambda d: d["incident_classes"]["job_telemetry"].update(blocks_trading_default=True), "INFO class cannot block"),
    (lambda d: d.pop("incident_classes_approved"), "incident_classes_approved"),
    (lambda d: d["requires_stop"].update(asset_types=[]), "asset_types"),
    (lambda d: d.update(stop_exempt_accounts="x"), "stop_exempt_accounts"),
])
def test_validator_rejects_a_broken_incident_registry(mutate, match):
    doc = copy.deepcopy(RAW)
    mutate(doc)
    with pytest.raises(hd.RegistryError, match=match):
        hd.validate_incident_registry(doc)


def test_registry_endpoint_view_is_read_only_and_complete():
    out = api.registry_view()
    assert out["state"] == "OK" and set(OPEN_ALERT_TYPES) <= set(out["incident_classes"])
    assert out["incident_classes_approved"] is False and "requires_stop" in out and "stop_exempt_accounts" in out
