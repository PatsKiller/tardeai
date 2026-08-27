"""HealthRemediationOutcome@v1 — did the fix actually fix it?

Both live health agents define remediation success as `proc.returncode == 0`
(`system_health_agent.py:878`, `health_agent.py:569`). A subprocess exiting 0
means the command ran, not that the condition cleared. On 2026-08-27 the durable
record held 3,669 `ok: true` rows, every one of them a statement about an exit
code, and the operator alert printed "Auto-fixed" on that basis.

The 2026-08-26 repricer incident is the shape this exists to catch: the fix ran,
exited 0, wrote its output to a copy nothing reads, and the served numbers stayed
stale for 24 hours while the agent reported success each cycle.

So the verdict here is decided by **re-running the originating check and
comparing the finding**. The exit code is one input and never the verdict:

    FAILED      the command did not run to completion (non-zero, timeout, raise)
    CLEARED     it ran, and the originating finding no longer fires
    INEFFECTIVE it ran, and the finding still fires unchanged
    WORSENED    it ran, and the condition moved the wrong way

WORSENED is separated from INEFFECTIVE deliberately. A fix that makes things
worse while reporting success is the most dangerous state in the system, and
retrying it compounds the damage — so it escalates at once and stops.

This module is pure: it takes before/after findings and returns a verdict. It
runs no commands and writes nothing, so it can be tested on the real incident
shape rather than on source text. PR #543 shipped broken past a test that only
read source text; that is not a mistake worth repeating.

AUTHORITY: READ_ONLY_ADVISORY. Diagnoses; never remediates.
"""
from __future__ import annotations

from typing import Any, Iterable

SCHEMA = "HealthRemediationOutcome@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

CLEARED = "CLEARED"
INEFFECTIVE = "INEFFECTIVE"
FAILED = "FAILED"
WORSENED = "WORSENED"

# Ordered worst-last, so a rise in index is a regression.
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}

# Typed root causes. Seeded per the maturity plan; `unknown` is deliberately NOT
# a member — an undiagnosed INEFFECTIVE must say so as UNDIAGNOSED rather than
# be filed under a label that reads like a finding.
CAUSE_WROTE_UNREAD_COPY = "WROTE_UNREAD_COPY"
CAUSE_EFFECT_NOT_OBSERVED = "EFFECT_NOT_OBSERVED"
CAUSE_UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
CAUSE_UNDIAGNOSED = "UNDIAGNOSED"

ROOT_CAUSES = (
    CAUSE_WROTE_UNREAD_COPY,
    CAUSE_EFFECT_NOT_OBSERVED,
    CAUSE_UPSTREAM_UNAVAILABLE,
    CAUSE_UNDIAGNOSED,
)

# Exit codes meaning "another holder has the lock", not "the fix failed".
FLOCK_CONTENTION_CODES = frozenset({69, 99})


def _severity_rank(finding: dict[str, Any] | None) -> int:
    if not finding:
        return -1
    return SEVERITY_RANK.get(str(finding.get("severity") or "").lower(), 0)


