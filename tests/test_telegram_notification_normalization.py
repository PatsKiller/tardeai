import csv
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from alert_outbox import publish_event, publish_legacy_message, validate_preference_change
from evaluate_telegram_notification_normalization import evaluate
from notification_url_builder import build_alert_url, sanitize_operator_message
from operator_alert_policy_v2 import (
    APPROVALS_ONLY,
    CRITICAL_OPERATIONS,
    AlertEvent,
    alert_fingerprint,
    classify_legacy_message,
    route_event,
)

FIXTURE = ROOT / "docs/ops/alerts/telegram_notification_normalization_2026_07_28/telegram_notification_audit_last_7_days.csv"


def test_paper_proposals_never_route_to_approvals():
    msg = "❓ Paper Proposal: GDHG\n`/ptapprove 1`\n`/ptreject 1`"
    ev = classify_legacy_message(msg)
    decision = route_event(ev)
    assert ev.alert_type == "paper_proposal"
    assert decision.logical_destination != APPROVALS_ONLY
    assert decision.route_mode == "COMMAND_CENTER"


def test_approvals_channel_requires_live_authorization_reference():
    ev = AlertEvent(
        alert_type="live_order_2fa_required",
        source_system="test",
        source_producer="test",
        operator_action_required=True,
        authorization_or_order_id="intent-test",
    )
    decision = route_event(ev)
    assert decision.logical_destination == APPROVALS_ONLY
    assert decision.route_mode == "IMMEDIATE"

    no_auth = AlertEvent(
        alert_type="live_order_2fa_required",
        source_system="test",
        source_producer="test",
        operator_action_required=True,
    )
    blocked = route_event(no_auth)
    assert blocked.logical_destination != APPROVALS_ONLY
    assert blocked.suppression_reason == "approval_channel_requires_explicit_live_authorization"


def test_p1_digest_queues_instead_of_individual_send():
    decision = publish_legacy_message("Morning Brief\nPortfolio updates and watchlist changes")
    assert decision["route_mode"] == "DIGEST"
    assert decision["send_immediate"] is False


def test_repeated_incident_updates_same_fingerprint():
    ev = AlertEvent(
        alert_type="broker_auth_blocking",
        source_system="schwab",
        source_producer="schwab_token_manager",
        account_id="schwab_roth_ira",
        severity="critical",
        operator_action_required=True,
        operator_action_type="BROKER_AUTH_REPAIR",
    )
    first = publish_event(ev)
    second = publish_event(ev)
    assert first["fingerprint"] == second["fingerprint"] == alert_fingerprint(ev)
    assert first["send_immediate"] is True
    assert second["send_immediate"] is False
    assert second["suppression_reason"] == "duplicate_within_fingerprint"


def test_orphaned_stops_batch_to_one_incident():
    incidents = set()
    for sym in ["ANET", "ARKX", "CSCO", "DIVI", "DXCM", "QCOM", "SCHG"]:
        ev = classify_legacy_message(f"🚨 STOP HEALTH — ORPHANED: {sym} (fidelityrolloverira)")
        decision = route_event(ev)
        assert decision.logical_destination == CRITICAL_OPERATIONS
        incidents.add(publish_event(ev)["incident_id"])
    assert len(incidents) == 1


def test_url_redaction_and_alert_deeplink():
    url = build_alert_url("abc 123")
    assert url == "https://ms01-openclaw.tail163d14.ts.net/v3/go/alert/abc%20123"
    text = "Open http://localhost:7777/v2/alerts then cd /home/johnclaw/project and use state=abc"
    sanitized, violations = sanitize_operator_message(text)
    assert "localhost" not in sanitized
    assert ":7777" not in sanitized
    assert "/v2/" not in sanitized
    assert "state=abc" not in sanitized
    assert "/home/johnclaw" not in sanitized
    assert violations


def test_settings_safety_invariants():
    assert "paper_candidate_types_cannot_route_to_approvals" in validate_preference_change(
        "paper_proposal",
        {"approval_telegram": "IMMEDIATE", "general_telegram": "OFF", "command_center": True, "digest_bucket": "TRADING", "ttl_seconds": 3600},
    )
    assert "live_protection_failures_cannot_be_disabled_from_every_surface" in validate_preference_change(
        "position_unprotected",
        {"approval_telegram": "OFF", "general_telegram": "OFF", "command_center": False, "digest_bucket": "RISK", "ttl_seconds": 3600},
    )


def test_csv_replay_acceptance_projection():
    result = evaluate(FIXTURE)
    assert result["paper_to_approvals_count"] == 0
    assert result["approval_total"] == result["approval_live_authorization_count"]
    assert result["cross_channel_duplicate_count"] == 0
    assert result["route_counts"]["DIGEST"] > 0
    assert result["immediate_correlated_incident_count"] <= 12
    assert result["dashboard_only_count"] > result["immediate_raw_count"]


def test_telegram_chokepoint_enforcement_ratchet():
    """Replaces a guard that a bypass could walk through.

    The prior version matched only the literal api.telegram.org/.../sendMessage, so a
    producer satisfied it by writing __import__("telegram_transport").TELEGRAM_SEND_
    MESSAGE_API.format(...) while still calling requests.post, still reading the bot
    token and still choosing the chat id. 39 producers did exactly that and the guard
    stayed green.

    Enforcement now runs scripts/check_telegram_chokepoint.py, which detects the
    behaviour (transport import, endpoint constant, raw endpoint, HTTP call aimed at
    Telegram, chat-id selection, token read) and ratchets against a recorded baseline:
    a NEW bypassing file fails, an existing one may never grow. It does not claim zero
    — 47 files currently bypass the chokepoint and that is a tracked release blocker.
    """
    import subprocess
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_telegram_chokepoint.py")],
        capture_output=True, text=True)
    assert r.returncode == 0, f"chokepoint ratchet failed:\n{r.stdout}\n{r.stderr}"


def test_telegram_chokepoint_baseline_is_honest():
    """The baseline must record real debt, not assert a false zero."""
    import json
    base = json.loads((ROOT / "config" / "telegram_chokepoint_baseline.json").read_text())
    files = base.get("files", {})
    # If this ever legitimately reaches zero, delete this assertion with the manifest update.
    assert files, "baseline is empty — either migration is complete (update the manifest) or the scan broke"
    assert "scripts/telegram_transport.py" not in files, "the approved transport must not be a violation"
