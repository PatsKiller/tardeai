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
    CRITICAL_IMMEDIATE_TYPES,
    CRITICAL_OPERATIONS,
    AlertEvent,
    alert_fingerprint,
    classify_legacy_message,
    route_event,
)

# Tracked synthetic replay — never commit live Telegram audit dumps.
# The original 7-day production CSV was never in git (operator-local evidence).
FIXTURE = ROOT / "tests/fixtures/telegram_notification_normalization_replay.csv"


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


def test_a_lane_state_token_is_not_a_capital_protection_alert():
    """`ORPHANED` as a lane state token must not reach the protection channel.

    `research_lane_health` emits the lane state token `lane-registry: ORPHANED,SILENT`.
    Until 2026-09-21 the bare-substring regex classified that research-lane health report
    as `orphaned_stop` — critical, operator_action_required, PROTECTION_REPAIR. Measured
    the same day: it was the ONLY occurrence `orphaned_stop` had ever recorded, so the
    capital-protection channel's entire history was this one false positive.
    """
    lane = (
        "⚠️ *Research lane RAW-store health*\n"
        "Reads RAW stores (research rows including `[ERROR]…`). Silence is not health.\n"
        "Watched:\n  • deepseek (watched): ok=False streak=0 ok_24h=0 attempts_24h=0\n"
        "Firing:\n  • lane-registry: ORPHANED,SILENT  streak=None  (state held 50h)"
    )
    ev = classify_legacy_message(lane)
    assert ev.alert_type not in CRITICAL_IMMEDIATE_TYPES
    assert ev.alert_type == "job_telemetry"
    assert ev.operator_action_required is False
    assert ev.operator_action_type != "PROTECTION_REPAIR"


def test_genuine_protection_alerts_still_classify():
    """The guard must not become a false negative on the channel that cannot miss.

    The genuine producer shape separates the tokens ("STOP HEALTH — ORPHANED: ANET"), so
    the guard tests for stop/position anywhere in the text, never adjacency.
    """
    for msg, expected in [
        ("\U0001f6a8 STOP HEALTH — ORPHANED: ANET (fidelityrolloverira)", "orphaned_stop"),
        ("⚠️ Orphaned stop detected on AAPL — no matching position", "orphaned_stop"),
        ("\U0001f6a8 Position unprotected: MSFT has no stop", "position_unprotected"),
        ("naked position detected on TSLA", "position_unprotected"),
    ]:
        ev = classify_legacy_message(msg)
        assert ev.alert_type == expected, msg
        assert ev.alert_type in CRITICAL_IMMEDIATE_TYPES, msg
        assert ev.severity == "critical", msg
        assert ev.operator_action_required is True, msg


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


def test_csv_replay_fixture_is_tracked_synthetic():
    """Clean-checkout replay must not depend on an operator-local 7-day dump."""
    assert FIXTURE.is_file(), f"missing tracked synthetic fixture: {FIXTURE}"
    body = FIXTURE.read_text(encoding="utf-8")
    assert body.startswith("chat,text")
    assert "intent-test-1" in body
    assert "TELEGRAM_BOT_TOKEN" not in body
    assert "api.telegram.org" not in body


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
    — remaining known bypasses are tracked as a release blocker. Approved Bot API
    speakers (transport, CIO wrapper, SYSTEM ops family) are not NEW debt.
    """
    import subprocess
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_telegram_chokepoint.py")],
        capture_output=True, text=True)
    assert r.returncode == 0, f"chokepoint ratchet failed:\n{r.stdout}\n{r.stderr}"


def test_telegram_chokepoint_ratchet_reload_is_monotonic():
    """File-set ratchet is durable: a second scan on the same tree is identical.

    This is NOT a Telegram update_id / getUpdates offset cursor. The durable
    checkpoint is config/telegram_chokepoint_baseline.json. Known files may
    shrink, never grow; NEW bypassing files fail; approved speakers are skipped.
    """
    import subprocess
    cmd = [sys.executable, str(ROOT / "scripts" / "check_telegram_chokepoint.py")]
    r1 = subprocess.run(cmd, capture_output=True, text=True)
    r2 = subprocess.run(cmd, capture_output=True, text=True)
    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
    assert r1.stdout == r2.stdout
    assert "NEW bypass" not in (r1.stderr + r2.stderr)
    assert "grew " not in (r1.stderr + r2.stderr)


def test_telegram_chokepoint_baseline_is_honest():
    """Baseline may be empty after migration; approved transport must never be listed as debt."""
    import json
    import subprocess
    base = json.loads((ROOT / "config" / "telegram_chokepoint_baseline.json").read_text())
    files = base.get("files", {})
    assert "scripts/telegram_transport.py" not in files, "the approved transport must not be a violation"
    # Empty baseline is valid only when the live scan also reports zero bypasses.
    if not files:
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_telegram_chokepoint.py")],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        assert r.returncode == 0, r.stderr
        assert "zero bypasses" in (r.stdout + r.stderr).lower()



# ── an incident that can open must be able to close ─────────────────────────


def test_publish_legacy_message_threads_resolving_to_publish_event(monkeypatch):
    """The one missing link, measured 2026-09-21.

    `publish_event(event, *, resolving=False)` has always accepted the flag and
    threads it to the occurrence store, which sets resolved_at/status='resolved'
    from the dedupe decision -- and `alert_dedupe` only sets `is_resolution` when
    its caller says so. But `publish_legacy_message`, the SOLE production entry
    into that plane, called `publish_event(event)` bare.

    So every incident could open and none could ever close: 41 open, 41 distinct
    dedupe keys, 0 resolved, 0 acknowledged, oldest 2026-09-16 -- while dedupe
    itself worked correctly (occurrence counts climbing, notifications throttled).
    """
    import alert_outbox as ao

    seen = {}

    def fake_publish_event(event, *, resolving=False):
        seen["resolving"] = resolving
        return {"alert_id": "al_test", "incident_id": "inc_test"}

    monkeypatch.setattr(ao, "publish_event", fake_publish_event)

    ao.publish_legacy_message("finnhub recovered", source_producer="pytest", resolving=True)
    assert seen["resolving"] is True, "a recovery was published as a new alert"

    seen.clear()
    ao.publish_legacy_message("finnhub is down", source_producer="pytest")
    assert seen["resolving"] is False, "an ordinary alert must not resolve anything"


def test_send_telegram_carries_resolving_to_the_publish_layer(monkeypatch):
    """End of the chain: the producer's signal must survive the whole path.

    `check_data_source_health` passes `resolving=t.recovered`; that has to reach
    `publish_operator_message`, or the seam below it is unreachable in production
    and the capability exists without the behaviour -- the exact defect class
    this alert plane already demonstrated for five days.
    """
    import telegram_alert as ta

    captured = {}

    def fake_publish_operator_message(message, *, bypass_router=False, resolving=False):
        captured["resolving"] = resolving
        return {"accepted": True, "delivered": True, "route_mode": "LEGACY"}

    monkeypatch.setattr(ta, "publish_operator_message", fake_publish_operator_message)
    monkeypatch.setattr(ta, "_comms_gateway_owns", lambda mc: False)
    monkeypatch.setattr(ta, "_best_effort_comms_publish", lambda *a, **k: None)
    monkeypatch.setattr(ta, "_enabled", lambda: True, raising=False)

    ta.send_telegram("data source recovered", resolving=True)
    assert captured.get("resolving") is True, "the recovery signal was dropped in send_telegram"

    captured.clear()
    ta.send_telegram("data source is down")
    assert captured.get("resolving") is False, "a plain alert must not claim to resolve"
