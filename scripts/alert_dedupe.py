#!/usr/bin/env python3
"""Recurring-event dedupe decision — pure, deterministic, timestamp-injected.

The previous model used one globally-unique fingerprint as the suppression key, so
the FIRST occurrence of an alert suppressed every later one for the lifetime of the
row: a stop that went unprotected, was fixed, and went unprotected again a week later
produced exactly one notification, forever. It also overwrote the stored payload on
every repeat, destroying the occurrence history.

Here a fingerprint identifies a RECURRING CONDITION, not a single permanent event.
Suppression is a function of the condition's state and the clock:

    notify when   no prior occurrence
                  | prior occurrence older than the dedupe window
                  | severity increased
                  | operator action became required
                  | state_version changed
                  | the condition was resolved and has recurred
                  | the escalation deadline passed without acknowledgement
                  | the condition resolved and resolution is worth reporting

Every occurrence is retained; nothing is overwritten. `should_notify` never touches a
database or a clock — callers pass `now`, which is what makes the tests deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

# Ordered low -> high. Anything unknown sorts at "info".
SEVERITY_ORDER = ("debug", "info", "notice", "warning", "error", "critical", "urgent")

NOTIFY_FIRST_OCCURRENCE = "first_occurrence"
NOTIFY_WINDOW_ELAPSED = "dedupe_window_elapsed"
NOTIFY_SEVERITY_INCREASED = "severity_increased"
NOTIFY_ACTION_REQUIRED = "operator_action_now_required"
NOTIFY_STATE_VERSION = "state_version_changed"
NOTIFY_RECURRED_AFTER_RESOLUTION = "recurred_after_resolution"
NOTIFY_ESCALATION_DEADLINE = "escalation_deadline_passed"
NOTIFY_RESOLUTION = "condition_resolved"
SUPPRESS_WITHIN_WINDOW = "duplicate_within_dedupe_window"


def severity_rank(sev: str | None) -> int:
    s = (sev or "info").strip().lower()
    return SEVERITY_ORDER.index(s) if s in SEVERITY_ORDER else SEVERITY_ORDER.index("info")


@dataclass(frozen=True)
class PriorState:
    """What we already know about this recurring condition."""
    last_notified_at: datetime | None = None
    last_seen_at: datetime | None = None
    severity: str | None = None
    operator_action_required: bool = False
    state_version: str | None = None
    resolved_at: datetime | None = None
    acknowledged_at: datetime | None = None
    occurrence_count: int = 0
    notified_count: int = 0


@dataclass(frozen=True)
class DedupeDecision:
    notify: bool
    reason: str
    occurrence_seq: int
    is_escalation: bool = False
    is_resolution: bool = False
    suppressed_until: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        if isinstance(d.get("suppressed_until"), datetime):
            d["suppressed_until"] = d["suppressed_until"].isoformat()
        return d


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def should_notify(
    prior: PriorState | None,
    *,
    now: datetime,
    severity: str = "info",
    operator_action_required: bool = False,
    state_version: str = "1",
    dedupe_window_seconds: int = 900,
    escalate_after_seconds: int | None = None,
    resolving: bool = False,
    notify_on_resolution: bool = True,
) -> DedupeDecision:
    """Decide whether this occurrence warrants a notification.

    `resolving=True` marks the condition clearing. A resolution is reported once
    (when the condition had actually been notified), so the operator learns the
    problem is over instead of being left to infer it from silence.
    """
    now = _aware(now) or datetime.now(timezone.utc)

    if prior is None or prior.occurrence_count == 0:
        seq = 1
        if resolving:
            # Nothing was ever reported, so there is nothing to resolve.
            return DedupeDecision(False, "resolution_without_prior_occurrence", seq, is_resolution=True)
        return DedupeDecision(True, NOTIFY_FIRST_OCCURRENCE, seq)

    seq = prior.occurrence_count + 1
    last_notified = _aware(prior.last_notified_at)
    resolved_at = _aware(prior.resolved_at)
    acknowledged_at = _aware(prior.acknowledged_at)

    if resolving:
        if notify_on_resolution and prior.notified_count > 0 and resolved_at is None:
            return DedupeDecision(True, NOTIFY_RESOLUTION, seq, is_resolution=True)
        return DedupeDecision(False, "resolution_not_reportable", seq, is_resolution=True)

    # A previously-resolved condition that reappears is genuinely new.
    if resolved_at is not None:
        return DedupeDecision(True, NOTIFY_RECURRED_AFTER_RESOLUTION, seq)

    if severity_rank(severity) > severity_rank(prior.severity):
        return DedupeDecision(True, NOTIFY_SEVERITY_INCREASED, seq)

    if operator_action_required and not prior.operator_action_required:
        return DedupeDecision(True, NOTIFY_ACTION_REQUIRED, seq)

    if state_version and prior.state_version and str(state_version) != str(prior.state_version):
        return DedupeDecision(True, NOTIFY_STATE_VERSION, seq)

    # Unacknowledged past its escalation deadline: re-raise rather than let a live
    # problem age out in silence.
    if (escalate_after_seconds and last_notified and acknowledged_at is None
            and now - last_notified >= timedelta(seconds=int(escalate_after_seconds))):
        return DedupeDecision(True, NOTIFY_ESCALATION_DEADLINE, seq, is_escalation=True)

    if last_notified is None:
        return DedupeDecision(True, NOTIFY_WINDOW_ELAPSED, seq)

    window = timedelta(seconds=max(0, int(dedupe_window_seconds)))
    if now - last_notified >= window:
        return DedupeDecision(True, NOTIFY_WINDOW_ELAPSED, seq)

    return DedupeDecision(False, SUPPRESS_WITHIN_WINDOW, seq,
                          suppressed_until=last_notified + window)
