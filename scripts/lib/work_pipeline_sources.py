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

from scripts.lib import releases_coordination as coordination

SCHEMA = "WorkPipelineSources@v1"
LEDGER_REL = "data/coordination/coordinator/ledger.jsonl"
APPROVALS_REL = "data/runtime/pr_merge_telegram/digest_approvals.jsonl"
PLANS_REL = "data/coordination/plans"
CLAIMS_REL = "data/coordination/claims"
MAX_BYTES = 2_000_000
MAX_EVENTS = 20_000
MAX_PLANS = 200
MAX_PLAN_BYTES = 256_000
MAX_PRS = 200
MAX_CLAIMS = 1000
MAX_HISTORY = 100
SHA = re.compile(r"[0-9a-f]{40}\Z")
SAFE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,160}\Z")
TIMELINE_KINDS = frozenset({"dispatch", "assign", "check_request", "check_ok", "check_block",
                            "review_verdict", "review_receipt_recorded", "ci_observation",
                            "approval_recorded", "approval_record", "operator_approval_actual", "merge", "merged",
                            "merge_result", "verified_merge", "live_observation", "pr_open", "nudge",
                            "decision_pending", "decision_needed", "decision_resolved"})
PLAN_FIELDS = ("id", "title", "author_session", "vendor", "approved_at", "status", "claim", "branch",
               "pr", "updated_at", "stalled_since")
CLAIM_FIELDS = ("claim_id", "session", "agent", "vendor", "coordinator", "task", "branch", "pr", "pr_number", "state", "status",
                "stage", "stages", "started_at", "heartbeat_at", "ended_at", "head_sha", "worktree_head_sha", "worklog")


def _iso(value: Any) -> str | None:
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
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _latest(values: Iterable[Any]) -> str | None:
    stamps = [stamp for value in values if (stamp := _iso(value))]
    return max(stamps) if stamps else None


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
    return {"kind": row.get("kind"), "pr": _event_pr(row), "head_sha": row_head,
            "current_head": bool(row_head and head and row_head == head),
            "actor": _text(row.get("reviewer_session") or row.get("actor_session") or row.get("coordinator"), 100),
            "verdict": _text(row.get("verdict"), 40), "state": _text(row.get("state"), 40),
            "source": "coordinator_ledger", "source_ref": f"{LEDGER_REL}#event-{index}",
            "as_of": _iso(row.get("observed_at") or row.get("ts"))}


def _evidence_events(events: list[Mapping]) -> tuple[list[dict], bool]:
    """Public typed evidence only, normalized before the canonical exact-head fold."""
    out, invalid = [], False
    for row in events:
        if row.get("kind") not in (coordination.REVIEW_KIND, coordination.CI_KIND):
            continue
        at = _iso(row.get("observed_at") or row.get("ts"))
        if not at:
            invalid = True
            continue
        public = {key: row.get(key) for key in ("kind", "pr_number", "head_sha", "evidence_class",
                  "verdict", "reviewer_session", "receipt_path", "receipt_sha256", "state", "source")}
        public["observed_at"] = at
        public["workflows"] = [{key: _text(workflow.get(key), 200) for key in ("name", "status", "conclusion")}
                               for workflow in row.get("workflows") or [] if isinstance(workflow, Mapping)]
        out.append(public)
    return out, invalid


def _source(name: str, at: Any, gap: str | None = None) -> dict:
    return {"source": name, "as_of": _iso(at), "status": "UNAVAILABLE" if gap else "OK", "gap": gap}


