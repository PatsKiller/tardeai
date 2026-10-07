"""Classify a host schedule against a lane-registry declaration.

A spent one-shot stays UnitFileState=enabled after it elapses. SubState=elapsed
with an empty next elapse is that unit's normal terminal state. It is not
ENABLED_WHILE_DECLARED_RETIRED, and this module does not disable the unit.

A recurring timer that is still enabled and still has a next elapse, while the
registry says RETIRED or NEVER_SCHEDULED, is a real conflict. A crontab command
that is present while the registry says NEVER_SCHEDULED is a real conflict.
This module does not edit crontab, systemd, or the registry.
"""
from __future__ import annotations

CLASSIFIER_FALSE_POSITIVE_CLOSED = "CLASSIFIER_FALSE_POSITIVE_CLOSED"
ENABLED_WHILE_DECLARED_RETIRED = "ENABLED_WHILE_DECLARED_RETIRED"
ENABLED_WHILE_DECLARED_NEVER_SCHEDULED = "ENABLED_WHILE_DECLARED_NEVER_SCHEDULED"
CRON_PRESENT_WHILE_DECLARED_NEVER_SCHEDULED = "CRON_PRESENT_WHILE_DECLARED_NEVER_SCHEDULED"
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
) -> str:
    """Return a conflict code, ALIGNED, or CLASSIFIER_FALSE_POSITIVE_CLOSED."""
    declared = (declared_state or "").strip().upper()
    enabled = (unit_file_state or "").strip().lower() in _ENABLED
    spent = (sub_state or "").strip().lower() == "elapsed" and next_elapse_absent(next_elapse)
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


def classify_cron(*, declared_state: str, command_present: bool) -> str:
    declared = (declared_state or "").strip().upper()
    if command_present and declared == "NEVER_SCHEDULED":
        return CRON_PRESENT_WHILE_DECLARED_NEVER_SCHEDULED
    if command_present and declared == "ACTIVE":
        return ALIGNED
    if not command_present and declared in {"NEVER_SCHEDULED", "RETIRED", "PAUSED"}:
        return ALIGNED
    return UNCLASSIFIED
