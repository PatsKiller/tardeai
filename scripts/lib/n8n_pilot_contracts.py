"""Shadow contracts for the five coordination pilots.

Each function asks the coordination gateway to accept an event, then applies
the lane rule. Nothing here opens a socket, sends mail or Telegram, writes a
production ledger, calls a model, or invokes the detector and notifier.
A crontab command line is not a consumer receipt.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from scripts.lib.n8n_coordination_gateway import handle_request

PILOT_IDS = (
    "morning-brief-0730",
    "research-scheduler-holdings",
    "material-change-digest",
    "llm-spend-report-daily",
    "approval-package-reminder",
)


def evaluate_pilot(
    pilot_id: str,
    *,
    request: Mapping[str, Any],
    observation: Mapping[str, Any],
    key: bytes,
    now: datetime,
    nonce_store: dict[str, float],
    idempotency_store: dict[str, dict[str, Any]],
    expected_origin_sha: str,
) -> dict[str, Any]:
    if pilot_id not in PILOT_IDS:
        return _blocked(pilot_id, "unknown_pilot")
    if observation.get("send"):
        return _blocked(pilot_id, "send_blocked")
    if observation.get("provider_charge_requested"):
        return _blocked(pilot_id, "provider_charge_blocked")
    accepted = handle_request(
        request,
        key=key,
        now=now,
        nonce_store=nonce_store,
        idempotency_store=idempotency_store,
        expected_origin_sha=expected_origin_sha,
    )
    if accepted.get("state") == "REFUSED":
        return _from_gateway(pilot_id, accepted)
    event = request.get("event") if isinstance(request.get("event"), Mapping) else {}
    if event.get("lane_id") != pilot_id:
        return _blocked(pilot_id, "lane_mismatch")
    checker = {
        "morning-brief-0730": _morning_brief,
        "research-scheduler-holdings": _holdings,
        "material-change-digest": _material_digest,
        "llm-spend-report-daily": _llm_spend,
        "approval-package-reminder": _approval,
    }[pilot_id]
    verdict = checker(observation)
    if verdict["state"] == "REFUSED":
        return _blocked(pilot_id, verdict["reason"], gateway_state=accepted["state"])
    return {
        "schema": "N8nPilotContract@v1",
        "pilot_id": pilot_id,
        "state": verdict["state"],
        "reason": verdict["reason"],
        "gateway_state": accepted["state"],
        "consumed": verdict["state"] == "CONSUMED",
        "effects": [],
        "outbound": "blocked",
        "mutation": "blocked",
        "durable": False,
        "command_line_is_receipt": False,
    }


def _morning_brief(observation: Mapping[str, Any]) -> dict[str, str]:
    if _has_consumer(observation):
        return {"state": "CONSUMED", "reason": None}
    return {"state": "ARTIFACT_WRITTEN", "reason": "command_line_is_not_a_receipt"}


def _holdings(observation: Mapping[str, Any]) -> dict[str, str]:
    if observation.get("mode") != "holdings":
        return {"state": "REFUSED", "reason": "shared_ledger_not_mode_proof"}
    if observation.get("hermes_run_id"):
        if _has_consumer(observation):
            return {"state": "CONSUMED", "reason": None}
        return {"state": "ARTIFACT_WRITTEN", "reason": "no_consumer_receipt"}
    refusal = observation.get("typed_refusal")
    if isinstance(refusal, Mapping) and refusal.get("code") and refusal.get("reason"):
        return {"state": "REFUSED", "reason": f"typed_refusal:{refusal['code']}"}
    return {"state": "REFUSED", "reason": "missing_hermes_run_or_refusal"}


def _material_digest(observation: Mapping[str, Any]) -> dict[str, str]:
    if observation.get("muted") is not True:
        return {"state": "REFUSED", "reason": "live_notifier_stays_in_code"}
    if not observation.get("detector_event_id"):
        return {"state": "REFUSED", "reason": "missing_detector_event"}
    if "suppression" not in observation:
        return {"state": "REFUSED", "reason": "missing_suppression"}
    if _has_consumer(observation):
        return {"state": "CONSUMED", "reason": None}
    return {"state": "ARTIFACT_WRITTEN", "reason": "no_consumer_receipt"}


def _llm_spend(observation: Mapping[str, Any]) -> dict[str, str]:
    if observation.get("provider_charge_requested"):
        return {"state": "REFUSED", "reason": "provider_charge_blocked"}
    if observation.get("period") != "daily":
        return {"state": "REFUSED", "reason": "not_daily_digest"}
    amount = observation.get("amount_usd")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return {"state": "REFUSED", "reason": "missing_caller_cost"}
    if _has_consumer(observation):
        return {"state": "CONSUMED", "reason": None}
    return {"state": "ARTIFACT_WRITTEN", "reason": "no_consumer_receipt"}


def _approval(observation: Mapping[str, Any]) -> dict[str, str]:
    signal = str(observation.get("signal") or "")
    if signal.endswith("approval_packages.jsonl") or observation.get("signal_kind") == "ledger_mtime":
        if not observation.get("run_receipt"):
            return {"state": "REFUSED", "reason": "wrong_signal"}
    if not observation.get("run_receipt"):
        return {"state": "REFUSED", "reason": "missing_run_receipt"}
    if _has_consumer(observation):
        return {"state": "CONSUMED", "reason": None}
    return {"state": "ARTIFACT_WRITTEN", "reason": "no_consumer_receipt"}


def _has_consumer(observation: Mapping[str, Any]) -> bool:
    ack = observation.get("consumer_receipt")
    return isinstance(ack, Mapping) and bool(ack.get("consumer")) and bool(ack.get("receipt_id"))


def _blocked(pilot_id: str, reason: str, *, gateway_state: str | None = None) -> dict[str, Any]:
    return {
        "schema": "N8nPilotContract@v1",
        "pilot_id": pilot_id,
        "state": "REFUSED",
        "reason": reason,
        "gateway_state": gateway_state,
        "consumed": False,
        "effects": [],
        "outbound": "blocked",
        "mutation": "blocked",
        "durable": False,
        "command_line_is_receipt": False,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def _from_gateway(pilot_id: str, accepted: Mapping[str, Any]) -> dict[str, Any]:
    out = _blocked(pilot_id, str(accepted.get("reason") or "refused"), gateway_state="REFUSED")
    out["event_id"] = accepted.get("event_id")
    return out
