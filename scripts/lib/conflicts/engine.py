"""Trade-AI Conflict Resolution Engine — generic core (REFERENCE, coordinator 2026-10-24).

Operator: "a durable conflict resolution engine that's not just used here, but can be used in other parts of the site
when there are conflicts."

One engine, many domains. The core knows nothing about stocks, jobs or dollars:
  Subject   what the inputs are about (kind + id + context), e.g. security:SPCX, metric:portfolio_total, job:catalyst-engine
  Input     one producer's claim about the subject: source, value, as_of, role
  Profile   a domain plug-in: how to compare two values (same / compatible / opposite / unknown), freshness limits per
            source, which source is canonical, which roles are gates or never-auto, and the plain-English wording
  Finding   the verdict the operator sees (kind, rule, summary, clears_when, action, severity, sides, key)
  Ledger    the durable record (ConflictRecord@v1 lifecycle + ConflictDecision@v1), outside this pure module

Universal rules (every profile gets them; profiles may only tighten):
  U0 safety/protection/policy roles are NEVER auto-resolved          → GATE (blocks) or NEEDS_OPERATOR
  U1 identity/time/vocabulary unreadable                              → DATA_ERROR (excluded from judgement)
  U2 canonical value missing                                          → CONFLICT, review forced (profile's default)
  U3 canonical value stale and a newer input disagrees                → CONFLICT, canonical refresh/review
  U4 an input much older than the canonical value                     → SUPERSEDED, refresh queued
  U5 values compatible under the profile                              → AGREEMENT (never flags)
  U6 a gate role blocks the canonical action                          → GATE, clears when the check passes
  U7 two fresh, opposite values                                       → CONFLICT, the owner reviews and decides
  U8 the same conflict reopens ≥ N times in a window                  → NEEDS_OPERATOR (flapping)
  U9 every non-agreement finding states what clears it
Precedence is the order above. Pure, deterministic, no I/O; MBI_BEHAVIOR = 0 (never orders, sizes or stops).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional, Protocol

ENGINE_VERSION = "ConflictEngine@v1-matrix-draft"

SAME, COMPATIBLE, OPPOSITE, UNKNOWN = "same", "compatible", "opposite", "unknown"
SEVERITY_ORDER = {"NEEDS_OPERATOR": 0, "GATE": 1, "CONFLICT": 2, "DATA_ERROR": 3, "SUPERSEDED": 4, "AGREEMENT": 5}


@dataclass
class Subject:
    kind: str                      # security | metric | job | position | count | ...
    id: str                        # canonical id (security_guid, metric name, lane_id, ...)
    label: str                     # what the operator reads (SPCX, "Portfolio total", job name)
    context: dict = field(default_factory=dict)   # profile-specific (held, accounts, unit, ...)


@dataclass
class Input:
    source: str
    value: Any
    as_of: Optional[datetime]
    role: str = "claim"            # claim | gate | safety | protection | policy
    subject_id: Optional[str] = None
    account: Optional[str] = None
    detail: Optional[str] = None
    inputs_as_of: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Finding:
    kind: str
    rule: str
    summary: str
    clears_when: str
    action: str = "none"           # none | queue_refresh | queue_review | notify_operator
    severity: str = "info"         # info | warn | block | operator
    sides: list = field(default_factory=list)
    key: str = ""
    owner: str = "source owner"
    next_run: str = "Not measured"
    never_auto: bool = False
    tier: int = 4

    def as_dict(self) -> dict:
        return {"schema": "ConflictFinding@v1", "engine": ENGINE_VERSION, **self.__dict__}


class Profile(Protocol):
    name: str
    canonical_source: str                     # whose value wins by default (e.g. the CIO record)
    canonical_max_age: timedelta
    flap_limit: int
    flap_window: timedelta

    def compare(self, a: Any, b: Any, subject: Subject) -> str: ...          # SAME | COMPATIBLE | OPPOSITE | UNKNOWN
    def supersede_after(self, source: str) -> timedelta: ...
    def gate_blocks(self, gate: Input, canonical: Input, subject: Subject) -> bool: ...
    def protection_finding(self, i: Input, subject: Subject, canonical: Optional[Input]) -> Optional[Finding]: ...
    def describe(self, value: Any) -> str: ...
    def owner_review_action(self) -> str: ...                                 # queue_review (CIO) / notify_operator


def side(i: Input, profile: Profile) -> dict:
    at = i.inputs_as_of if i.inputs_as_of is not None or i.metadata.get("material_time_required") else i.as_of
    return {"source": i.source, "value": profile.describe(i.value),
            "as_of": at.isoformat() if isinstance(at, datetime) and at.tzinfo else None,
            "account": i.account, "source_label": profile.source_label(i.source) if hasattr(profile, "source_label") else i.source}


def _fact_findings(findings, profile):
    if profile.name in {"numeric_fact", "schedule_state"}:
        for finding in findings:
            if finding.kind == "CONFLICT":
                finding.kind, finding.rule = "DATA_ERROR", "T1"
                finding.clears_when = "the authoritative source or its reader is repaired and agrees"
                finding.action = "notify_operator"
            if finding.kind == "DATA_ERROR":
                finding.tier, finding.never_auto = 1, True
                finding.owner = "source owner"
    return findings


def evaluate(subject: Subject, canonical: Optional[Input], inputs: Iterable[Input], profile: Profile, *, now: datetime,
             history: Iterable[dict] = ()) -> list[Finding]:
    domain = getattr(profile, "evaluate_domain", None)
    if domain:
        return domain(subject, canonical, list(inputs), now=now, history=list(history))
    out: list[Finding] = []
    pre = f"{subject.kind}:{subject.id}"
    history = list(history)
    pending: list[Input] = []
    for i in inputs:                                                         # U1
        if i.subject_id and i.subject_id != subject.id:
            out.append(Finding("DATA_ERROR", "U1", f"{i.source} is about a different {subject.kind} (same label, other ID)",
                               "the producer re-keys its row to the confirmed ID", "notify_operator", "warn",
                               [side(i, profile)], f"{pre}:U1:{i.source}"))
        elif i.as_of is None and i.role == "claim":
            out.append(Finding("DATA_ERROR", "U1", f"{i.source} has no readable time — freshness cannot be judged",
                               "the producer stamps its time", "queue_refresh", "warn", [side(i, profile)],
                               f"{pre}:U1t:{i.source}"))
        else:
            pending.append(i)

    for i in [i for i in pending if i.role in ("safety", "protection", "policy")]:    # U0
        pending.remove(i)
        f = profile.protection_finding(i, subject, canonical)
        if f:
            f.key = f.key or f"{pre}:U0:{i.source}:{i.account or ''}"
            out.append(f)

    if canonical is None:                                                    # U2
        out.append(Finding("CONFLICT", "U2", f"No {profile.canonical_source} value on record",
                           f"{profile.canonical_source} records a value", profile.owner_review_action(), "warn", [],
                           f"{pre}:U2"))
        return _fact_findings(out, profile)
    can_age = (now - canonical.as_of) if canonical.as_of else None
    can_stale = can_age is not None and can_age > profile.canonical_max_age

    for g in [i for i in pending if i.role == "gate"]:                       # U6
        pending.remove(g)
        if profile.gate_blocks(g, canonical, subject):
            out.append(Finding("GATE", "U6", f"Blocked: {g.detail or g.source} ({profile.describe(g.value)})",
                               f"{g.source} passes on its next run", "none", "block",
                               [side(g, profile), side(canonical, profile)], f"{pre}:U6:{g.source}"))

    for i in [i for i in pending if i.role == "claim"]:
        rel = profile.compare(canonical.value, i.value, subject)
        if rel == UNKNOWN:
            out.append(Finding("DATA_ERROR", "U1", f"{i.source} value '{profile.describe(i.value)}' cannot be compared",
                               "the producer uses a known value/unit", "notify_operator", "warn", [side(i, profile)],
                               f"{pre}:U1v:{i.source}"))
            continue
        if rel in (SAME, COMPATIBLE):                                        # U5
            note = "" if rel == SAME else f" ({profile.describe(i.value)} vs {profile.describe(canonical.value)})"
            out.append(Finding("AGREEMENT", "U5", f"{i.source} agrees with {profile.canonical_source}{note}", "—",
                               "none", "info", [side(i, profile), side(canonical, profile)], f"{pre}:U5:{i.source}"))
            continue
        older_by = (canonical.as_of - i.as_of) if (canonical.as_of and i.as_of) else timedelta(0)
        if can_stale and i.as_of and canonical.as_of and i.as_of > canonical.as_of:      # U3
            out.append(Finding("CONFLICT", "U3", f"{profile.canonical_source} is {can_age.days} days old and {i.source} "
                               f"now says {profile.describe(i.value)}", f"{profile.canonical_source} re-reviews",
                               profile.owner_review_action(), "warn", [side(i, profile), side(canonical, profile)],
                               f"{pre}:U3:{i.source}"))
            continue
        if older_by > profile.supersede_after(i.source):                     # U4
            out.append(Finding("SUPERSEDED", "U4", f"{i.source} ({profile.describe(i.value)}, {older_by.days} days older) "
                               f"is superseded by {profile.canonical_source} ({profile.describe(canonical.value)})",
                               f"{i.source} refreshes", "queue_refresh", "info",
                               [side(i, profile), side(canonical, profile)], f"{pre}:U4:{i.source}"))
            continue
        key = f"{pre}:U7:{i.source}"
        reopened = [h for h in history if h.get("key") == key and h.get("opened_at")
                    and now - h["opened_at"] <= profile.flap_window]
        if len(reopened) >= profile.flap_limit:                              # U8
            out.append(Finding("NEEDS_OPERATOR", "U8", f"{i.source} and {profile.canonical_source} keep flipping "
                               f"({len(reopened)} times)", "you decide which input to trust here", "notify_operator",
                               "operator", [side(i, profile), side(canonical, profile)], key))
            continue
        out.append(Finding("CONFLICT", "U7", f"{profile.canonical_source} says {profile.describe(canonical.value)}; "
                           f"{i.source} says {profile.describe(i.value)}",
                           f"{profile.canonical_source} reviews both and records a decision with its reason",
                           profile.owner_review_action(), "warn", [side(canonical, profile), side(i, profile)], key))
    return _fact_findings(out, profile)


def finding_sort_key(finding: Finding):
    return (finding.tier, SEVERITY_ORDER[finding.kind], finding.key)


def headline(findings: Iterable[Finding]) -> Optional[str]:
    """U9: the one line any card shows — most severe first; AGREEMENT and SUPERSEDED never flag."""
    flagged = sorted((f for f in findings if f.kind in ("NEEDS_OPERATOR", "GATE", "CONFLICT", "DATA_ERROR")),
                     key=finding_sort_key)
    if not flagged:
        return None
    more = f" · +{len(flagged) - 1} more" if len(flagged) > 1 else ""
    return f"{flagged[0].summary} — clears when {flagged[0].clears_when}{more}"
