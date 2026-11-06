"""Pure nine-stage facts over already observed Work/PR/approval snapshots.

No reads, network, writes or merge authority. enrich attaches fresh per-item
coordination bundles and returns the new collection; source bundles are never
mutated. Every unknown transition keeps an explicit gap instead of using a
PR's update clock. The approvals object is the caller's exact canonical object.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Mapping

SHA = re.compile(r"[0-9a-f]{40}\Z")
STAGES = ("requested", "building", "uploaded", "pr_open", "checks", "review", "approval", "merged", "live")
REQUIRED_SOURCES = ("claims", "coordinator_ledger", "digest_approvals", "plans", "releases")


def _row(value):
    return value if isinstance(value, Mapping) else {}


def _time(value, now):
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if stamp.tzinfo is None:
        return None
    stamp = stamp.astimezone(timezone.utc)
    return stamp if stamp <= now else None


def _iso(value):
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def _head(value):
    return value if isinstance(value, str) and SHA.fullmatch(value) else None


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _number(value):
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.lstrip("#").isdigit():
        return int(value.lstrip("#")) or None
    return None


def _fact(value, source, at=None, gap=None):
    return {"value": value, "source": source, "as_of": _iso(at), "gap": gap}


def _events(bundle, now, head):
    return [event for event in bundle.get("timeline") or [] if isinstance(event, Mapping)
            and isinstance(event.get("source"), str) and event.get("source")
            and _time(event.get("as_of"), now) is not None
            and (not head or event.get("head_sha") == head)]


def _first(events, kinds, now):
    stamps = [stamp for e in events if e.get("kind") in kinds and (stamp := _time(e.get("as_of"), now)) is not None]
    return min(stamps) if stamps else None


def _last(events, kinds, now):
    stamps = [_time(e.get("as_of"), now) for e in events if e.get("kind") in kinds]
    return max(stamps) if stamps else None


def _checks(pr, head, now):
    raw = _row(pr.get("ci"))
    at = _time(raw.get("as_of"), now)
    passed, total = _count(raw.get("passed")), _count(raw.get("total"))
    gap = raw.get("gap")
    if not head or raw.get("head_sha") != head:
        gap = "checks_head_not_bound"
    elif passed is None or total is None or total == 0 or passed > total:
        gap = gap or "checks_counts_unavailable"
    elif at is None:
        gap = gap or "checks_observation_not_recorded"
    green = not gap and str(raw.get("state") or "").lower() == "green" and passed == total
    return {**raw, "head_sha": head if not gap else raw.get("head_sha"),
            "passed": passed if not gap else None, "total": total if not gap else None,
            "as_of": _iso(at), "gap": gap, "green_at": _iso(_time(raw.get("green_at") or raw.get("completed_at"), now))}, green


def _reviews(bundle, pr, head, now):
    review = dict(_row(bundle.get("review")))
    quota = _count(pr.get("review_required_count"))
    quota_source = pr.get("review_required_source")
    quota_at = _time(pr.get("review_required_as_of"), now)
    quota_gap = pr.get("review_required_gap")
    if quota_gap or not quota or not isinstance(quota_source, str) or not quota_source or quota_at is None:
        quota_gap = quota_gap or "review_requirement_unavailable"
        quota = None
    records = review.get("records")
    latest = {}
    if (not review.get("gap") and review.get("source") and review.get("head_sha") == head and head
            and review.get("evidence_class") == "reported_review_not_approval" and isinstance(records, list)):
        for record in records:
            record = _row(record)
            at = _time(record.get("observed_at"), now)
            who = record.get("reviewer_session")
            owner = _row(_row(bundle.get("owner")).get("value")).get("session")
            if (at is not None and isinstance(who, str) and who and who != "UNKNOWN" and who != owner
                    and (who not in latest or at >= latest[who][0])):
                latest[who] = (at, record.get("verdict"))
    complete = bool(quota and review.get("state") == "MERGE" and len(latest) >= quota
                    and all(v == "MERGE" for _, v in latest.values()))
    review.update(required_count=quota, required_source=quota_source, required_as_of=_iso(quota_at),
                  required_gap=quota_gap, reported_complete=complete)
    return review, complete


def _operator_member(waiting, number, head, now):
    if not number or not head:
        return None
    rows = waiting.get("actionable_items")
    if not isinstance(rows, list):
        return None
    matches = []
    for raw in rows:
        member = _row(raw)
        member_head = _head(member.get("head_sha") or member.get("source_sha") or _row(member.get("document")).get("source_sha"))
        if (_number(member.get("pr") or member.get("pr_number")) == number and member_head == head
                and member.get("next_actor") == "operator" and member.get("source")
                and _time(member.get("source_as_of") or member.get("as_of"), now) is not None):
            matches.append(member)
    return matches[0] if matches else None


def _claim_bundle(item, coordination, now):
    ids = set(_row(item.get("how")).get("claim_ids") or [])
    matches = [c for c in coordination.get("claims") or [] if isinstance(c, Mapping) and c.get("claim_id") in ids]
    active = set(coordination.get("active_claim_ids") or [])
    matches.sort(key=lambda c: (c.get("claim_id") in active,
                                _time(c.get("heartbeat_at"), now) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    claim = matches[0] if matches else {}
    owner = {k: claim.get(k) for k in ("session", "vendor", "agent", "coordinator", "claim_id")}
    beat = _time(claim.get("heartbeat_at"), now)
    worklog = _row(claim.get("worklog"))
    written = _time(worklog.get("last_entry_at"), now)
    coordinator = (_fact(claim["coordinator"], "claim_board", beat)
                   if isinstance(claim.get("coordinator"), str) and claim["coordinator"] else
                   dict(_row(coordination.get("default_coordinator"))))
    count = _count(worklog.get("blockers"))
    blocker_text = worklog.get("blocker_text") if isinstance(worklog.get("blocker_text"), str) else None
    blocker_gap = worklog.get("blocker_gap") or (None if count == 0 or blocker_text else "worklog_blocker_text_not_recorded")
    activity = max((v for v in (beat, written) if v is not None), default=None)
    return {"owner": _fact(owner if matches else None, "claim_board", beat,
                           None if matches and owner.get("session") else "claim_owner_not_recorded"),
            "coordinator": coordinator,
            "next_action": _fact(worklog.get("next_step"), "claim_worklog", written,
                                 None if worklog.get("next_step") else "worklog_next_step_not_recorded"),
            "last_activity": _fact(_iso(activity), "claim_board+claim_worklog", activity,
                                   None if activity else "activity_not_recorded"),
            "blocker": _fact(blocker_text, "claim_worklog", written, blocker_gap),
            "claim_ids": list(ids),
            "timeline": [event for event in coordination.get("work_events") or [] if isinstance(event, Mapping)
                         and (event.get("claim_id") in ids or (event.get("session") and
                              any(event.get("session") == c.get("session") and event.get("branch") == c.get("branch") for c in matches)))],
            "gaps": []}, matches


def _enrich_item(item, bundle, pr, claims, waiting, now, census_at, threshold):
    facts = dict(bundle)
    number = _number(pr.get("number") or item.get("pr_number") or _row(item.get("what")).get("pr_number"))
    head = _head(pr.get("head_sha") or pr.get("headRefOid"))
    if not head and not number:
        head = next((_head(c.get("worktree_head_sha") or c.get("head_sha")) for c in claims
                     if _head(c.get("worktree_head_sha") or c.get("head_sha"))), None)
    events = _events(bundle, now, head)
    checks, green = _checks(pr, head, now)
    review, review_complete = _reviews(bundle, pr, head, now)
    operator = _operator_member(waiting, number, head, now)
    live = _row(bundle.get("live"))
    live_at = _time(live.get("as_of"), now)
    merge_at = _time(pr.get("merged_at") or pr.get("mergedAt"), now)
    opened_at = _time(pr.get("created_at") or pr.get("createdAt"), now)
    stage, actor, since, source = "requested", "agent", None, "work_source"
    published = []
    if live.get("value") is True and not live.get("gap") and live.get("source") and live_at:
        stage, actor, since, source = "live", "coordinator", live_at, live["source"]
    elif pr.get("state") == "merged" or merge_at:
        stage, actor, since, source = "merged", "coordinator", merge_at, "github_census"
    elif number and pr:
        if pr.get("draft") or pr.get("isDraft"):
            stage, since, source = "pr_open", opened_at, "github_census"
        elif not green:
            stage, source = "checks", "github_census"
            since = (_time(_row(pr.get("ci")).get("started_at"), now)
                     if head and _row(pr.get("ci")).get("head_sha") == head else None)
            since = since or _last(events, {"checks_started"}, now)
        else:
            stage, actor, source = "review", "coordinator", "github_census+review_ledger"
            since = _last(events, {"review_started"}, now)
            if review_complete and operator:
                stage, actor, source, since = "approval", "operator", "canonical_operator_approvals", None
                since = _last(events, {"approval_started"}, now)
    else:
        published = [e for e in events if e.get("source") and head and e.get("head_sha") == head
                     and (e.get("kind") == "branch_uploaded" or
                          (e.get("kind") == "publication_observation" and e.get("state") in ("published", "uploaded")))]
        building = [_time(_row(c.get("stages")).get("building"), now) for c in claims]
        building = [at for at in building if at is not None]
        if published:
            stage, source = "uploaded", "publication_ledger"
            since = min(_time(e["as_of"], now) for e in published)
        elif building or any(c.get("stage") == "building" for c in claims) or item.get("stage") in ("building", "claimed"):
            stage, source = "building", "claim_board"
            since = min(building) if building else _first(events, {"building"}, now)
    transitions = [e for e in events if e.get("kind") == "stage_transition" and e.get("to_stage") == stage and e.get("source")]
    if transitions:
        since = max(_time(e["as_of"], now) for e in transitions)
        source = "stage_transition_ledger"
    created = opened_at
    created_source = "github_census"
    if not number:
        created = _time(item.get("created_at") or _row(item.get("when")).get("created_at"), now)
        created_source = "task_board"
        if created is None:
            created_times = [_time(c.get("started_at"), now) for c in claims]
            created_times = [at for at in created_times if at is not None]
            created = min(created_times) if created_times else None
            created_source = "claim_board"
        if created is None:
            created = _first([{"kind": c.get("stage"), "as_of": c.get("at")} for c in item.get("cells") or [] if isinstance(c, Mapping)], {"proposed", "queued"}, now)
            created_source = "work_stage_history"
    if stage == "requested" and since is None:
        since, source = created, created_source
    clock = live_at if stage == "live" else census_at if number else since
    stage_gap = None
    if number and not pr and stage != "live":
        stage, actor, stage_gap = None, "unknown", "pr_not_in_census"
    action = {"requested": "Assign this requested work.", "building": "Continue implementation and record the next step.",
              "uploaded": "Open or locate the pull request for this exact uploaded head.", "pr_open": "Finish this draft pull request.",
              "checks": "Resolve or wait for the current head's checks.", "review": "Coordinate the required exact-head reviews and governed merge.",
              "approval": "Review the exact version in the canonical approval queue.", "merged": "Observe served membership and deployment verification.",
              "live": "No action: served and verified."}.get(stage, "Locate current source evidence for this work.")
    owner_session = _row(_row(bundle.get("owner")).get("value")).get("session")
    actor_source = source
    if actor == "agent" and not owner_session:
        actor, actor_source = "coordinator", "work_assignment_rule"
        action = "Assign an engineer to this work before its next implementation step."
    next_action = _fact(action, source, clock, None if clock else "observation_not_recorded")
    worklog_next = _row(bundle.get("next_action"))
    if (stage in ("building", "uploaded", "pr_open", "checks") and owner_session
            and worklog_next.get("source") == "claim_worklog" and not worklog_next.get("gap")
            and isinstance(worklog_next.get("value"), str) and worklog_next["value"].strip()
            and _time(worklog_next.get("as_of"), now) is not None):
        next_action = dict(worklog_next)
    if stage == "approval" and operator and isinstance(operator.get("next_action"), str) and operator["next_action"].strip():
        next_action = _fact(operator["next_action"], operator["source"],
                            _time(operator.get("source_as_of") or operator.get("as_of"), now))
    facts["gaps"] = list(bundle.get("gaps") or [])
    if (stage == "building" or (not number and head)) and not published:
        facts["gaps"].append({"source": "publication_ledger", "reason": "publication_not_observed"})
    if review.get("required_gap") and number:
        facts["gaps"].append({"source": "review_requirement", "reason": review["required_gap"]})
    facts.update(current_stage=_fact(stage, source, clock, stage_gap or (None if clock else "observation_not_recorded")), stage_since=_fact(_iso(since), source, since, None if since else "transition_not_recorded"),
                 created_at=_fact(_iso(created), created_source, created, None if created else "creation_not_recorded"),
                 next_actor=_fact(actor, actor_source, clock, stage_gap or (None if clock else "observation_not_recorded")), head_sha=head, ci=checks, review=review,
                 next_action=next_action, pr_number=number,
                 stuck=_fact(None, "stage_clock", since, "stuck_threshold_or_clock_unavailable"))
    if stage == "checks" and since:
        facts["stage_since"]["basis"] = "checks_run_started"
    if isinstance(threshold, (int, float)) and not isinstance(threshold, bool) and math.isfinite(threshold) and threshold > 0 and since:
        facts["stuck"] = {**_fact(stage != "live" and (now - since).total_seconds() / 60 > threshold, "stage_clock", since),
                          "basis": "stage", "threshold_minutes": threshold}
    return facts


def enrich(items, coordination, prs, waiting, now, *, census_as_of=None, census_warning=None, stuck_after_minutes=120):
    """Attach current facts to in-memory items and return a fresh collection (no IO).

    `approvals` aliases the exact canonical waiting object; no second member set
    or count is constructed. Current facts are descriptive, never merge grants.
    """
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("aware evaluation clock required")
    now = now.astimezone(timezone.utc)
    output = dict(coordination)
    output["by_pr"] = dict(coordination.get("by_pr") or {})
    output["by_item"] = {}
    output["approvals"] = waiting
    output["stuck_after_minutes"] = stuck_after_minutes
    census_at = _time(census_as_of, now)
    output["sources"] = {**_row(coordination.get("sources")), "pr_census": {
        "source": "github_pr_census", "as_of": _iso(census_at),
        "status": "OK" if census_at and not census_warning else "PARTIAL",
        "gap": str(census_warning)[:200] if census_warning else (None if census_at else "census_observation_unavailable"),
    }}
    source_clocks = [_time(coordination.get("as_of"), now), census_at]
    output["as_of"] = _iso(max((clock for clock in source_clocks if clock is not None), default=None))
    by_number = {_number(p.get("number")): p for p in prs if isinstance(p, Mapping) and _number(p.get("number"))}
    for item in items:
        number = _number(item.get("pr_number") or _row(item.get("what")).get("pr_number"))
        bundle = _row(item.get("coordination")) or _row(output["by_pr"].get(number))
        extra, claims = _claim_bundle(item, coordination, now)
        if not bundle:
            bundle = extra
        if not claims:
            ids = set(bundle.get("claim_ids") or [])
            claims = [c for c in coordination.get("claims") or [] if isinstance(c, Mapping) and c.get("claim_id") in ids]
        facts = _enrich_item(item, bundle, by_number.get(number, {}), claims, waiting, now, census_at, stuck_after_minutes)
        item["coordination"] = facts
        output["by_item"][item.get("id")] = facts
        if number:
            output["by_pr"][number] = facts
    missing = [name for name in REQUIRED_SOURCES if not _row(_row(coordination.get("sources")).get(name))]
    gaps = list(coordination.get("gaps") or [])
    gaps.extend({"source": name, "reason": "source_not_supplied"} for name in missing)
    for name, source in _row(coordination.get("sources")).items():
        source = _row(source)
        if source.get("gap") or source.get("status") not in ("OK", "AVAILABLE"):
            gap = {"source": name, "reason": source.get("gap") or "source_incomplete"}
            if gap not in gaps:
                gaps.append(gap)
    if census_at is None:
        gaps.append({"source": "census", "reason": "census_observation_unavailable"})
    if census_warning:
        gaps.append({"source": "census", "reason": str(census_warning)[:200]})
    members = waiting.get("actionable_items")
    members_complete = (isinstance(members, list) and type(waiting.get("actionable_count")) is int
                        and waiting["actionable_count"] == len(members))
    if waiting.get("complete") is not True or not members_complete:
        gaps.append({"source": "operator_approvals", "reason": "canonical_queue_incomplete"})
    output.update(gaps=gaps, complete=not gaps, status="OK" if not gaps else "PARTIAL")
    return output
