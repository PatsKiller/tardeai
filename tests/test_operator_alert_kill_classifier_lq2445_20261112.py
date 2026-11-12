"""LQ-20261107-2445: the legacy classifier must not turn deploy/release notices or identifier tokens into an
Emergency Kill P0, and a real kill-switch or revoke alert must stay critical KILL_REVIEW.

Measured 2026-11-12 09:47 ET: a "RELEASE NOT REACHED after promote" deploy notice naming the unit flag
``ops_applier_writes_grants_killswitch_stop`` became incident emergency_kill_or_revoke (critical), so Home read NO.
All texts here are synthetic (repo is public); shapes follow the producers named in each test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from operator_alert_policy_v2 import classify_legacy_message  # noqa: E402

KILL = "emergency_kill_or_revoke"

# scripts/current_bound_units.py renders "🚨 *RELEASE NOT REACHED after {what}* — {day}" then one bullet per unit.
DEPLOY_NOTICE = (
    "🚨 *RELEASE NOT REACHED after promote* — 2026-11-12\n"
    "• *tradeai-example-runner.service*: restarted but not running the new release\n"
    "• *tradeai-ops-applier.service*: on an old release, intentionally deferred by the deploy "
    "(ops_applier_writes_grants_killswitch_stop) — operator action: "
    "`systemctl --user restart tradeai-ops-applier.service`"
)
# scripts/lib/pr_merge_digest.py renders "📦 *PR merge digest* — N ready (`id`)" then PR summaries (free prose).
PR_DIGEST = (
    "📦 *PR merge digest* — 3 ready (`0123456789ab`)\n*Ready for your approval*\n"
    "*#1001* — disk guard: the cleaner's own kill switch must be set before it removes anything"
)


@pytest.mark.parametrize("text", [
    DEPLOY_NOTICE,
    DEPLOY_NOTICE.replace("promote", "deploy"),
    PR_DIGEST,
    # identifier-style tokens anywhere, not only in a deploy notice
    "lane ops-applier: flag ops_applier_writes_grants_killswitch_stop is set",
    "unit tradeai-killswitch-watch.service restarted",
    "readiness gate kill_switches_clear passed",
    # prose that merely contains the letters
    "Fix: require a CURRENT UNREVOKED approval before acting",
    "grant_revoked_at column backfilled for 12 rows",
])
def test_2445_notices_and_identifier_tokens_are_not_an_emergency_kill(text):
    ev = classify_legacy_message(text)
    assert ev.alert_type != KILL, text
    assert ev.operator_action_type != "KILL_REVIEW"


def test_2445_the_measured_deploy_notice_is_job_telemetry_warning():
    ev = classify_legacy_message(DEPLOY_NOTICE)
    assert (ev.alert_type, ev.severity, ev.operator_action_required) == ("job_telemetry", "warning", False)


def test_2445_pr_merge_digest_is_job_telemetry_info():
    ev = classify_legacy_message(PR_DIGEST)
    assert (ev.alert_type, ev.severity) == ("job_telemetry", "info")


@pytest.mark.parametrize("text", [
    # scripts/atm_auto_approver.py shapes
    "ATM KILL SWITCH FIRED: aggregate daily P&L -3.4% — ATM PAUSED",
    "ATM KILL SWITCH: acct_synthetic daily P&L -2.1% — account paused",
    # scripts/execution_state.py blocker shape and plain prose
    "kill_switch active: account — daily loss limit",
    "Kill switch engaged at account level by operator",
    "KILL-SWITCH tripped: broker level",
    "EMERGENCY KILL engaged — all sessions halted",
    "Live session revoked by operator",
    "Operator approval REVOKED for live trading",
    "kill switches engaged on 2 accounts",
])
def test_2445_a_real_kill_or_revoke_stays_critical_kill_review(text):
    ev = classify_legacy_message(text)
    assert (ev.alert_type, ev.severity, ev.operator_action_required, ev.operator_action_type) == (
        KILL, "critical", True, "KILL_REVIEW"), text


def test_2445_a_notice_marker_later_in_a_real_kill_alert_does_not_demote_it():
    # the notice rule is anchored at the start; a kill alert that quotes a notice is still a kill
    ev = classify_legacy_message("ATM KILL SWITCH FIRED — see RELEASE NOT REACHED after promote notice")
    assert ev.alert_type == KILL


def test_2445_health_agent_exemption_is_unchanged():
    assert classify_legacy_message("Health agent: kill switch inspect ok").alert_type != KILL
