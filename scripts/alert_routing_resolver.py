#!/usr/bin/env python3
"""Server-authoritative routing resolver.

ONE place decides where an alert goes. It composes four layers, in this order:

    1. immutable safety invariants   (never overridable, applied last as a veto)
    2. default policy                (operator_alert_policy_v2.route_event)
    3. current versioned DB preference (operator_alert_preferences)
    4. runtime mode                  (OFF / SHADOW / ACTIVE)

Preferences are data, not authority: a preference row can widen or narrow delivery
within the invariants, but it can never grant approval-channel access to a paper
alert, silence a live protection failure everywhere, or name a chat ID. Chat IDs and
tokens are resolved from the environment by the delivery layer and are never read
from, written to, or accepted in a preference row.

Pure and injectable: pass `preferences` and `mode` to test without a database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from operator_alert_policy_v2 import (
    APPROVALS_ONLY,
    APPROVAL_ALLOWLIST,
    CRITICAL_IMMEDIATE_TYPES,
    CRITICAL_OPERATIONS,
    PAPER_OR_CANDIDATE_TYPES,
    POLICY_VERSION,
    ROUTE_COMMAND_CENTER,
    ROUTE_DIGEST,
    ROUTE_IMMEDIATE,
    ROUTE_LOG,
    AlertEvent,
    route_event,
)

# Keys a preference row may influence. Anything resembling a secret or a transport
# address is absent on purpose and is stripped if it somehow appears.
PREFERENCE_FIELDS = (
    "general_telegram", "approval_telegram", "command_center", "digest_bucket",
    "ttl_seconds", "dedupe_window_seconds", "escalate_after_seconds", "sound_enabled",
)
FORBIDDEN_PREFERENCE_FIELDS = (
    "chat_id", "thread_id", "token", "bot_token", "secret", "secret_ref", "webhook",
    "url", "endpoint", "recipient",
)

PREF_OFF = "OFF"
PREF_IMMEDIATE = "IMMEDIATE"
PREF_DIGEST = "DIGEST"

# Invariant identifiers, surfaced to the UI and asserted by tests.
INV_PAPER_NOT_APPROVALS = "paper_candidate_types_cannot_route_to_approvals"
INV_APPROVALS_ALLOWLIST = "approval_channel_requires_allowlisted_type"
INV_APPROVALS_NEEDS_AUTH = "approval_channel_requires_explicit_live_authorization"
INV_PROTECTION_ALWAYS_VISIBLE = "live_protection_failures_cannot_be_disabled_from_every_surface"
INV_NO_SECRETS_IN_PREFS = "preferences_must_not_carry_secrets_or_chat_ids"

# Live protection classes that must always reach the operator somewhere.
PROTECTION_TYPES = {
    "orphaned_stop", "position_unprotected", "protection_failure",
    "protection_uncertain", "partial_fill_protection_uncertain",
}


@dataclass(frozen=True)
class ResolvedRoute:
    route_mode: str
    logical_destination: str | None
    digest_bucket: str | None
    ttl_seconds: int
    dedupe_window_seconds: int
    escalate_after_seconds: int | None
    sound_enabled: bool = False
    suppression_reason: str | None = None
    invariant_violations: tuple[str, ...] = ()
    applied_preference: bool = False
    preference_row_version: int | None = None
    runtime_mode: str = "OFF"
    delivery_allowed: bool = False
    policy_version: str = POLICY_VERSION
    sources: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["invariant_violations"] = list(self.invariant_violations)
        return d


def sanitize_preference(row: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Keep only routing fields; report any secret-ish key found."""
    if not row:
        return {}, []
    violations: list[str] = []
    lowered = {str(k).lower() for k in row.keys()}
    if any(any(bad in k for bad in FORBIDDEN_PREFERENCE_FIELDS) for k in lowered):
        violations.append(INV_NO_SECRETS_IN_PREFS)
    clean = {k: row[k] for k in PREFERENCE_FIELDS if k in row}
    return clean, violations


def _approval_authorized(event: AlertEvent) -> bool:
    return bool(
        event.operator_action_required
        and (event.authorization_or_order_id or event.session_ref or event.order_ref)
    )


