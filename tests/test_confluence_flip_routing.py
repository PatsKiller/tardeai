#!/usr/bin/env python3
"""confluence_flip must route DIGEST, never IMMEDIATE, never critical.

This is the authority-adjacent boundary for the one symbol-scope alert that may
fire: it is advisory context, not capital at risk, and it must never dilute
CRITICAL_IMMEDIATE_TYPES (AGENTS.md §17A: diluting the critical set is how a
critical channel stops being read).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from operator_alert_policy_v2 import (  # noqa: E402
    AlertEvent,
    CRITICAL_IMMEDIATE_TYPES,
    ROUTE_DIGEST,
    route_event,
)


def _event() -> AlertEvent:
    return AlertEvent(
        alert_type="confluence_flip",
        source_system="indicator_engine",
        source_producer="oscillator_alerts",
        symbol="NVDA",
    )


def test_confluence_flip_routes_digest():
    d = route_event(_event())
    assert d.route_mode == ROUTE_DIGEST


def test_confluence_flip_is_never_critical():
    assert "confluence_flip" not in CRITICAL_IMMEDIATE_TYPES


def test_confluence_flip_is_not_immediate_even_when_severe():
    ev = _event()
    # Even a producer that (wrongly) marks it urgent must not flip it to IMMEDIATE,
    # because confluence_flip has no capital-at-risk meaning.
    ev = AlertEvent(**{**ev.__dict__, "severity": "urgent"})
    assert route_event(ev).route_mode == ROUTE_DIGEST


def test_material_change_immediate_is_not_regressed():
    """The routing change must not disturb an existing IMMEDIATE type."""
    ev = AlertEvent(alert_type="material_change", source_system="x", source_producer="y", symbol="Z")
    assert route_event(ev).route_mode != ROUTE_DIGEST
