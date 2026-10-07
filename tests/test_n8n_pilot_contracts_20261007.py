"""The five pilot contracts stay unable to send. Observations are fixtures."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.lib.n8n_coordination_gateway import sign_claim
from scripts.lib.n8n_pilot_contracts import evaluate_pilot

KEY = b"pilot-contract-key-not-a-live-secret"
SHA = "18a27ff288894c4e428151d5f385e68522ecd47b"
NOW = datetime(2026, 10, 7, 1, 30, tzinfo=timezone.utc)


def _request(lane: str, nonce: str) -> dict:
    claim = {
        "v": 1,
        "caller_id": "n8n-lab",
        "project": "trade-ai",
        "iat": NOW.timestamp(),
        "exp": (NOW + timedelta(seconds=90)).timestamp(),
        "nonce": nonce,
        "scope": "coordination_read",
    }
    event = {
        "event_id": "evt-" + lane[:12],
        "source_project": "trade-ai",
        "lane_id": lane,
        "schema_version": "event-reference/v0",
        "origin_sha": SHA,
        "subject_key": lane,
        "source_timestamp": "2026-10-07T11:30:00+00:00",
        "deadline": "2026-10-07T16:00:00+00:00",
        "artifact_ref": "fixture/" + lane,
        "authority_class": "coordination_read",
        "correlation_id": "corr-" + nonce,
        "idempotency_key": "idem-" + nonce,
    }
    return {
        "route": "coordination/event",
        "operation": "accept_event",
        "claim": claim,
        "signature": sign_claim(claim, KEY),
        "event": event,
    }


def _eval(lane: str, observation: dict, nonce: str) -> dict:
    return evaluate_pilot(
        lane,
        request=_request(lane, nonce),
        observation=observation,
        key=KEY,
        now=NOW,
        nonce_store={},
        idempotency_store={},
        expected_origin_sha=SHA,
    )


def test_morning_brief_command_line_is_not_a_receipt():
    refused_send = _eval("morning-brief-0730", {"send": True, "syslog_cmd_lines": 5}, "mb-send")
    assert refused_send["reason"] == "send_blocked"
    assert refused_send["consumed"] is False
    quiet = _eval("morning-brief-0730", {"syslog_cmd_lines": 5}, "mb-quiet")
    assert quiet["state"] == "ARTIFACT_WRITTEN"
    assert quiet["reason"] == "command_line_is_not_a_receipt"
    assert quiet["consumed"] is False
    assert quiet["outbound"] == "blocked"


def test_holdings_requires_mode_and_a_run_or_refusal():
    shared = _eval("research-scheduler-holdings", {"mode": "watch", "ledger_age_hours": 0.2}, "hold0001")
    assert shared["reason"] == "shared_ledger_not_mode_proof"
    missing = _eval("research-scheduler-holdings", {"mode": "holdings"}, "hold0002")
    assert missing["reason"] == "missing_hermes_run_or_refusal"
    refused = _eval(
        "research-scheduler-holdings",
        {"mode": "holdings", "typed_refusal": {"code": "no_run", "reason": "fixture"}},
        "hold0003",
    )
    assert refused["reason"] == "typed_refusal:no_run"
    handed = _eval("research-scheduler-holdings", {"mode": "holdings", "hermes_run_id": "hr-1"}, "hold0004")
    assert handed["state"] == "ARTIFACT_WRITTEN"
    assert handed["reason"] == "no_consumer_receipt"


def test_material_digest_leaves_the_notifier_in_code():
    live = _eval(
        "material-change-digest",
        {"muted": False, "detector_event_id": "det-1", "suppression": "none"},
        "matd0001",
    )
    assert live["reason"] == "live_notifier_stays_in_code"
    muted = _eval(
        "material-change-digest",
        {"muted": True, "detector_event_id": "det-1", "suppression": "digest"},
        "matd0002",
    )
    assert muted["state"] == "ARTIFACT_WRITTEN"
    assert muted["mutation"] == "blocked"


def test_llm_spend_does_not_charge_a_provider():
    charged = _eval("llm-spend-report-daily", {"period": "daily", "amount_usd": 1.2, "provider_charge_requested": True}, "ll-0001")
    assert charged["reason"] == "provider_charge_blocked"
    missing = _eval("llm-spend-report-daily", {"period": "daily"}, "llm00002")
    assert missing["reason"] == "missing_caller_cost"
    daily = _eval("llm-spend-report-daily", {"period": "daily", "amount_usd": 0.4}, "llm00003")
    assert daily["state"] == "ARTIFACT_WRITTEN"
    assert daily["effects"] == []


def test_approval_refuses_the_ledger_mtime_until_a_run_receipt_exists():
    wrong = _eval(
        "approval-package-reminder",
        {"signal": "data/governance/approval_packages.jsonl", "signal_kind": "ledger_mtime", "syslog_cmd_lines": 168},
        "appr0001",
    )
    assert wrong["reason"] == "wrong_signal"
    assert wrong["consumed"] is False
    receipt = _eval(
        "approval-package-reminder",
        {"signal": "data/governance/approval_packages.jsonl", "run_receipt": {"actions": 0, "sent": False}},
        "appr0002",
    )
    assert receipt["state"] == "ARTIFACT_WRITTEN"
    assert receipt["reason"] == "no_consumer_receipt"
    sent = _eval("approval-package-reminder", {"send": True, "run_receipt": {"actions": 1}}, "ap-0003")
    assert sent["reason"] == "send_blocked"
