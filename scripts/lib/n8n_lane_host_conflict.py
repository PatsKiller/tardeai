"""Classify a host schedule against a lane-registry declaration.

A spent one-shot stays UnitFileState=enabled after it elapses. SubState=elapsed
with an empty next elapse is that unit's normal terminal state. It is not
ENABLED_WHILE_DECLARED_RETIRED, and this module does not disable the unit.

A recurring timer that is still enabled and still has a next elapse, while the
registry says RETIRED or NEVER_SCHEDULED, is a real conflict. A crontab command
that is present while the registry says NEVER_SCHEDULED is a real conflict.
This module does not edit crontab, systemd, or the registry.

2026-10-08 (n8n scheduler-of-record): a lane whose registry row says `scheduler.kind == "n8n"`
has handed its schedule to an n8n workflow. Its old cron line (`scheduler.match`) still present
uncommented, or its old timer still enabled, is a DOUBLE scheduler — the safe_flock lock keeps
the two from running at once, but the registry is then false and the gate must fail:
CRON_PRESENT_WHILE_SCHEDULER_N8N / TIMER_ENABLED_WHILE_SCHEDULER_N8N.
"""
from __future__ import annotations

CLASSIFIER_FALSE_POSITIVE_CLOSED = "CLASSIFIER_FALSE_POSITIVE_CLOSED"
ENABLED_WHILE_DECLARED_RETIRED = "ENABLED_WHILE_DECLARED_RETIRED"
ENABLED_WHILE_DECLARED_NEVER_SCHEDULED = "ENABLED_WHILE_DECLARED_NEVER_SCHEDULED"
CRON_PRESENT_WHILE_DECLARED_NEVER_SCHEDULED = "CRON_PRESENT_WHILE_DECLARED_NEVER_SCHEDULED"
CRON_PRESENT_WHILE_SCHEDULER_N8N = "CRON_PRESENT_WHILE_SCHEDULER_N8N"
TIMER_ENABLED_WHILE_SCHEDULER_N8N = "TIMER_ENABLED_WHILE_SCHEDULER_N8N"
SCHEDULER_N8N = "n8n"
ALIGNED = "ALIGNED"
UNCLASSIFIED = "UNCLASSIFIED"

_ENABLED = frozenset({"enabled", "enabled-runtime", "static"})
_ABSENT = frozenset({"", "n/a", "0", "none", "null"})


def next_elapse_absent(value: object) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in _ABSENT


def classify_timer(
    *,
    declared_state: str,
    unit_file_state: str,
    sub_state: str,
    next_elapse: object,
    recurring: bool,
    scheduler_kind: str = "systemd",
) -> str:
    """Return a conflict code, ALIGNED, or CLASSIFIER_FALSE_POSITIVE_CLOSED.

    ``scheduler_kind="n8n"``: the unit named in the lane's `match` is the RETIRED scheduler; it
    being enabled (and not a spent one-shot) is the double-scheduler conflict, whatever the state.
    """
    declared = (declared_state or "").strip().upper()
    enabled = (unit_file_state or "").strip().lower() in _ENABLED
    spent = (sub_state or "").strip().lower() == "elapsed" and next_elapse_absent(next_elapse)
    if (scheduler_kind or "").strip().lower() == SCHEDULER_N8N:
        if enabled and not spent:
            return TIMER_ENABLED_WHILE_SCHEDULER_N8N
        return ALIGNED
    if spent and not recurring and declared == "RETIRED":
        return CLASSIFIER_FALSE_POSITIVE_CLOSED
    if enabled and not spent and recurring and declared == "RETIRED":
        return ENABLED_WHILE_DECLARED_RETIRED
    if enabled and not spent and recurring and declared == "NEVER_SCHEDULED":
        return ENABLED_WHILE_DECLARED_NEVER_SCHEDULED
    if declared == "ACTIVE" and enabled and not spent:
        return ALIGNED
    if declared == "RETIRED" and not enabled:
        return ALIGNED
    return UNCLASSIFIED


def classify_cron(*, declared_state: str, command_present: bool, scheduler_kind: str = "cron") -> str:
    """``scheduler_kind="n8n"``: the matched cron command is the RETIRED scheduler; present and
    uncommented is the double-scheduler conflict, whatever the declared state."""
    declared = (declared_state or "").strip().upper()
    if (scheduler_kind or "").strip().lower() == SCHEDULER_N8N:
        return CRON_PRESENT_WHILE_SCHEDULER_N8N if command_present else ALIGNED
    if command_present and declared == "NEVER_SCHEDULED":
        return CRON_PRESENT_WHILE_DECLARED_NEVER_SCHEDULED
    if command_present and declared == "ACTIVE":
        return ALIGNED
    if not command_present and declared in {"NEVER_SCHEDULED", "RETIRED", "PAUSED"}:
        return ALIGNED
    return UNCLASSIFIED