def resolve_route(
    event: AlertEvent,
    *,
    preferences: dict[str, Any] | None = None,
    mode: str | None = None,
) -> ResolvedRoute:
    """Resolve the authoritative route for one event."""
    from alert_runtime_mode import MODE_ACTIVE, get_mode

    runtime_mode = (mode or get_mode()).upper()
    base = route_event(event)
    atype = event.alert_type

    pref, violations = sanitize_preference(preferences)
    applied = bool(pref)
    row_version = None
    if preferences and "row_version" in preferences:
        try:
            row_version = int(preferences["row_version"])
        except (TypeError, ValueError):
            row_version = None

    route_mode = base.route_mode
    destination = base.logical_destination
    bucket = base.digest_bucket
    ttl = base.ttl_seconds
    dedupe = base.dedupe_window_seconds
    escalate = base.escalate_after_seconds
    sound = False
    suppression = base.suppression_reason
    sources: dict[str, Any] = {"route_mode": "default_policy"}

    if applied:
        general = str(pref.get("general_telegram", PREF_OFF) or PREF_OFF).upper()
        approval = str(pref.get("approval_telegram", PREF_OFF) or PREF_OFF).upper()
        command_center = bool(pref.get("command_center", True))
        sound = bool(pref.get("sound_enabled", False))

        if pref.get("digest_bucket"):
            bucket_pref = str(pref["digest_bucket"]).upper()
            if bucket_pref in {"RISK", "TRADING", "OPS"}:
                bucket = bucket_pref
                sources["digest_bucket"] = "preference"
        for key, setter in (("ttl_seconds", "ttl"), ("dedupe_window_seconds", "dedupe"),
                            ("escalate_after_seconds", "escalate")):
            if pref.get(key) is not None:
                try:
                    val = int(pref[key])
                except (TypeError, ValueError):
                    continue
                if setter == "ttl":
                    ttl = val
                elif setter == "dedupe":
                    dedupe = val
                else:
                    escalate = val
                sources[key] = "preference"

        # The preference decides the surface. Approval channel wins over general when
        # both are enabled, because it is the narrower, authorization-bound channel.
        if approval == PREF_IMMEDIATE:
            route_mode, destination = ROUTE_IMMEDIATE, APPROVALS_ONLY
            sources["route_mode"] = "preference:approval_telegram"
        elif general == PREF_IMMEDIATE:
            route_mode, destination = ROUTE_IMMEDIATE, CRITICAL_OPERATIONS
            sources["route_mode"] = "preference:general_telegram"
        elif general == PREF_DIGEST or approval == PREF_DIGEST:
            route_mode, destination = ROUTE_DIGEST, None
            bucket = bucket or "OPS"
            sources["route_mode"] = "preference:digest"
        elif command_center:
            route_mode, destination = ROUTE_COMMAND_CENTER, None
            sources["route_mode"] = "preference:command_center"
        else:
            route_mode, destination = ROUTE_LOG, None
            sources["route_mode"] = "preference:log_only"

    # ── Immutable invariants — applied AFTER preferences so they cannot be traded away
    if destination == APPROVALS_ONLY:
        if atype in PAPER_OR_CANDIDATE_TYPES:
            violations.append(INV_PAPER_NOT_APPROVALS)
            route_mode, destination = ROUTE_COMMAND_CENTER, None
            suppression = INV_PAPER_NOT_APPROVALS
        elif atype not in APPROVAL_ALLOWLIST:
            violations.append(INV_APPROVALS_ALLOWLIST)
            route_mode, destination = ROUTE_COMMAND_CENTER, None
            suppression = INV_APPROVALS_ALLOWLIST
        elif not _approval_authorized(event):
            violations.append(INV_APPROVALS_NEEDS_AUTH)
            route_mode, destination = ROUTE_COMMAND_CENTER, None
            suppression = INV_APPROVALS_NEEDS_AUTH

    # A live protection failure must remain visible on at least one surface. LOG is
    # not a surface — it is the absence of one.
    if atype in PROTECTION_TYPES and route_mode == ROUTE_LOG:
        violations.append(INV_PROTECTION_ALWAYS_VISIBLE)
        route_mode, destination = ROUTE_COMMAND_CENTER, None
        suppression = INV_PROTECTION_ALWAYS_VISIBLE

    # Synthetic events can never occupy a real delivery channel.
    if bool((event.payload or {}).get("delivery_prohibited")):
        if route_mode == ROUTE_IMMEDIATE:
            route_mode, destination = ROUTE_COMMAND_CENTER, None
        suppression = suppression or "synthetic_delivery_prohibited"

    # ── Runtime mode gate: only ACTIVE may actually deliver through the outbox.
    delivery_allowed = (
        runtime_mode == MODE_ACTIVE
        and route_mode == ROUTE_IMMEDIATE
        and not bool((event.payload or {}).get("delivery_prohibited"))
    )

    return ResolvedRoute(
        route_mode=route_mode,
        logical_destination=destination,
        digest_bucket=bucket if route_mode == ROUTE_DIGEST else None,
        ttl_seconds=ttl,
        dedupe_window_seconds=dedupe,
        escalate_after_seconds=escalate,
        sound_enabled=sound,
        suppression_reason=suppression,
        invariant_violations=tuple(dict.fromkeys(violations)),
        applied_preference=applied,
        preference_row_version=row_version,
        runtime_mode=runtime_mode,
        delivery_allowed=delivery_allowed,
        sources=sources,
    )


def load_preferences(conn=None) -> dict[str, dict[str, Any]]:
    """alert_type -> preference row. Empty dict when unmigrated/unavailable."""
    from alert_runtime_mode import missing_tables
    if missing_tables(conn):
        return {}
    own = False
    try:
        if conn is None:
            from db_adapter import _get_conn
            conn = _get_conn()
            own = True
        if conn is None:
            return {}
        with conn.cursor() as cur:
            cur.execute(
                "SELECT alert_type, " + ", ".join(PREFERENCE_FIELDS) + ", row_version "
                "FROM operator_alert_preferences"
            )
            cols = [d[0] for d in cur.description]
            return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}
    except Exception:
        return {}
    finally:
        if own and conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
