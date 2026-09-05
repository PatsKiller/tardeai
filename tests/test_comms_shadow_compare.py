#!/usr/bin/env python3
"""Unit tests for Phase 11 SHADOW legacy-vs-gateway compare helper."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.comms.shadow_compare import (  # noqa: E402
    compare_legacy_vs_gateway,
    extract_route_intent,
    record_shadow_observation,
    reset_shadow_observations,
    shadow_report,
)
from scripts.lib.comms import (  # noqa: E402
    compare_legacy_vs_gateway as exported_compare,
    record_shadow_observation as exported_record,
    shadow_report as exported_report,
)


@pytest.fixture(autouse=True)
def _clean():
    reset_shadow_observations()
    yield
    reset_shadow_observations()


def test_compare_full_match():
    legacy = {
        "subject_key": "system:watchdog",
        "severity": "info",
        "channels": ["telegram"],
        "intended_action": "notify",
    }
    gateway = {
        "subject_key": "system:watchdog",
        "severity": "info",
        "channels": ["telegram"],
        "intended_action": "notify",
        "event_id": "evt_1",
    }
    result = compare_legacy_vs_gateway(legacy, gateway)
    assert result["match"] is True
    assert result["mismatches"] == []
    assert set(result["matches"]) == {"subject_key", "severity", "route_intent"}
    assert result["fields"]["subject_key"]["match"] is True
    assert result["fields"]["severity"]["match"] is True
    assert result["fields"]["route_intent"]["match"] is True


def test_compare_subject_key_mismatch():
    result = compare_legacy_vs_gateway(
        {"subject_key": "alert:a", "severity": "warn", "channel": "telegram"},
        {"subject_key": "alert:b", "severity": "warn", "channels": ["telegram"]},
    )
    assert result["match"] is False
    assert "subject_key" in result["mismatches"]
    assert "severity" in result["matches"]


def test_compare_severity_and_route_intent_mismatch():
    legacy = {
        "subject_key": "symbol:AAPL",
        "severity": "critical",
        "channels": ["telegram"],
        "intended_action": "notify",
    }
    gateway = {
        "subject_key": "symbol:AAPL",
        "severity": "info",
        "channels": ["slack"],
        "intended_action": "escalate",
    }
    result = compare_legacy_vs_gateway(legacy, gateway)
    assert result["match"] is False
    assert "severity" in result["mismatches"]
    assert "route_intent" in result["mismatches"]
    assert "subject_key" in result["matches"]


def test_extract_route_intent_from_explicit_and_composed():
    assert extract_route_intent(
        {"route_intent": {"channels": ["telegram"], "intended_action": "notify"}}
    ) == {"channels": ["telegram"], "intended_action": "notify"}
    composed = extract_route_intent(
        {"channel": "telegram", "action": "notify"}
    )
    assert composed["channels"] == ["telegram"]
    assert composed["intended_action"] == "notify"


def test_record_shadow_observation_and_report():
    legacy = {
        "subject_key": "system:watchdog",
        "severity": "info",
        "channels": ["telegram"],
        "intended_action": "notify",
    }
    gateway_ok = dict(legacy, event_id="evt_ok")
    gateway_bad = {
        "subject_key": "system:other",
        "severity": "info",
        "channels": ["telegram"],
        "intended_action": "notify",
        "event_id": "evt_bad",
    }
    row1 = record_shadow_observation(
        legacy_decision=legacy,
        gateway_event=gateway_ok,
        producer="ops.watchdog",
    )
    row2 = record_shadow_observation(
        legacy_decision=legacy,
        gateway_event=gateway_bad,
        producer="ops.watchdog",
        note="subject drift",
    )
    assert row1["match"] is True
    assert row2["match"] is False
    assert "subject_key" in row2["mismatches"]

    report = shadow_report()
    assert report["total_observations"] == 2
    assert report["matched"] == 1
    assert report["mismatched"] == 1
    assert report["match_rate"] == 0.5
    assert report["mismatch_counts_by_field"]["subject_key"] == 1
    assert report["delivery_owned"] is False
    assert len(report["observations"]) == 2


def test_package_exports():
    assert exported_compare is compare_legacy_vs_gateway
    assert exported_record is record_shadow_observation
    assert exported_report is shadow_report
