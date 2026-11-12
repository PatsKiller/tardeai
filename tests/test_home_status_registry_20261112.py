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


def test_the_map_is_approved_and_the_note_records_the_decision():
    # LQ-20261107-2264: operator approved D2 on 2026-11-12 (~10:12 ET); the flip is recorded in the note
    assert RAW["incident_classes_approved"] is True
    note = RAW["incident_classes_note"]
    assert "APPROVED" in note and "operator" in note.lower() and "D2-PROPOSAL-20261112" in note


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
    assert out["incident_classes_approved"] is True and "unclassified_incident" in out and "requires_stop" in out and "stop_exempt_accounts" in out


# ---- LQ-20261107-2264: the approved D2 class map (surface columns) ----------------------------------------------------
D2_EXPECT = {  # alert type -> (priority, home_status, trade_ready_effect, verdict, blocks)
    "position_unprotected": ("P0", "CRITICAL", "NO", "ACT NOW", True),
    "trading_impact_outage": ("P0", "CRITICAL", "NO", "ACT NOW", True),
    "emergency_kill_or_revoke": ("P0", "CRITICAL", "NO", "ACT NOW", True),
    "orphaned_stop": ("P1", "WARN", "NONE", "ACT TODAY", False),   # D2-d: warns, does not block
    "stop_warning": ("P1", "WARN", "NONE", "ACT TODAY", False),
    "data_integrity": ("P1", "WARN", "NONE", "ACT TODAY", False),
    "platform_availability": ("P1", "WARN", "NONE", "ACT TODAY", False),
}


@pytest.mark.parametrize("alert,exp", sorted(D2_EXPECT.items()))
def test_the_approved_d2_map_row(alert, exp):
    out = hd.incident_surface(RAW, alert)
    assert out["classified"] is True
    assert (out["priority"], out["home_status"], out["trade_ready_effect"], out["incident_verdict"], out["blocks_trading"]) == exp


def test_every_info_class_is_log_only_and_not_on_home():
    info = [k for k, c in RAW["incident_classes"].items() if c["priority"] == "INFO"]
    assert len(info) == 8
    for k in info:
        out = hd.incident_surface(RAW, k)
        assert out["home_status"] is None and out["incident_verdict"] == "LOG ONLY" and not out["blocks_trading"]
        assert RAW["incident_classes"][k]["home_visible"] is False


def test_a_p0_can_never_map_below_critical():
    p0 = [k for k, c in RAW["incident_classes"].items() if c["priority"] == "P0"]
    assert sorted(p0) == ["emergency_kill_or_revoke", "position_unprotected", "trading_impact_outage"]
    for k in p0:
        out = hd.incident_surface(RAW, k)
        assert out["home_status"] == "CRITICAL" and out["trade_ready_effect"] == "NO" and out["incident_verdict"] == "ACT NOW"
        assert out["blocks_trading"] is True


@pytest.mark.parametrize("field,value", [("home_status", "WARN"), ("home_status", None), ("trade_ready_effect", "NONE"),
                                          ("incident_verdict", "ACT TODAY"), ("blocks_trading_default", False)])
def test_the_loader_refuses_a_p0_mapped_below_critical(field, value):
    d = copy.deepcopy(RAW)
    d["incident_classes"]["position_unprotected"][field] = value
    with pytest.raises(hd.RegistryError):
        hd.validate_incident_registry(d)


def test_the_loader_refuses_a_p1_promoted_or_an_info_shown_on_home():
    d = copy.deepcopy(RAW)
    d["incident_classes"]["orphaned_stop"]["home_status"] = "CRITICAL"
    with pytest.raises(hd.RegistryError):
        hd.validate_incident_registry(d)
    d = copy.deepcopy(RAW)
    d["incident_classes"]["job_telemetry"]["home_status"] = "WARN"
    with pytest.raises(hd.RegistryError):
        hd.validate_incident_registry(d)


@pytest.mark.parametrize("alert", ["brand_new_alert_type", "", None, 7, "POSITION_UNPROTECTED"])
def test_an_unclassified_incident_is_unknown_never_ok_never_ignored(alert):
    out = hd.incident_surface(RAW, alert)
    assert out["classified"] is False
    assert out["trade_ready_effect"] == "UNKNOWN" and out["incident_verdict"] == "ACT TODAY" and out["home_status"] == "WARN"
    assert out["blocks_trading"] is False  # UNKNOWN is not NO; NO still overrides UNKNOWN (R3)


def test_the_loader_refuses_an_unclassified_mapping_that_ignores_or_passes_it():
    for field, bad in (("trade_ready_effect", "NONE"), ("trade_ready_effect", "YES"), ("incident_verdict", "LOG ONLY"), ("home_status", None)):
        d = copy.deepcopy(RAW)
        d["unclassified_incident"][field] = bad
        with pytest.raises(hd.RegistryError):
            hd.validate_incident_registry(d)
    d = copy.deepcopy(RAW)
    d.pop("unclassified_incident")
    with pytest.raises(hd.RegistryError):
        hd.validate_incident_registry(d)


def test_a_per_incident_override_may_only_raise_never_lower_a_p0():
    assert hd.incident_surface(RAW, "position_unprotected", blocks_override=False)["blocks_trading"] is True   # D2-c
    assert hd.incident_surface(RAW, "orphaned_stop", blocks_override=True)["blocks_trading"] is True           # raising is allowed
    assert hd.incident_surface(RAW, "orphaned_stop", blocks_override=None)["blocks_trading"] is False
