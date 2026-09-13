"""Availability and data-integrity alerts must interrupt, not wait in a digest.

WHY
---
On 2026-09-13 the plausibility monitor sent a real alert whose body began
"🚨 CRITICAL". It was still suppressed into the 4-hourly P1 digest, because
`telegram_alert_router` consults `operator_alert_policy_v2.route_event` FIRST
and returns on its verdict -- the `_P0_PATTERNS` list holding `URGENT|CRITICAL`
is only reached if that call raises. The word was decorative. Routing is by
alert_type.

That mattered: tradeai-cio-telegram.service sat disabled for five days, and the
Finviz column shift published inverted analyst ratings for five months. "A
service has been off at some point in the last four hours" is close to useless.

These types are deliberately NOT in CRITICAL_IMMEDIATE_TYPES. That set is
capital at risk right now -- orphaned stops, protection failures, broker auth --
and the policy file says plainly that diluting it "is how a critical channel
stops being read". A disabled service is not capital at risk. It follows the
`material_change` precedent instead: immediate, general channel, deduped hourly.

Routing keys off explicit sentinels, never prose: a reworded alert must not
silently change priority.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from operator_alert_policy_v2 import (  # noqa: E402
    CRITICAL_IMMEDIATE_TYPES,
    ROUTE_IMMEDIATE,
    classify_legacy_message,
    route_event,
)
from telegram_alert_router import classify_alert  # noqa: E402

AVAILABILITY = (
    "[PLATFORM_AVAILABILITY] 🚨 A service that should be running is OFF\n\n• [DISABLED] tradeai-cio-telegram.service"
)
AVAILABILITY_KNOWN = "[PLATFORM_AVAILABILITY] 🚨 Services off\n\n• [FAILED] trade-ai-lab-moomoo-opend.service"
RECOVERED = "[PLATFORM_AVAILABILITY] ✅ Services: everything declared in expected_services.json is on."
INTEGRITY = "[DATA_INTEGRITY] 🚨 A new column is off its declared scale\n\n• analyst_consensus_history.recom_score"


@pytest.mark.parametrize(
    "msg,expected_type",
    [
        (AVAILABILITY, "platform_availability"),
        (AVAILABILITY_KNOWN, "platform_availability"),
        (RECOVERED, "platform_availability"),
        (INTEGRITY, "data_integrity"),
    ],
)
def test_the_sentinel_selects_the_alert_type(msg, expected_type):
    assert classify_legacy_message(msg).alert_type == expected_type


@pytest.mark.parametrize("msg", [AVAILABILITY, AVAILABILITY_KNOWN, RECOVERED, INTEGRITY])
def test_these_route_immediate(msg):
    assert route_event(classify_legacy_message(msg)).route_mode == ROUTE_IMMEDIATE


@pytest.mark.parametrize("msg", [AVAILABILITY, INTEGRITY])
def test_the_router_tier_is_p0_interrupt(msg):
    """The end the producer actually reaches, through send_telegram."""
    assert classify_alert(msg) == "P0_INTERRUPT"


def test_deduped_hourly_so_a_persistent_outage_speaks_once_per_hour():
    d = route_event(classify_legacy_message(AVAILABILITY))
    assert d.dedupe_window_seconds == 3600


def test_not_added_to_the_capital_at_risk_set():
    """Diluting that set is how a critical channel stops being read."""
    for t in ("platform_availability", "data_integrity"):
        assert t not in CRITICAL_IMMEDIATE_TYPES


# ── negative controls: nothing else got escalated ────────────────────────────


@pytest.mark.parametrize(
    "msg",
    [
        "pipeline retry_exhausted on nightly job",
        "cron success: sync completed",
        "debug: uploaded unchanged",
    ],
)
def test_ordinary_job_noise_still_digests(msg):
    assert route_event(classify_legacy_message(msg)).route_mode != ROUTE_IMMEDIATE


def test_health_degraded_is_unchanged():
    assert classify_alert("Health Agent: DEGRADED — 70/100") == "P2_DASHBOARD_ONLY"


def test_prose_alone_does_not_escalate():
    """The word CRITICAL is not, and must not become, the routing key.

    A message can say anything; only the sentinel decides priority.
    """
    prose = "🚨 CRITICAL — something sounds urgent but carries no sentinel"
    assert route_event(classify_legacy_message(prose)).route_mode != ROUTE_IMMEDIATE


def test_a_sentinel_anywhere_in_the_body_is_honoured():
    """Producers may prepend a heading; the token need not lead the message."""
    msg = "Daily report\n\n[DATA_INTEGRITY] a column is off its declared scale"
    assert classify_legacy_message(msg).alert_type == "data_integrity"


def test_both_producers_emit_their_sentinel():
    """A routing rule nothing triggers is worse than no rule."""
    avail = (ROOT / "scripts" / "check_expected_services.py").read_text()
    integ = (ROOT / "scripts" / "data_plausibility_monitor.py").read_text()
    assert "[PLATFORM_AVAILABILITY]" in avail
    assert "[DATA_INTEGRITY]" in integ