def find_matching(finding_type: str, findings: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """The same finding type in a later scan, if it is still firing."""
    for f in findings or ():
        if str(f.get("type")) == str(finding_type):
            return f
    return None


def _metric(finding: dict[str, Any] | None) -> float | None:
    """A comparable magnitude, when the finding carries one.

    Only fields that mean "how bad" are read. A finding with no such field is
    compared on severity alone rather than on an invented number.
    """
    if not finding:
        return None
    for key in ("age_hours", "age_seconds", "stale_hours", "count", "missing_count",
                "failure_count", "backlog", "drift_pct"):
        value = finding.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def classify(
    *,
    finding_type: str,
    before: dict[str, Any],
    after_findings: Iterable[dict[str, Any]],
    exit_code: int | None,
    timed_out: bool = False,
    raised: bool = False,
) -> dict[str, Any]:
    """Verdict on one remediation, from the re-checked condition.

    `after_findings` is the finding set from re-running the originating check
    AFTER the command. Passing the pre-remediation set here would make every
    verdict INEFFECTIVE, so callers must re-run and pass the new set.
    """
    still = find_matching(finding_type, after_findings)

    # Did the command even run? Exit code answers only this question.
    if raised or timed_out:
        outcome = FAILED
    elif exit_code is not None and exit_code in FLOCK_CONTENTION_CODES:
        # Someone else holds the lock; nothing was attempted. Not a failure of
        # the fix, and explicitly not a success either.
        outcome = FAILED
    elif exit_code is not None and exit_code != 0:
        outcome = FAILED
    elif still is None:
        outcome = CLEARED
    else:
        before_rank, after_rank = _severity_rank(before), _severity_rank(still)
        before_metric, after_metric = _metric(before), _metric(still)
        worse = after_rank > before_rank or (
            before_metric is not None
            and after_metric is not None
            and after_metric > before_metric
        )
        outcome = WORSENED if worse else INEFFECTIVE

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "outcome": outcome,
        # `ok` is the verdict, never the exit code. Kept for readers that still
        # consume the old boolean, so they cannot be told a lie by omission.
        "ok": outcome == CLEARED,
        "finding_type": finding_type,
        "exit_code": exit_code,
        "verified_by_recheck": not (raised or timed_out),
        "severity_before": before.get("severity"),
        "severity_after": still.get("severity") if still else None,
        "metric_before": _metric(before),
        "metric_after": _metric(still),
        "still_firing": still is not None,
    }


def diagnose(verdict: dict[str, Any], *, evidence: dict[str, Any] | None = None) -> str:
    """A typed root cause for an INEFFECTIVE or WORSENED verdict.

    Returns UNDIAGNOSED rather than guessing. A wrong cause is worse than an
    absent one: it terminates the investigation.
    """
    if verdict.get("outcome") not in (INEFFECTIVE, WORSENED):
        return ""
    ev = evidence or {}

    # The repricer shape: the command succeeded and wrote something, but the
    # path it wrote is not the path the reader reads.
    if ev.get("wrote_path") and ev.get("read_path") and ev["wrote_path"] != ev["read_path"]:
        return CAUSE_WROTE_UNREAD_COPY
    if ev.get("upstream_unavailable"):
        return CAUSE_UPSTREAM_UNAVAILABLE
    # It ran cleanly and the condition is unchanged: the effect was not observed
    # where the check looks.
    if verdict.get("exit_code") == 0 and verdict.get("still_firing"):
        return CAUSE_EFFECT_NOT_OBSERVED
    return CAUSE_UNDIAGNOSED


def should_stop_retrying(
    verdict: dict[str, Any], ineffective_streak: int, *, breaker: int = 2
) -> tuple[bool, str]:
    """Whether to stop and escalate. Returns (stop, reason).

    WORSENED stops immediately regardless of streak — retrying a fix that is
    making the condition worse compounds it, and the streak counter would spend
    two more cycles doing exactly that.
    """
    if verdict.get("outcome") == WORSENED:
        return True, "worsened_on_first_observation"
    if verdict.get("outcome") == INEFFECTIVE and ineffective_streak >= breaker:
        return True, f"ineffective_{ineffective_streak}x_breaker_{breaker}"
    return False, ""


def escalation_payload(
    verdict: dict[str, Any],
    *,
    root_cause: str,
    command: str,
    reason: str,
    trend: str | None = None,
) -> dict[str, Any]:
    """What the operator needs to act, not merely to be informed.

    Carries the diagnosis, the metric trend, and the exact command that failed
    to help — an alert saying "remediation ineffective" without the command is
    a page that cannot be actioned without a log dive.
    """
    before, after = verdict.get("metric_before"), verdict.get("metric_after")
    if trend is None and before is not None and after is not None:
        direction = "worse" if after > before else ("better" if after < before else "unchanged")
        trend = f"{before} -> {after} ({direction})"
    return {
        "schema": "HealthEscalation@v1",
        "authority": AUTHORITY,
        "outcome": verdict.get("outcome"),
        "finding_type": verdict.get("finding_type"),
        "root_cause": root_cause,
        "command_that_did_not_help": command,
        "metric_trend": trend or "no comparable metric on this finding",
        "severity": f"{verdict.get('severity_before')} -> {verdict.get('severity_after')}",
        "stop_reason": reason,
        "verified_by_recheck": verdict.get("verified_by_recheck"),
        "needs_operator": True,
    }
