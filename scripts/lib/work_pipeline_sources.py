"""Shared read-only work facts for Work pipeline and Releases.

A census snapshot supplies PRs, released membership and served_contains in its
background refresh. This request adapter runs no git/GitHub and never calls a
release membership checker. Claims/worklogs are the existing board projection;
ledger events, approvals and plan frontmatter are bounded local snapshots.
Only public typed fields leave these sources. A fact always names source/time;
reading a file is captured_at and never refreshes the underlying evidence.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from scripts.lib import releases_coordination as coordination

SCHEMA = "WorkPipelineSources@v1"
LEDGER_REL = "data/coordination/coordinator/ledger.jsonl"
APPROVALS_REL = "data/runtime/pr_merge_telegram/digest_approvals.jsonl"
PLANS_REL = "data/coordination/plans"
CLAIMS_REL = "data/coordination/claims"
REGISTRY_REL = "data/coordination/coordinator/coordinators.json"
NUDGER_REL = "data/coordination/coordinator/agent_nudger_state.json"
MAX_NUDGER_BYTES = 128 * 1024
MAX_NUDGER_SESSIONS = 256
MAX_WORKLOG_READS = 64
CLAIM_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[a-z0-9_.-]{1,24}-[0-9a-f]{8}\Z")
MAX_REGISTRY_BYTES = 64 * 1024
MAX_COORDINATORS = 64
MAX_BYTES = 2_000_000
MAX_EVENTS = 20_000
MAX_PLANS = 200
MAX_PLAN_BYTES = 256_000
MAX_PRS = 200
MAX_CLAIMS = 1000
MAX_HISTORY = 100
LIFECYCLE_STAGES = frozenset({"claimed", "building", "pr_open", "ci_green", "merged", "released", "abandoned"})
SHA = re.compile(r"[0-9a-f]{40}\Z")
SAFE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,160}\Z")
TIMELINE_KINDS = frozenset({"dispatch", "assign", "check_request", "check_ok", "check_block",
                            "review_verdict", "review_receipt_recorded", "ci_observation",
                            "approval_recorded", "approval_record", "operator_approval_actual", "merge", "merged",
                            "merge_result", "verified_merge", "live_observation", "pr_open", "nudge",
                            "decision_pending", "decision_needed", "decision_resolved", "branch_uploaded",
                            "publication_observation", "stage_transition", "review_started", "approval_started", "checks_started"})
PLAN_FIELDS = ("id", "title", "author_session", "vendor", "approved_at", "status", "claim", "branch",
               "pr", "updated_at", "stalled_since")
CLAIM_FIELDS = ("claim_id", "session", "worker_session", "agent", "vendor", "coordinator", "task", "branch", "pr", "pr_number", "state", "status",
                "stage", "stages", "started_at", "heartbeat_at", "ended_at", "head_sha", "worktree_head_sha", "worklog")


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and "T" in value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: Any) -> str | None:
    parsed = _parse(value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed is not None else None


def _sort_time(value: Any) -> datetime:
    return _parse(value) or datetime.min.replace(tzinfo=timezone.utc)


def _latest(values: Iterable[Any]) -> str | None:
    stamps = [stamp for value in values if (stamp := _parse(value))]
    return _iso(max(stamps)) if stamps else None


def _number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.startswith("#"):
        value = value[1:]
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def _text(value: Any, limit: int = 300) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


def _fact(value: Any, source: str, at: Any = None, gap: str | None = None) -> dict:
    return {"value": value, "source": source, "as_of": _iso(at), "gap": gap}


def _public_claim(claim: Mapping) -> dict:
    """Canonical board metadata only; no raw nested worklog/stage payloads."""
    public = {key: claim[key] for key in CLAIM_FIELDS if key in claim and key not in ("worklog", "stages")
              and (claim[key] is None or isinstance(claim[key], (str, int, bool)))}
    worklog = claim.get("worklog")
    safe_worklog = {}
    if isinstance(worklog, Mapping):
        if isinstance(worklog.get("exists"), bool):
            safe_worklog["exists"] = worklog["exists"]
        if isinstance(worklog.get("next_step"), str):
            safe_worklog["next_step"] = worklog["next_step"][:1000]
        for key in ("blocker_text", "blocker_gap"):
            if isinstance(worklog.get(key), str):
                safe_worklog[key] = worklog[key][:300]
        if (stamp := _iso(worklog.get("last_entry_at"))):
            safe_worklog["last_entry_at"] = stamp
        for key in ("plan_done", "plan_total", "blockers"):
            value = worklog.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                safe_worklog[key] = value
    public["worklog"] = safe_worklog
    stages = claim.get("stages")
    public["stages"] = {key: stamp for key, value in stages.items()
                        if key in LIFECYCLE_STAGES and (stamp := _iso(value))} if isinstance(stages, Mapping) else {}
    return public


def _claim_time(claim: Mapping) -> str | None:
    return _latest([claim.get("heartbeat_at"), (claim.get("worklog") or {}).get("last_entry_at")])


def _event_pr(row: Mapping) -> int | None:
    number = _number(row.get("pr_number") or row.get("pr"))
    if number:
        return number
    subject = row.get("subject")
    return _number(subject[3:]) if isinstance(subject, str) and subject.startswith("pr:") else None


def _public_event(row: Mapping, index: int, head: str) -> dict:
    row_head = row.get("head_sha") or row.get("sha")
    row_head = row_head if isinstance(row_head, str) and SHA.fullmatch(row_head) else None
    subject = row.get("subject")
    claim_id = row.get("claim_id") or (subject[6:] if isinstance(subject, str) and subject.startswith("claim:") else None)
    claim_id = claim_id if isinstance(claim_id, str) and SAFE_ID.fullmatch(claim_id) else None
    return {"kind": row.get("kind"), "pr": _event_pr(row), "head_sha": row_head,
            "claim_id": claim_id, "session": _text(row.get("session"), 100),
            "branch": _text(row.get("branch"), 200),
            "to_stage": row.get("to_stage") if row.get("to_stage") in (
                "requested", "building", "uploaded", "pr_open", "checks", "review", "approval", "merged", "live") else None,
            "current_head": bool(row_head and head and row_head == head),
            "actor": _text(row.get("reviewer_session") or row.get("actor_session") or row.get("coordinator"), 100),
            "verdict": _text(row.get("verdict"), 40), "state": _text(row.get("state"), 40),
            "source": "coordinator_ledger", "source_ref": f"{LEDGER_REL}#event-{index}",
            "as_of": _iso(row.get("observed_at") or row.get("ts"))}


def _evidence_events(events: list[Mapping]) -> tuple[list[dict], list[dict]]:
    """Public typed evidence only, normalized before the canonical exact-head fold."""
    out, invalid = [], []
    for row in events:
        if row.get("kind") not in (coordination.REVIEW_KIND, coordination.CI_KIND):
            continue
        at = _iso(row.get("observed_at") or row.get("ts"))
        if not at:
            invalid.append({"pr_number": _number(row.get("pr_number")),
                            "head_sha": row.get("head_sha"), "kind": row.get("kind")})
            continue
        public = {key: row.get(key) for key in ("kind", "pr_number", "head_sha", "evidence_class",
                  "verdict", "reviewer_session", "receipt_path", "receipt_sha256", "state", "source")}
        public["observed_at"] = at
        public["workflows"] = [{key: _text(workflow.get(key), 200) for key in ("name", "status", "conclusion")}
                               for workflow in row.get("workflows") or [] if isinstance(workflow, Mapping)]
        out.append(public)
    return out, invalid


def _registry_view(value: Mapping | None) -> tuple[dict, str | None]:
    """Only registered default routing, never prose or inferred territory authority."""
    if value is None:
        return {}, "registry_not_supplied"
    if not isinstance(value, Mapping):
        return {}, "registry_corrupt"
    stamp = _iso(value.get("updated_at"))
    if stamp is None:
        return {}, "registry_timestamp_invalid"
    lead, rows = value.get("lead"), value.get("coordinators")
    if not isinstance(lead, str) or not SAFE_ID.fullmatch(lead):
        return {}, "registry_lead_invalid"
    if not isinstance(rows, list) or len(rows) > MAX_COORDINATORS:
        return {}, "registry_coordinator_budget_or_shape_invalid"
    public, seen = [], set()
    for row in rows:
        if not isinstance(row, Mapping):
            return {}, "registry_coordinator_invalid"
        ident, role, territories = row.get("id"), row.get("role"), row.get("territories")
        if (not isinstance(ident, str) or not SAFE_ID.fullmatch(ident) or ident in seen
                or not isinstance(role, str) or role not in ("lead", "member", "observer")
                or not isinstance(territories, list) or len(territories) > MAX_COORDINATORS
                or any(not isinstance(t, str) or not SAFE_ID.fullmatch(t) for t in territories)):
            return {}, "registry_coordinator_invalid"
        seen.add(ident)
        public.append({"id": ident, "role": role, "territories": list(territories)})
    leads = [row for row in public if row["role"] == "lead"]
    if len(leads) != 1 or leads[0]["id"] != lead:
        return {}, "registry_lead_not_registered"
    return {"lead": lead, "coordinators": public, "updated_at": stamp}, None


def _terminal(claim: Mapping) -> bool:
    return bool(claim.get("ended_at") or any(
        str(claim.get(key) or "").strip().lower() in coordination.ENDED_STATES
        for key in ("_state", "state", "stage", "status")
    ))


def _past_activity(claim: Mapping, now: datetime) -> tuple[str | None, str | None]:
    values = [("claim_board", _parse(claim.get("heartbeat_at"))),
              ("claim_worklog", _parse((claim.get("worklog") or {}).get("last_entry_at")))]
    valid = [(source, at) for source, at in values if at is not None and at <= now]
    if not valid:
        return None, None
    latest = max(at for _source, at in valid)
    return _iso(latest), "+".join(source for source, at in valid if at == latest)


def _routing(owner: Mapping, registry: Mapping, gaps: Mapping) -> dict:
    if owner.get("coordinator"):
        return {**_fact(owner["coordinator"], "claim_board", owner.get("heartbeat_at") or owner.get("started_at")),
                "routing_basis": "explicit_claim"}
    if registry and not gaps.get("coordination_registry"):
        return {**_fact(registry["lead"], "coordinator_registry", registry["updated_at"]),
                "source_ref": REGISTRY_REL, "routing_basis": "default_lead"}
    return {**_fact(None, "coordinator_registry", None, gaps.get("coordination_registry")
                   or "coordinator_source_not_recorded"), "source_ref": REGISTRY_REL, "routing_basis": None}


def _epoch_or_stamp(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    return _parse(value)


def _nudger_view(value: Any, now: datetime) -> tuple[dict, str | None]:
    if value is None:
        return {}, "nudger_state_not_supplied"
    if isinstance(value, list):
        if len(value) > MAX_NUDGER_SESSIONS or len(set(str(v) for v in value)) != len(value):
            return {}, "nudger_session_budget_or_duplicate"
        if any(not isinstance(v, str) or not SAFE_ID.fullmatch(v) for v in value):
            return {}, "nudger_session_invalid"
        return {session: {"changed_at": None} for session in value}, None
    if not isinstance(value, Mapping) or len(value) > MAX_NUDGER_SESSIONS:
        return {}, "nudger_state_shape_or_budget_invalid"
    public = {}
    for session, record in value.items():
        if not isinstance(session, str) or not SAFE_ID.fullmatch(session) or not isinstance(record, Mapping):
            return {}, "nudger_session_invalid"
        changed = _epoch_or_stamp(record.get("changed_at"))
        if changed is None or changed > now:
            return {}, "nudger_changed_at_invalid"
        public[session] = {"changed_at": _iso(changed)}
    return public, None


def _agent_rows(claims: list[Mapping], active_ids: list[str], tracked: Mapping, events: list[Mapping],
                now: datetime, registry: Mapping, source_gaps: Mapping) -> tuple[list[dict], bool, bool, str | None]:
    """Logical sessions and exact physical nudger links, with separate activity bases."""
    groups: dict[str, list[Mapping]] = {}
    coverage_gaps = []
    for claim in claims:
        if _terminal(claim):
            continue
        logical = claim.get("session") or claim.get("worker_session")
        if not isinstance(logical, str) or not logical:
            if claim.get("claim_id") in active_ids:
                coverage_gaps.append("agent_session_not_recorded")
            continue
        groups.setdefault(logical, []).append(claim)
    nudges, invalid_nudge_clock = {}, False
    for event_index, event in enumerate(events, 1):
        if event.get("kind") != "nudge" or event.get("by") != "agent-nudger":
            continue
        subject = event.get("subject")
        if not isinstance(subject, str) or not SAFE_ID.fullmatch(subject):
            continue
        at = _parse(event.get("ts"))
        if at is None:
            invalid_nudge_clock = True
            continue
        if at > now:
            continue
        nudges.setdefault(subject, []).append((at, event_index))
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    rows = []
    for logical, group in sorted(groups.items()):
        group.sort(key=lambda c: (_sort_time(_past_activity(c, now)[0]),
                                  _sort_time(c.get("started_at"))), reverse=True)
        current = group[0]
        at, basis = _past_activity(current, now)
        gaps = []
        if at is None:
            gaps.append("agent_activity_clock_not_recorded")
        candidates = {value for c in group for value in (c.get("session"), c.get("worker_session"))
                      if isinstance(value, str) and value in tracked}
        physical = next(iter(candidates)) if len(candidates) == 1 else None
        if physical is None:
            gaps.append("nudge_session_link_not_recorded")
        nudge_gap = None
        if physical is None:
            nudge_gap = "nudge_session_link_not_recorded"
        elif source_gaps.get("nudger_state"):
            nudge_gap = "nudger_state_unavailable"
        elif source_gaps.get("coordinator_ledger") or invalid_nudge_clock:
            nudge_gap = "nudge_log_unavailable"
        if nudge_gap and nudge_gap not in gaps:
            gaps.append(nudge_gap)
        stamps = nudges.get(physical, []) if physical else []
        nudge_at = _iso(max(at for at, _index in stamps)) if stamps else None
        changed = (tracked.get(physical) or {}).get("changed_at") if physical else None
        if physical and not changed and not nudge_at:
            nudge_gap = nudge_gap or "nudger_clock_not_recorded"
            gaps.append("nudger_clock_not_recorded")
        members = [{"as_of": _iso(at), "source": "coordinator_ledger",
                    "source_ref": f"{LEDGER_REL}#event-{index}"} for at, index in stamps
                   if at.astimezone(ZoneInfo("America/New_York")).date() == today]
        count = None if nudge_gap else len(members)
        route = _routing(current, registry, source_gaps)
        if route.get("gap"):
            gaps.append(route["gap"])
        current_ids = [c.get("claim_id") for c in group if c.get("claim_id") in active_ids]
        idle = round((now - _parse(at)).total_seconds() / 60, 1) if at else None
        rows.append({
            "active": bool(current_ids), "session": logical, "worker_session": physical,
            "vendor": current.get("vendor"), "coordinator": route.get("value"), "coordinator_fact": route,
            "current_claim_id": current.get("claim_id"), "current_claim_ids": current_ids,
            "claim_ids": [c.get("claim_id") for c in group], "pr": _number(current.get("pr_number") or current.get("pr")),
            "branch": current.get("branch"), "item_id": None, "stage": current.get("stage"),
            "last_activity": at, "activity_source": basis, "activity_as_of": at, "idle_minutes": idle,
            "nudges_today": count, "nudge_gap": nudge_gap, "nudge_source": "coordinator_ledger", "nudge_as_of": nudge_at,
            "nudge_events": members, "nudge_day": str(today), "nudge_timezone": "America/New_York",
            "screen_changed_at": changed, "screen_activity_source": "agent_nudger_state", "screen_activity_basis": "screen_changed_at",
            "gaps": gaps,
        })
    # Membership is independent of auxiliary clocks, routing and nudge coverage.
    # Idle and nudge counters separately report their missing evidence.
    complete = not coverage_gaps and not source_gaps.get("claims")
    nudges_complete = not invalid_nudge_clock and not any(source_gaps.get(key) for key in
        ("nudger_state", "coordinator_ledger")) and all(not row["nudge_gap"] for row in rows if row["active"])
    if invalid_nudge_clock:
        coverage_gaps.append("nudge_event_timestamp_invalid")
    return rows, complete, nudges_complete, ";".join(sorted(set(coverage_gaps))) or None


def _blocker(worklog: Mapping) -> dict:
    count, text = worklog.get("blockers"), _text(worklog.get("blocker_text"), 300)
    gap = worklog.get("blocker_gap")
    if count == 0 and worklog.get("exists") is not False:
        return _fact(None, "claim_worklog", worklog.get("last_entry_at"), gap)
    if not isinstance(count, int) or isinstance(count, bool):
        gap = gap or "worklog_not_available"
    elif count > 0 and not text:
        gap = gap or "worklog_blocker_text_not_recorded"
    return _fact(text, "claim_worklog", worklog.get("last_entry_at"), gap)


def _source(name: str, at: Any, gap: str | None = None) -> dict:
    return {"source": name, "as_of": _iso(at), "status": "UNAVAILABLE" if gap else "OK", "gap": gap}


def build(prs: list[Mapping], claims: list[Mapping], events: list[Mapping], approvals: list[Mapping],
          plans: list[Mapping], now: datetime, *, serving: Mapping | None = None,
          health: Mapping | None = None, source_gaps: Mapping[str, str] | None = None,
          stale_claim_hours: float = 24.0, coordination_registry: Mapping | None = None,
          nudger_sessions: Any = None) -> dict:
    """Pure public facts over snapshots. Historical owners survive stale/ended claims.

    Each PR supplies released={at,sha,basis} from the census's earliest apply
    receipt, plus served_contains from that same census snapshot. No membership
    is inferred from a merge timestamp or an unrelated successful deployment.
    """
    serving, health, source_gaps = serving or {}, health or {}, dict(source_gaps or {})
    registry, registry_gap = _registry_view(coordination_registry)
    if registry_gap and "coordination_registry" not in source_gaps:
        source_gaps["coordination_registry"] = registry_gap
    tracked, nudger_gap = _nudger_view(nudger_sessions, now)
    if nudger_gap and "nudger_state" not in source_gaps:
        source_gaps["nudger_state"] = nudger_gap
    if len(prs) > MAX_PRS:
        source_gaps["prs"] = "pr_budget_exceeded"
        prs = prs[:MAX_PRS]
    if len(claims) > MAX_CLAIMS:
        source_gaps["claims"] = "claim_budget_exceeded"
        claims = claims[:MAX_CLAIMS]
    if len(events) > MAX_EVENTS:
        source_gaps["coordinator_ledger"] = "event_budget_exceeded"
        events = []
    if len(approvals) > MAX_EVENTS:
        source_gaps["digest_approvals"] = "approval_event_budget_exceeded"
        approvals = []
    if len(plans) > MAX_PLANS:
        source_gaps["plans"] = "plan_budget_exceeded"
        plans = plans[:MAX_PLANS]
    valid_approvals = []
    for record in approvals:
        if record.get("schema") == "PrMergeDigestApproval@v1":
            items = record.get("items")
            if not isinstance(items, list) or len(items) > 500:
                source_gaps["digest_approvals"] = "invalid_approval_items"
                continue
        valid_approvals.append(record)
    approvals = valid_approvals
    evidence_events, invalid_evidence = _evidence_events(events)
    if invalid_evidence:
        source_gaps["coordinator_ledger"] = "typed_evidence_timestamp_invalid"
    public_claims = [_public_claim(c) for c in claims]
    active = []
    for raw_claim, claim in zip(claims, public_claims):
        stamp = _iso(claim.get("heartbeat_at"))
        age = (now - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds() if stamp else None
        terminal = _terminal(raw_claim)
        if (not terminal and age is not None and 0 <= age <= stale_claim_hours * 3600
                and claim.get("claim_id")):
            active.append(claim["claim_id"])
    inventory = [{**{key: plan.get(key) for key in PLAN_FIELDS if key in plan},
                  "source": "plan_registry", "source_ref": f"{PLANS_REL}/{plan.get('id')}.md",
                  "as_of": _latest([plan.get("updated_at"), plan.get("approved_at")])} for plan in plans]
    by_pr, owner_candidates, owner_filled = {}, 0, 0
    for pr in prs:
        number = _number(pr.get("number"))
        if number is None:
            continue
        raw_head = pr.get("head_sha") or pr.get("headRefOid")
        head = raw_head if isinstance(raw_head, str) and SHA.fullmatch(raw_head) else ""
        branch = pr.get("branch") or pr.get("headRefName")
        matches = [c for c in public_claims if _number(c.get("pr_number") or c.get("pr")) == number
                   or (branch and c.get("branch") == branch and not _number(c.get("pr_number") or c.get("pr")))]
        matches.sort(key=lambda c: (bool(branch and c.get("branch") == branch),
                                    bool(pr.get("state") != "merged" and c.get("claim_id") in active),
                                    _sort_time(_claim_time(c)), _sort_time(c.get("started_at"))), reverse=True)
        owner = matches[0] if matches else None
        if matches:
            owner_candidates += 1
            owner_filled += bool((owner or {}).get("session"))
        owner_at = _iso((owner or {}).get("heartbeat_at") or (owner or {}).get("started_at"))
        wl = (owner or {}).get("worklog") or {}
        history = [_public_event(row, index, head) for index, row in enumerate(events, 1)
                   if isinstance(row.get("kind"), str) and row.get("kind") in TIMELINE_KINDS
                   and _event_pr(row) == number]
        for kind, value in (("pr_open", pr.get("created_at") or pr.get("createdAt")),
                            ("merged", pr.get("merged_at") or pr.get("mergedAt"))):
            at = _iso(value)
            if at:
                history.append({"kind": kind, "as_of": at, "source": "github_census",
                                "source_ref": f"github_pr:{number}", "head_sha": head or None})
        for claim in matches:
            for kind in ("claimed", "building"):
                at = _iso((claim.get("stages") or {}).get(kind) or
                          (claim.get("started_at") if kind == "claimed" else None))
                if at:
                    history.append({"kind": kind, "as_of": at, "source": "claim_board",
                                    "source_ref": f"{CLAIMS_REL}/{claim.get('claim_id')}.json"})
        evidence = coordination.evidence_for_pr(evidence_events, number, head)
        invalid_kinds = {record["kind"] for record in invalid_evidence
                         if head and record["head_sha"] == head and record["pr_number"] == number}
        if invalid_kinds:
            unknown = coordination.evidence_for_pr([], number, head)
            for kind, field in ((coordination.REVIEW_KIND, "review"), (coordination.CI_KIND, "ci")):
                if kind in invalid_kinds:
                    evidence[field] = {**unknown[field], "source": "coordinator_ledger",
                                       "gap": f"invalid_{field}_timestamp"}
        public_approvals = []
        for record in approvals:
            if record.get("schema") != "PrMergeDigestApproval@v1":
                continue
            for approved in record.get("items") or []:
                if not isinstance(approved, Mapping) or _number(approved.get("pr")) != number:
                    continue
                approved_head = approved.get("head_sha")
                if not isinstance(approved_head, str) or not SHA.fullmatch(approved_head):
                    continue
                at = _iso(record.get("approved_at"))
                if not at:
                    continue
                ident = record.get("approval_id")
                ident = ident if isinstance(ident, str) and SAFE_ID.fullmatch(ident) else None
                public = {"approval_id": ident, "pr": number, "head_sha": approved_head,
                          "current_head": bool(head and approved_head == head), "as_of": at,
                          "source": "digest_approvals", "source_ref": APPROVALS_REL}
                public_approvals.append(public)
                history.append({**public, "kind": "operator_approval"})
        linked_plans = [{**{key: plan.get(key) for key in PLAN_FIELDS if key in plan},
                         "source": "plan_registry", "source_ref": f"{PLANS_REL}/{plan.get('id')}.md",
                         "as_of": _latest([plan.get("updated_at"), plan.get("approved_at")])}
                        for plan in plans if _number(plan.get("pr")) == number
                        or (branch and plan.get("branch") == branch)
                        or (plan.get("claim") and plan.get("claim") in {c.get("claim_id") for c in matches})]
        released = pr.get("released") if isinstance(pr.get("released"), Mapping) else None
        release_at = _iso((released or {}).get("at"))
        release_gap = None if released and release_at else "release_membership_not_observed"
        release_value = {key: released.get(key) for key in ("sha", "at", "basis")} if released else None
        if release_value:
            release_value["at"] = release_at
        exact_served = (isinstance(serving.get("sha"), str) and SHA.fullmatch(serving["sha"])
                        and health.get("sha") == serving["sha"])
        verified_at = _iso(health.get("at"))
        release_time, verified_time, now_time = _parse(release_at), _parse(verified_at), _parse(now)
        live = bool(released and release_time and pr.get("served_contains") is True and exact_served
                    and health.get("ok") is True and verified_time and now_time
                    and release_time <= verified_time <= now_time)
        live_gap = None if live else ("served_membership_not_observed" if pr.get("served_contains") is not True
                                      else "served_health_not_bound" if not exact_served
                                      else "served_health_not_verified")
        if release_at:
            history.append({"kind": "released", "as_of": release_at, "source": "release_pins",
                            "source_ref": (released or {}).get("basis"), "sha": (released or {}).get("sha")})
        if live:
            history.append({"kind": "verified_live", "as_of": verified_at, "source": "deploy_receipt",
                            "source_ref": "deploy_receipt.json", "sha": serving.get("sha")})
        history.sort(key=lambda row: (_sort_time(row.get("as_of")), str(row.get("source_ref") or "")))
        row_gaps = []
        if len(history) > MAX_HISTORY:
            row_gaps.append("timeline_truncated")
        owner_value = {key: (owner or {}).get(key) for key in ("session", "agent", "vendor", "coordinator", "claim_id", "task")}
        routed = _routing(owner or {}, registry, source_gaps)
        by_pr[number] = {
            "owner": _fact(owner_value if owner else None, "claim_board", owner_at,
                           None if owner and owner.get("session") else "claim_owner_not_recorded"),
            "last_activity": _fact(_claim_time(owner or {}), "claim_board+claim_worklog",
                                   _claim_time(owner or {}),
                                   None if _claim_time(owner or {}) else "activity_timestamp_not_recorded"),
            "coordinator": routed,
            "claim_ids": [c.get("claim_id") for c in matches],
            "active_claim_ids": [c.get("claim_id") for c in matches if c.get("claim_id") in active],
            "next_action": _fact(wl.get("next_step"), "claim_worklog", wl.get("last_entry_at"),
                                 None if wl.get("next_step") else "worklog_next_step_not_recorded"),
            "blocker": _blocker(wl),
            "open_blocker_count": _fact(wl.get("blockers"), "claim_worklog", wl.get("last_entry_at"),
                                        None if "blockers" in wl else "worklog_not_available"),
            "review": evidence["review"], "ci": evidence["ci"],
            "approvals": public_approvals,
            "approval": _fact(None if source_gaps.get("digest_approvals") else
                              any(a["current_head"] for a in public_approvals), "digest_approvals",
                              _latest(a["as_of"] for a in public_approvals if a["current_head"]),
                              "approval_source_unavailable" if source_gaps.get("digest_approvals") else None),
            "plans": linked_plans,
            "plan_link": _fact([p.get("id") for p in linked_plans], "plan_registry",
                               _latest(p["as_of"] for p in linked_plans),
                               None if linked_plans else "plan_link_not_recorded"),
            "timeline": history[-MAX_HISTORY:], "gaps": row_gaps,
            "released": _fact(release_value, "release_pins", release_at, release_gap),
            "live": _fact(live, "served_release+deploy_receipt", verified_at if live else None, live_gap),
        }
    current_claims = [c for raw, c in zip(claims, public_claims) if not _terminal(raw)]
    agents, agents_complete, nudges_complete, agents_gap = _agent_rows(
        current_claims, active, tracked, events, now, registry, source_gaps)
    if agents_gap:
        source_gaps["agent_facts"] = agents_gap
    nudge_times = [e.get("ts") for e in events if e.get("kind") == "nudge" and e.get("by") == "agent-nudger"
                   and _parse(e.get("ts")) is not None and _parse(e.get("ts")) <= now]
    nudger_at = _latest([*(r.get("changed_at") for r in tracked.values()), *nudge_times])
    sources = {
        "nudger_state": {**_source(NUDGER_REL, nudger_at, source_gaps.get("nudger_state")),
                         "complete": not bool(source_gaps.get("nudger_state") or source_gaps.get("coordinator_ledger") or agents_gap),
                         "as_of_basis": "recorded_screen_change_or_nudge_event"},
        "worklogs": _source(CLAIMS_REL, _latest((c.get("worklog") or {}).get("last_entry_at") for c in public_claims),
                             source_gaps.get("worklogs")),
        "claims": _source(CLAIMS_REL, _latest(_claim_time(c) for c in public_claims), source_gaps.get("claims")),
        "coordination_registry": _source(REGISTRY_REL, registry.get("updated_at"),
                                         source_gaps.get("coordination_registry")),
        "coordinator_ledger": _source(LEDGER_REL, _latest(e.get("observed_at") or e.get("ts") for e in events),
                                      source_gaps.get("coordinator_ledger")),
        "digest_approvals": _source(APPROVALS_REL, _latest(r.get("approved_at") for r in approvals),
                                    source_gaps.get("digest_approvals")),
        "plans": _source(PLANS_REL, _latest(p.get("updated_at") or p.get("approved_at") for p in plans),
                          source_gaps.get("plans")),
        "releases": _source("census_release_membership", _latest([serving.get("since"), health.get("at")]),
                             source_gaps.get("releases")),
    }
    for name, reason in source_gaps.items():
        if name not in sources:
            sources[name] = _source(name, None, reason)
    gaps = [{"source": name, "reason": value["gap"]} for name, value in sources.items() if value.get("gap")]
    work_kinds = {"branch_uploaded", "publication_observation", "stage_transition", "review_started", "approval_started", "checks_started"}
    work_events = [_public_event(event, index, "") for index, event in enumerate(events, 1)
                   if event.get("kind") in work_kinds and _event_pr(event) is None]
    return {"schema": SCHEMA, "by_pr": by_pr, "claims": public_claims, "active_claim_ids": active,
            "work_events": work_events,
            "default_coordinator": _fact(registry.get("lead"), "coordinator_registry", registry.get("updated_at"),
                                         source_gaps.get("coordination_registry")),
            "plans": inventory, "agents": agents, "agents_complete": bool(agents_complete),
            "nudges_complete": bool(nudges_complete),
            "agents_status": "OK" if agents_complete else ("PARTIAL" if agents else "UNAVAILABLE"),
            "sources": sources, "gaps": gaps, "as_of": _latest(s["as_of"] for s in sources.values()),
            "captured_at": _iso(now), "stale_claim_hours": stale_claim_hours,
            "owner_coverage": {"prs_with_claim": owner_candidates, "owner_filled": owner_filled,
                               "pct": round(owner_filled / owner_candidates * 100, 1) if owner_candidates else None}}


def _safe_path(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        relative = path.relative_to(root)
    except (OSError, ValueError):
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    return True


def _jsonl(path: Path, root: Path | None = None) -> tuple[list[dict], str | None]:
    if path.is_symlink() or (root is not None and not _safe_path(root, path)):
        return [], "unsafe_symlink"
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return [], "missing"
    except OSError:
        return [], "unreadable"
    if len(raw) > MAX_BYTES:
        return [], "byte_budget_exceeded"
    try:
        lines = raw.decode("utf-8").splitlines()
        if len(lines) > MAX_EVENTS:
            return [], "event_budget_exceeded"
        rows = [json.loads(line) for line in lines if line.strip()]
        if any(not isinstance(row, dict) for row in rows):
            return [], "corrupt"
    except (UnicodeDecodeError, ValueError):
        return [], "corrupt"
    return rows, None


def _plans(root: Path) -> tuple[list[dict], str | None]:
    """Read just JSON-scalar frontmatter emitted by the existing plan registry.

    Never imports its writer, reads the body into a document, or invents a plan.
    """
    directory = root / PLANS_REL
    if not _safe_path(root, directory):
        return [], "unsafe_plan_path"
    if not directory.is_dir():
        return [], "missing"
    paths = []
    for path in directory.glob("*.md"):
        paths.append(path)
        if len(paths) > MAX_PLANS:
            return [], "plan_budget_exceeded"
    plans, used = [], 0
    for path in sorted(paths):
        if path.is_symlink() or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", path.stem):
            return [], "unsafe_plan_path"
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_PLAN_BYTES + 1)
        except OSError:
            return [], "unreadable"
        used += len(raw)
        if len(raw) > MAX_PLAN_BYTES or used > MAX_BYTES:
            return [], "byte_budget_exceeded"
        try:
            lines = raw.decode("utf-8").splitlines()
            if not lines or lines[0].strip() != "---":
                return [], "corrupt_frontmatter"
            front, closed = {}, False
            for line in lines[1:]:
                if line.strip() == "---":
                    closed = True
                    break
                key, sep, value = line.partition(":")
                if sep and key.strip() in PLAN_FIELDS:
                    front[key.strip()] = json.loads(value.strip())
            if not closed or any(isinstance(v, (dict, list)) for v in front.values()):
                return [], "corrupt_frontmatter"
        except (UnicodeDecodeError, ValueError):
            return [], "corrupt_frontmatter"
        if front.get("id") and front["id"] != path.stem:
            return [], "plan_id_mismatch"
        front["id"] = path.stem
        plans.append(front)
    return plans, None


def _registry(root: Path) -> tuple[dict | None, str | None]:
    path = root / REGISTRY_REL
    if not _safe_path(root, path):
        return None, "registry_unsafe_path"
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_REGISTRY_BYTES + 1)
    except FileNotFoundError:
        return None, "registry_missing"
    except OSError:
        return None, "registry_unreadable"
    if len(raw) > MAX_REGISTRY_BYTES:
        return None, "registry_byte_budget_exceeded"
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, "registry_corrupt"
    public, gap = _registry_view(value)
    return public if not gap else None, gap


def _nudger(root: Path, now: datetime) -> tuple[dict | None, str | None]:
    path = root / NUDGER_REL
    if not _safe_path(root, path):
        return None, "nudger_state_unsafe_path"
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_NUDGER_BYTES + 1)
    except FileNotFoundError:
        return None, "nudger_state_missing"
    except OSError:
        return None, "nudger_state_unreadable"
    if len(raw) > MAX_NUDGER_BYTES:
        return None, "nudger_state_byte_budget_exceeded"
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, "nudger_state_corrupt"
    public, gap = _nudger_view(value, now)
    return public if not gap else None, gap


def _worklogs(root: Path, prs: list[Mapping], claims: list[Mapping], now: datetime,
              stale_hours: float) -> tuple[list[dict], str | None]:
    """Selected current owners/fresh claims only; never trust a submitted worklog path."""
    selected = set()
    for raw in claims[:MAX_CLAIMS]:
        beat = _parse(raw.get("heartbeat_at"))
        if not _terminal(raw) and beat is not None and 0 <= (now - beat).total_seconds() <= stale_hours * 3600:
            selected.add(raw.get("claim_id"))
    for pr in prs[:MAX_PRS]:
        number, branch = _number(pr.get("number")), pr.get("branch") or pr.get("headRefName")
        matches = [c for c in claims[:MAX_CLAIMS] if number and _number(c.get("pr_number") or c.get("pr")) == number
                   or (branch and c.get("branch") == branch and not _number(c.get("pr_number") or c.get("pr")))]
        if matches:
            owner = max(matches, key=lambda c: (_sort_time(_claim_time(c)), _sort_time(c.get("started_at"))))
            selected.add(owner.get("claim_id"))
    out, gaps, read_count = [], [], 0
    for raw in claims:
        claim = dict(raw)
        old = dict(raw["worklog"]) if isinstance(raw.get("worklog"), Mapping) else {}
        count = old.get("blockers")
        if raw.get("claim_id") not in selected or count == 0 or isinstance(old.get("blocker_text"), str):
            out.append(claim)
            continue
        ident = raw.get("claim_id")
        gap = None
        if not isinstance(ident, str) or not CLAIM_ID.fullmatch(ident):
            gap = "worklog_claim_id_invalid"
        elif read_count >= MAX_WORKLOG_READS:
            gap = "worklog_read_budget_exceeded"
        else:
            path = root / CLAIMS_REL / f"{ident}.worklog.md"
            if not _safe_path(root, path):
                gap = "worklog_unsafe_path"
            else:
                read_count += 1
                view, gap = coordination.read_worklog(path, root / CLAIMS_REL)
                if gap is None or gap == "worklog_truncated":
                    text = view.get("blocker")
                    observed_count = len(view.get("blockers") or [])
                    if gap and isinstance(count, int):
                        observed_count = max(count, observed_count)
                    old.update({"exists": True, "blockers": observed_count, "blocker_text": text,
                                "last_entry_at": view.get("last_entry_at") or old.get("last_entry_at")})
        if gap:
            old["blocker_gap"] = gap
            gaps.append(gap)
        else:
            old.pop("blocker_gap", None)
        claim["worklog"] = old
        out.append(claim)
    return out, ";".join(sorted(set(gaps))) or None


def load(state_root: Path, prs: list[Mapping], claims: list[Mapping], now: datetime, *,
         release_reader: Any = None, health: Mapping | None = None, serving: Mapping | None = None,
         stale_claim_hours: float = 24.0, source_gaps: Mapping[str, str] | None = None) -> dict:
    """Read bounded local sources; census already owns all GitHub/git membership work."""
    root = Path(state_root)
    events, event_gap = _jsonl(root / LEDGER_REL, root)
    approvals, approval_gap = _jsonl(root / APPROVALS_REL, root)
    plans, plans_gap = _plans(root)
    registry, registry_gap = _registry(root)
    tracked, nudger_gap = _nudger(root, now)
    claims, worklogs_gap = _worklogs(root, prs, claims, now, stale_claim_hours)
    gaps = dict(source_gaps or {})
    gaps.update({key: value for key, value in (("coordinator_ledger", event_gap),
                                             ("digest_approvals", approval_gap), ("plans", plans_gap),
                                             ("coordination_registry", registry_gap),
                                             ("nudger_state", nudger_gap), ("worklogs", worklogs_gap)) if value})
    if serving is None:
        try:
            serving = release_reader.serving() if release_reader is not None else {}
        except Exception:  # noqa: BLE001 - missing identity remains a named source gap
            serving = {}
    if not serving or not serving.get("sha"):
        gaps["releases"] = "served_identity_unavailable"
    return build(prs, claims, events, approvals, plans, now, serving=serving, health=health,
                 source_gaps=gaps, stale_claim_hours=stale_claim_hours, coordination_registry=registry,
                 nudger_sessions=tracked)
