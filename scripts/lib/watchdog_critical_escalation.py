"""Cron-outage watchdog CRIT -> the governed CRITICAL hub (LQ-20261113-3064, operator containment point 1).

Before this module a CRIT watchdog report reached the operator only as one Telegram P1 through ``send_telegram_outcome``.
The operator's governed critical path is ``critical_channels.deliver`` (Critical chat + email + text gateway, with the
class allowlist, the dedupe and the live-release guard). This module is the bridge: it turns a CRIT report into one
``B9_monitoring_blind`` event and hands it to that hub. It adds no sender, reads no credential and carries no address;
every address comes from the hub's own contact loader at send time.

Off by default: ``config/cron_outage_watchdog.json`` ``critical_escalation.enabled`` must be ``true``.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping

#: The hub's existing class for "the monitor cannot see". Whether a NEW class would be better is the operator's decision.
WATCHDOG_ALERT_CLASS = "B9_monitoring_blind"
# Short on purpose: the text channel is capped at 160 characters and shortens the trigger, never the action.
ACTION = "check cron wrappers and release layout"
MAX_WHAT = 70


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def escalation_key(report: Mapping[str, Any]) -> str:
    """The same named findings the Telegram path keys on; never a volatile timestamp."""
    incidents = sorted(str(x.get("id")) for x in report.get("monitor_incidents") or [] if isinstance(x, dict))
    missed = sorted(str(x) for x in report.get("missed_lane_ids") or [])
    return hashlib.sha256(json.dumps({"missed": missed, "monitor": incidents}, sort_keys=True).encode()).hexdigest()[:16]


def escalation_event(report: Mapping[str, Any], *, test: bool = False) -> dict[str, Any] | None:
    """One hub event for a CRIT report, or None when the report is not CRIT (and this is not a test)."""
    if not test and report.get("status") != "CRIT":
        return None
    incidents = [str(x.get("id")) for x in report.get("monitor_incidents") or [] if isinstance(x, dict)]
    missed = [str(x) for x in report.get("missed_lane_ids") or []]
    parts: list[str] = []
    if incidents:
        parts.append(", ".join(sorted(incidents)))
    if missed:
        parts.append(f"{len(missed)} lane(s) missed")
    if report.get("alert_delivery_status") == "FAILED_OR_UNCONFIRMED":
        parts.append("alert unconfirmed")
    what = _clean("cron watchdog CRIT: " + ("; ".join(parts) or "status CRIT"))[:MAX_WHAT]
    key = escalation_key(report)
    if test:
        what = "TEST ONLY: " + what
    return {
        "alert_class": WATCHDOG_ALERT_CLASS,
        "symbol": "", "account": "",
        "what": what, "trigger": what, "action": ACTION,
        "evidence": {"incidents": incidents, "missed_lane_ids": missed, "observed_at": report.get("observed_at")},
        # The text primitive dedupes on this; a test gets its own so it cannot be eaten by, or eat, a real CRIT.
        "event_id": ("watchdog-test-" if test else "watchdog-crit-") + key,
    }


def escalate(report: Mapping[str, Any], *, deliver: Callable[..., Any] | None = None, test: bool = False,
             **hub_kwargs: Any) -> dict[str, Any]:
    """Fan one CRIT report to text + Telegram + email through the hub. Never raises; the receipt says what happened."""
    event = escalation_event(report, test=test)
    if event is None:
        return {"status": "NOT_CRIT", "delivered": False, "event": None, "receipts": []}
    try:
        if deliver is None:
            from scripts.lib import critical_channels  # noqa: PLC0415 - resolved at call time; the hub is the only sender
            deliver = critical_channels.deliver
        delivery = deliver(event, **hub_kwargs)
        doc = delivery.as_dict()
    except Exception as exc:  # noqa: BLE001 - an escalation fault must never take the watchdog down
        return {"status": "ESCALATION_ERROR", "delivered": False, "event": event, "receipts": [],
                "reason": type(exc).__name__}
    return {"status": "SENT" if doc.get("delivered") else "NOT_CONFIRMED", "delivered": bool(doc.get("delivered")),
            "event": event, "receipts": doc.get("receipts") or []}


def enabled(cfg: Mapping[str, Any]) -> bool:
    block = cfg.get("critical_escalation")
    return isinstance(block, dict) and block.get("enabled") is True


def escalate_if_due(report: Mapping[str, Any], cfg: Mapping[str, Any], prior: dict, *, now_iso: str,
                    now_epoch: float, **kwargs: Any) -> tuple[dict[str, Any], dict]:
    """The watchdog's hook. Never raises (review 3064 F3): a fault in config, key or state is a receipt, not a crash."""
    try:
        return _escalate_if_due(report, cfg, prior, now_iso=now_iso, now_epoch=now_epoch, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the watchdog must keep running and keep alerting on Telegram
        return {"status": "ESCALATION_ERROR", "delivered": False, "reason": type(exc).__name__}, prior


def _escalate_if_due(report: Mapping[str, Any], cfg: Mapping[str, Any], prior: dict, *, now_iso: str,
                     now_epoch: float, **kwargs: Any) -> tuple[dict[str, Any], dict]:
    """Escalates once per finding key per ``reminder_seconds`` while CRIT stays up.

    Due-ness is this module's OWN state (review 3064 F1), not the Telegram P1's gate: after a confirmed Telegram the P1 is
    NOT_REQUIRED for ``reminder_seconds``, and keying on it would leave a failed text/email/chat unretried for that long.
    The key and time are stored only after a confirmed delivery, so an unconfirmed escalation is retried every tick.
    """
    if not enabled(cfg):
        return {"status": "DISABLED", "delivered": False}, prior
    if report.get("status") != "CRIT":
        return {"status": "NOT_REQUIRED", "delivered": False}, prior
    key = escalation_key(report)
    reminder = int(cfg.get("reminder_seconds", 1800))
    last = prior.get("critical_escalated_epoch")
    if prior.get("critical_escalation_key") == key and isinstance(last, (int, float)) and now_epoch - last < reminder:
        return {"status": "NOT_REQUIRED", "delivered": False, "reason": "reminder_window"}, prior
    result = escalate(report, **kwargs)
    state = dict(prior)
    if result["delivered"]:
        state.update(critical_escalation_key=key, critical_escalated_epoch=now_epoch, critical_escalated_at=now_iso)
    result.pop("event", None)  # the report carries the receipts, not the sentence
    return result, state
