"""LQ-20261107-2468 (REVIEW-2463 F1): a kill-switch / revoke word that the 2445 identifier guards reject must be
UNCLASSIFIED (warning, not in the Home class map -> Home UNKNOWN), never the quiet default job_telemetry/info.
A real kill text stays critical emergency_kill_or_revoke, and the 2445 false-P0 fixes still hold. Synthetic texts."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from operator_alert_policy_v2 import classify_legacy_message  # noqa: E402

KILL = "emergency_kill_or_revoke"


@pytest.mark.parametrize("text", [
    # the REVIEW-2463 F1 table
    "KILL_SWITCH_ENGAGED level=hard",
    "\U0001F6D1 KILL-SWITCH-ENGAGED level=hard",
    "kill-switch-tripped on account X",
    "atm_kill_switch fired for ACCT1",
    "ALERT trade_kill_switch triggered",
    "token_revoked: schwab",
    "EMERGENCY_KILL executed",
    "Emergency-kill executed",
])
def test_2468_guard_rejected_kill_or_revoke_is_unclassified_never_info(text):
    ev = classify_legacy_message(text)
    assert ev.alert_type == "unclassified", text
    assert ev.severity == "warning", text
    assert ev.alert_type != "job_telemetry"
    assert not ev.operator_action_required  # not a P0 page: nothing here is known to be a real kill


@pytest.mark.parametrize("text", [
    "ATM KILL SWITCH FIRED: aggregate daily P&L breached",
    "kill_switch active: HARD - orders blocked",
    "Kill switch HARD: engaged",
    "session revoked by operator",
    "EMERGENCY KILL executed",
])
def test_2468_real_kill_texts_stay_critical(text):
    ev = classify_legacy_message(text)
    assert ev.alert_type == KILL and ev.severity == "critical" and ev.operator_action_required, text


@pytest.mark.parametrize("text", [
    "\U0001F6A8 *RELEASE NOT REACHED after promote* — 2026-11-12\n• unit: ops_applier_writes_grants_killswitch_stop",
    "\U0001F4E6 *PR merge digest* — 3 ready\n*#1001* — the cleaner's own kill switch must be set",
])
def test_2468_the_2445_notices_stay_job_telemetry(text):
    ev = classify_legacy_message(text)
    assert ev.alert_type == "job_telemetry", text


def test_2468_health_agent_exemption_is_kept():
    assert classify_legacy_message("[health agent] kill switch check").alert_type == "job_telemetry"
    assert classify_legacy_message("system health: token_revoked probe ok").alert_type == "job_telemetry"


def test_2468_ordinary_text_is_still_the_quiet_default():
    ev = classify_legacy_message("nothing to see here")
    assert (ev.alert_type, ev.severity) == ("job_telemetry", "info")


def test_2468_an_earlier_rule_still_wins_over_unclassified():
    # an identifier token inside a text another rule claims keeps that rule's class (no blanket UNKNOWN)
    ev = classify_legacy_message("[PLATFORM_AVAILABILITY] tradeai-killswitch-watch.service is down")
    assert ev.alert_type == "platform_availability"
