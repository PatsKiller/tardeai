#!/usr/bin/env python3
"""Typed operator-alert policy for Telegram notification normalization.

Pure functions only: no broker calls, no order writes, no 2FA, no secrets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any

POLICY_VERSION = "operator-alert-policy-v2-2026-07-28"

CRITICAL_OPERATIONS = "CRITICAL_OPERATIONS"
APPROVALS_ONLY = "APPROVALS_ONLY"

ROUTE_IMMEDIATE = "IMMEDIATE"
ROUTE_DIGEST = "DIGEST"
ROUTE_COMMAND_CENTER = "COMMAND_CENTER"
ROUTE_LOG = "LOG"

APPROVAL_ALLOWLIST = {
    "live_order_2fa_required",
    "live_session_2fa_required",
    "protective_order_approval_required",
    "material_live_authorization_amendment_required",
}

CRITICAL_IMMEDIATE_TYPES = {
    "orphaned_stop",
    "position_unprotected",
    "protection_failure",
    "protection_uncertain",
    "broker_auth_blocking",
    "partial_fill_protection_uncertain",
    "flatten_failed_or_uncertain",
    "emergency_kill_or_revoke",
    "trading_impact_outage",
    "market_hours_stop_unresolved",
}

PAPER_OR_CANDIDATE_TYPES = {
    "paper_proposal",
    "paper_approval",
    "proposal_blocked_or_rebuild",
    "proposal_revalidated_or_cancelled",
    "research_update",
    "scanner_candidate",
    "entry_candidate",
    "stop_warning",
    "siem_without_trading_impact",
    "job_telemetry",
    "debug_or_success",
}


@dataclass(frozen=True)
class AlertEvent:
    alert_type: str
    source_system: str
    source_producer: str
    entity_id: str | None = None
    account_id: str | None = None
    symbol: str | None = None
    severity: str = "info"
    operator_action_required: bool = False
    operator_action_type: str | None = None
    state_version: str = "1"
    authorization_or_order_id: str | None = None
    session_ref: str | None = None
    order_ref: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True)
class RoutingDecision:
    route_mode: str
    logical_destination: str | None
    digest_bucket: str | None
    ttl_seconds: int
    dedupe_window_seconds: int
    escalate_after_seconds: int | None
    suppression_reason: str | None = None
    policy_version: str = POLICY_VERSION


DEFAULT_TTLS = {
    "scanner_candidate": 4 * 3600,
    "entry_candidate": 4 * 3600,
    "paper_proposal": 7 * 86400,
    "paper_approval": 7 * 86400,
    "proposal_blocked_or_rebuild": 7 * 86400,
    "proposal_revalidated_or_cancelled": 24 * 3600,
    "research_update": 7 * 86400,
    "stop_warning": 24 * 3600,
    "debug_or_success": 7 * 86400,
}


def alert_fingerprint(event: AlertEvent) -> str:
    parts = [
        event.alert_type,
        event.source_system,
        event.entity_id or "",
        event.account_id or "",
        (event.symbol or "").upper(),
        event.state_version or "1",
        "action" if event.operator_action_required else "no_action",
        event.authorization_or_order_id or event.order_ref or "",
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def incident_id_for(event: AlertEvent) -> str:
    key_parts = [
        event.alert_type,
        event.source_system,
        event.account_id or "",
        (event.symbol or "") if event.alert_type not in {"orphaned_stop"} else "batched",
        event.authorization_or_order_id or "",
    ]
    return hashlib.sha256("|".join(key_parts).encode("utf-8")).hexdigest()[:20]


def route_event(event: AlertEvent) -> RoutingDecision:
    atype = event.alert_type
    if atype in APPROVAL_ALLOWLIST:
        if not event.operator_action_required or not (event.authorization_or_order_id or event.session_ref or event.order_ref):
            return RoutingDecision(
                route_mode=ROUTE_COMMAND_CENTER,
                logical_destination=None,
                digest_bucket=None,
                ttl_seconds=900,
                dedupe_window_seconds=300,
                escalate_after_seconds=None,
                suppression_reason="approval_channel_requires_explicit_live_authorization",
            )
        return RoutingDecision(ROUTE_IMMEDIATE, APPROVALS_ONLY, None, 900, 300, 600)

    if atype in CRITICAL_IMMEDIATE_TYPES:
        if atype in {"position_unprotected", "protection_failure", "protection_uncertain", "orphaned_stop"}:
            return RoutingDecision(ROUTE_IMMEDIATE, CRITICAL_OPERATIONS, None, 24 * 3600, 900, 1800)
        if event.operator_action_required or event.severity.lower() in {"critical", "urgent"}:
            return RoutingDecision(ROUTE_IMMEDIATE, CRITICAL_OPERATIONS, None, 24 * 3600, 900, 1800)
        return RoutingDecision(ROUTE_DIGEST, None, "OPS", 24 * 3600, 1800, 3600)

    if atype in {"stop_near_trigger", "stop_trigger_non_rth", "stop_warning"}:
        return RoutingDecision(ROUTE_DIGEST, None, "RISK", 24 * 3600, 3600, None)
    if atype in {"proposal_revalidated_or_cancelled"}:
        return RoutingDecision(ROUTE_DIGEST, None, "TRADING", 24 * 3600, 3600, None)
    if atype == "material_change":
        # A tracked name behaving unlike ITSELF — AOUT at 14.9x its own average daily
        # move on 2026-09-04, which the operator saw on the movers board and was never
        # told about. Same shape as thesis_update and for the same reason: immediate,
        # general channel, deduped on the hour.
        #
        # Deliberately NOT in CRITICAL_IMMEDIATE_TYPES. That set is capital at risk
        # right now — orphaned stops, protection failures, broker auth. A price move is
        # not that, and diluting the critical set is how a critical channel stops being
        # read. But DIGEST made it arrive hours later, which for a 45% move is the same
        # as not arriving at all.
        return RoutingDecision(ROUTE_IMMEDIATE, CRITICAL_OPERATIONS, None, 24 * 3600, 3600, None)
    if atype == "thesis_update":
        # A material thesis change is the one piece the operator wants as text (not
        # noise). Immediate to the general channel; deduped on the 60-min window.
        return RoutingDecision(ROUTE_IMMEDIATE, CRITICAL_OPERATIONS, None, 24 * 3600, 3600, None)
    if atype in {"siem_without_trading_impact", "system_health", "job_telemetry"}:
        return RoutingDecision(ROUTE_DIGEST, None, "OPS", DEFAULT_TTLS.get(atype, 7 * 86400), 3600, None)
    if atype in {"debug_or_success"}:
        return RoutingDecision(ROUTE_LOG, None, None, DEFAULT_TTLS[atype], 3600, None)
    if atype in PAPER_OR_CANDIDATE_TYPES:
        return RoutingDecision(ROUTE_COMMAND_CENTER, None, None, DEFAULT_TTLS.get(atype, 7 * 86400), 3600, None)
    return RoutingDecision(ROUTE_COMMAND_CENTER, None, None, 7 * 86400, 3600, None)


def expires_at_for(event: AlertEvent, decision: RoutingDecision) -> datetime:
    created = event.created_at or datetime.now(timezone.utc)
    return created + timedelta(seconds=decision.ttl_seconds)


def alert_id_for(fingerprint: str) -> str:
    return f"al_{fingerprint[:24]}"


def classify_legacy_message(message: str, *, source_producer: str = "legacy_send_telegram") -> AlertEvent:
    """Compatibility classifier for old string producers.

    Runtime producers should prefer AlertEvent fields. This shim deliberately avoids
    promoting paper/proposal text to approval authority.
    """
    text = message or ""
    low = text.lower()
    symbol = None
    m = re.search(r"\b(?:symbol[:\s]+|new go\s*[—-]\s*|proposal #\d+:\s*|stop(?:_triggered)?\s*[—-]\s*)([A-Z]{1,6})\b", text, re.I)
    if m:
        symbol = m.group(1).upper()

    payload = {"message": text}

    def ev(alert_type: str, severity: str = "info", action: bool = False, action_type: str | None = None) -> AlertEvent:
        entity = symbol or hashlib.sha256(text[:200].encode("utf-8")).hexdigest()[:16]
        account_id = None
        acct_m = re.search(r"\b((?:schwab|fidelity|alpaca)[A-Za-z0-9_-]+)\b", text, re.I)
        if acct_m:
            account_id = acct_m.group(1).lower()
        auth = None
        auth_m = re.search(r"\b(?:intent|authorization|session|order)(?:[ _-]?id)?[:=#\s]+([A-Za-z0-9_.:-]+)", text, re.I)
        if auth_m:
            auth = auth_m.group(1)
        return AlertEvent(
            alert_type=alert_type,
            source_system="telegram_legacy",
            source_producer=source_producer,
            entity_id=entity,
            account_id=account_id,
            symbol=symbol,
            severity=severity,
            operator_action_required=action,
            operator_action_type=action_type,
            authorization_or_order_id=auth,
            payload=payload,
        )

    if re.search(r"\blive (?:order )?2fa\b|2fa required.*live order|live order.*approval required", text, re.I):
        return ev("live_order_2fa_required", "critical", True, "LIVE_ORDER_2FA")
    if re.search(r"\blive session\b.*\b2fa\b|session authorization.*required", text, re.I):
        return ev("live_session_2fa_required", "critical", True, "LIVE_SESSION_2FA")
    if re.search(r"stop approved by|approved by", text, re.I):
        return ev("job_telemetry", "info")
    if re.search(r"protective|trailing stop", text, re.I) and re.search(r"approval required|operator approval|2fa|2nd factor|live stop enabled", text, re.I) and "paper" not in low:
        return ev("protective_order_approval_required", "critical", True, "PROTECTIVE_ORDER_APPROVAL")
    if re.search(r"material.*authorization.*amendment|amend.*live.*authorization", text, re.I):
        return ev("material_live_authorization_amendment_required", "critical", True, "LIVE_AUTH_AMENDMENT")

    if "paper proposal" in low or re.search(r"trade proposal #\d+", low):
        return ev("paper_proposal", "info")
    if re.search(r"proposal.*(?:blocked|rebuild|watch|expired|stale|revalidated|cancelled|canceled|rejected|deferred)", text, re.I):
        return ev("proposal_blocked_or_rebuild", "info")
    # MaterialChangeNotice@v1 renders this exact header. Matched BEFORE the
    # research_update branches, which route to DIGEST and swallowed the first live
    # alert into the 8pm digest queue instead of sending it.
    if "material change \u2014" in low or "x its normal daily move" in low:
        return ev("material_change", "info")
    if re.search(r"research update|holding research|analyst report|catalyst research", text, re.I):
        return ev("research_update", "info")
    if re.search(r"hermes watchlist|rank-only|watchlist alerts", text, re.I):
        return ev("research_update", "info")
    if re.search(r"investigating \d+ escalation|topic curator|incubator promoter|trade ai critique", text, re.I):
        return ev("research_update", "info")
    if re.search(r"\bthesis\b.*\b(?:updated|version|published|changed)\b|\bdesk@v\d+\b", text, re.I):
        return ev("thesis_update", "info")
    if re.search(r"\b(?:new go|wait|avoid|entry alert|entry candidate|scanner|social scalp setup|trade ai live)\b", text, re.I):
        return ev("scanner_candidate", "info")
    if re.search(r"orphan(?:ed|s)|naked .*position|position.*unprotected|unprotected live position", text, re.I):
        return ev("orphaned_stop" if "orphan" in low else "position_unprotected", "critical", True, "PROTECTION_REPAIR")
    if re.search(r"protection.*(?:failed|uncertain)|stop.*placement.*(?:failed|uncertain)", text, re.I):
        return ev("protection_failure", "critical", True, "PROTECTION_REPAIR")
    if re.search(r"broker.*auth.*(?:fail|expired|blocking)|re.auth.*fail", text, re.I):
        return ev("broker_auth_blocking", "critical", True, "BROKER_AUTH_REPAIR")
    if re.search(r"partial fill.*protection.*uncertain", text, re.I):
        return ev("partial_fill_protection_uncertain", "critical", True, "PROTECTION_REPAIR")
    if re.search(r"flatten.*(?:failed|uncertain)", text, re.I):
        return ev("flatten_failed_or_uncertain", "critical", True, "FLATTEN_REVIEW")
    if not re.search(r"health agent|system health", text, re.I) and re.search(r"kill.?switch|emergency kill|revoke", text, re.I):
        return ev("emergency_kill_or_revoke", "critical", True, "KILL_REVIEW")
    if re.search(r"siem\s+p[01]", text, re.I):
        if "paper_execution" not in low and re.search(r"live position|live session|protection|trading impact", text, re.I):
            return ev("trading_impact_outage", "critical", True, "OUTAGE_REVIEW")
        return ev("siem_without_trading_impact", "warning")
    if re.search(r"health agent:\s*degraded", text, re.I):
        return ev("research_update", "info")
    if re.search(r"stop.*(?:near|warning|after.?hours|pre.?market)|near.?stop", text, re.I):
        return ev("stop_warning", "warning")
    if re.search(r"debug|cron success|sync success|uploaded unchanged", text, re.I):
        return ev("debug_or_success", "info")
    if re.search(r"health|pipeline|reaper|job|output_invalid|retry_exhausted|locktimeout", text, re.I):
        return ev("job_telemetry", "warning")
    return ev("job_telemetry", "info")


def render_operator_message(event: AlertEvent, alert_id: str) -> str:
    from notification_url_builder import build_alert_url, build_dashboard_url, sanitize_operator_message

    title = event.alert_type.replace("_", " ").title()
    symbol = f" {event.symbol}" if event.symbol else ""
    action = "Action required" if event.operator_action_required else "No immediate action"
    link = build_alert_url(alert_id) if alert_id else build_dashboard_url("/v3/reports")
    lines = [
        f"{title}{symbol}",
        f"Severity: {event.severity.upper()} · {action}",
    ]
    if event.operator_action_type:
        lines.append(f"Action type: {event.operator_action_type}")
    msg = event.payload.get("message")
    if msg:
        lines.append("")
        lines.append(str(msg)[:1200])
    lines.append("")
    lines.append(link)
    return sanitize_operator_message("\n".join(lines))[0]


def event_to_jsonable(event: AlertEvent) -> dict[str, Any]:
    data = event.__dict__.copy()
    if isinstance(data.get("created_at"), datetime):
        data["created_at"] = data["created_at"].isoformat()
    return json.loads(json.dumps(data, default=str))