def build(prs: list[Mapping], claims: list[Mapping], events: list[Mapping], approvals: list[Mapping],
          plans: list[Mapping], now: datetime, *, serving: Mapping | None = None,
          health: Mapping | None = None, source_gaps: Mapping[str, str] | None = None,
          stale_claim_hours: float = 24.0) -> dict:
    """Pure public facts over snapshots. Historical owners survive stale/ended claims.

    Each PR supplies released={at,sha,basis} from the census's earliest apply
    receipt, plus served_contains from that same census snapshot. No membership
    is inferred from a merge timestamp or an unrelated successful deployment.
    """
    serving, health, source_gaps = serving or {}, health or {}, dict(source_gaps or {})
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
    public_claims = [{key: c.get(key) for key in CLAIM_FIELDS if key in c} for c in claims]
    active = []
    for claim in public_claims:
        stamp = _iso(claim.get("heartbeat_at"))
        age = (now - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds() if stamp else None
        if (coordination.is_live(claim) and age is not None and 0 <= age <= stale_claim_hours * 3600
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
        matches.sort(key=lambda c: (_claim_time(c) or "", _iso(c.get("started_at")) or ""), reverse=True)
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
        live = bool(released and release_at and pr.get("served_contains") is True and exact_served
                    and health.get("ok") is True and verified_at and verified_at >= release_at)
        live_gap = None if live else ("served_membership_not_observed" if pr.get("served_contains") is not True
                                      else "served_health_not_bound" if not exact_served
                                      else "served_health_not_verified")
        if release_at:
            history.append({"kind": "released", "as_of": release_at, "source": "release_pins",
                            "source_ref": (released or {}).get("basis"), "sha": (released or {}).get("sha")})
        if live:
            history.append({"kind": "verified_live", "as_of": verified_at, "source": "deploy_receipt",
                            "source_ref": "deploy_receipt.json", "sha": serving.get("sha")})
        history.sort(key=lambda row: (row.get("as_of") or "", str(row.get("source_ref") or "")))
        row_gaps = []
        if len(history) > MAX_HISTORY:
            row_gaps.append("timeline_truncated")
        owner_value = {key: (owner or {}).get(key) for key in ("session", "agent", "vendor", "coordinator", "claim_id", "task")}
        by_pr[number] = {
            "owner": _fact(owner_value if owner else None, "claim_board", owner_at,
                           None if owner and owner.get("session") else "claim_owner_not_recorded"),
            "last_activity": _fact(_claim_time(owner or {}), "claim_board+claim_worklog",
                                   _claim_time(owner or {}),
                                   None if _claim_time(owner or {}) else "activity_timestamp_not_recorded"),
            "coordinator": _fact((owner or {}).get("coordinator"), "claim_board", owner_at,
                                 None if (owner or {}).get("coordinator") else "coordinator_source_not_recorded"),
            "claim_ids": [c.get("claim_id") for c in matches],
            "active_claim_ids": [c.get("claim_id") for c in matches if c.get("claim_id") in active],
            "next_action": _fact(wl.get("next_step"), "claim_worklog", wl.get("last_entry_at"),
                                 None if wl.get("next_step") else "worklog_next_step_not_recorded"),
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
    sources = {
        "claims": _source(CLAIMS_REL, _latest(_claim_time(c) for c in public_claims), source_gaps.get("claims")),
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
    return {"schema": SCHEMA, "by_pr": by_pr, "claims": public_claims, "active_claim_ids": active,
            "plans": inventory,
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


def load(state_root: Path, prs: list[Mapping], claims: list[Mapping], now: datetime, *,
         release_reader: Any = None, health: Mapping | None = None, serving: Mapping | None = None,
         stale_claim_hours: float = 24.0) -> dict:
    """Read bounded local sources; census already owns all GitHub/git membership work."""
    root = Path(state_root)
    events, event_gap = _jsonl(root / LEDGER_REL, root)
    approvals, approval_gap = _jsonl(root / APPROVALS_REL, root)
    plans, plans_gap = _plans(root)
    gaps = {key: value for key, value in (("coordinator_ledger", event_gap),
                                         ("digest_approvals", approval_gap), ("plans", plans_gap)) if value}
    if serving is None:
        try:
            serving = release_reader.serving() if release_reader is not None else {}
        except Exception:  # noqa: BLE001 - missing identity remains a named source gap
            serving = {}
    if not serving or not serving.get("sha"):
        gaps["releases"] = "served_identity_unavailable"
    return build(prs, claims, events, approvals, plans, now, serving=serving, health=health,
                 source_gaps=gaps, stale_claim_hours=stale_claim_hours)
