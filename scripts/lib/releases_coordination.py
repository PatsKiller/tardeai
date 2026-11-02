"""Read-only coordination view for the Releases page (additive, 2026-11-02).

The Releases board already lists open PRs. This module answers the operator's next question — *whose work
is this, where is it, what is it waiting on* — from sources that already exist, without inventing a store
and without granting anything.

Sources, all read-only:

* the canonical coordinator ledger ``data/coordination/coordinator/ledger.jsonl``, for the typed evidence
  events the lead records: ``review_receipt_recorded`` and ``ci_observation``;
* the claim board, for owner / branch / current task / blocker / next step.

Rules that matter more than the shape:

1. **Head binding.** Review and CI evidence only counts when its ``head_sha`` equals the row's head. A
   record for another head is ``UNKNOWN`` with ``gap: "head_changed"`` — never attached to the new head.
2. **No inference.** A row's ``merge_state: CLEAN`` is not CI evidence; ``is_draft: false`` is not a
   review; a freeform ledger note is not either. Only the two typed kinds count.
3. **Source time, not read time.** ``as_of`` comes from the newest record actually used; ``captured_at``
   is when this view read the sources. They are deliberately different fields.
4. **Nothing here is approval.** Every evidence entry carries
   ``evidence_class: "reported_review_not_approval"``; no merge authority is created.

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

SCHEMA = "ReleasesCoordination@v1"
EVIDENCE_CLASS = "reported_review_not_approval"
REVIEW_KIND = "review_receipt_recorded"
CI_KIND = "ci_observation"
CI_STATES = ("GREEN", "RED", "PENDING", "SKIPPED", "UNKNOWN")
UNKNOWN = "UNKNOWN"


def _iso(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _parse(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _newest(values: Iterable[Optional[str]]) -> Optional[str]:
    best: Optional[datetime] = None
    best_raw: Optional[str] = None
    for raw in values:
        dt = _parse(raw)
        if dt is not None and (best is None or dt > best):
            best, best_raw = dt, raw
    return best_raw


# ------------------------------------------------------------------- the canonical ledger
def read_ledger(path: Path) -> tuple[list[dict[str, Any]], Optional[str]]:
    """(events, gap). Unreadable or absent is a gap, never an empty success."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], "ledger_absent"
    except OSError as exc:
        return [], f"ledger_unreadable:{type(exc).__name__}"
    events = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            events.append(row)
    return events, None


def _truthy_class(row: Mapping[str, Any]) -> bool:
    return str(row.get("evidence_class") or "") == EVIDENCE_CLASS


def evidence_for_pr(events: Iterable[Mapping[str, Any]], pr_number: int, head_sha: str) -> dict[str, Any]:
    """Head-bound review and CI evidence for one PR.

    Only records that name this PR *and* this exact head count. Anything else is reported as a gap rather
    than being attached to the current head.
    """
    reviews: list[dict[str, Any]] = []
    ci: Optional[dict[str, Any]] = None
    stale_reviews = stale_ci = 0
    for row in events:
        try:
            if int(row.get("pr_number") or 0) != int(pr_number):
                continue
        except (TypeError, ValueError):
            continue
        kind = str(row.get("kind") or "")
        row_head = str(row.get("head_sha") or "")
        if kind == REVIEW_KIND and _truthy_class(row):
            if row_head != head_sha:
                stale_reviews += 1
                continue
            reviews.append({
                "verdict": str(row.get("verdict") or UNKNOWN),
                "reviewer_session": str(row.get("reviewer_session") or UNKNOWN),
                "observed_at": _iso(row.get("observed_at") or row.get("ts")),
                "receipt_path": row.get("receipt_path"),
                "receipt_sha256": row.get("receipt_sha256"),
                "evidence_class": EVIDENCE_CLASS,
            })
        elif kind == CI_KIND and row_head == head_sha:
            state = str(row.get("state") or UNKNOWN).upper()
            candidate = {
                "state": state if state in CI_STATES else UNKNOWN,
                "head_sha": row_head,
                "as_of": _iso(row.get("observed_at") or row.get("ts")),
                "observed_at": _iso(row.get("observed_at") or row.get("ts")),
                "source": str(row.get("source") or UNKNOWN),
                "workflows": list(row.get("workflows") or []),
                "evidence_class": EVIDENCE_CLASS,
            }
            if ci is None or (_parse(candidate["observed_at"]) or datetime.min.replace(tzinfo=timezone.utc)) >= (
                    _parse(ci["observed_at"]) or datetime.min.replace(tzinfo=timezone.utc)):
                ci = candidate
            continue
        elif kind == CI_KIND:
            stale_ci += 1

    # Latest record PER REVIEWER, then BLOCK/CHANGES dominates. A reviewer who first MERGEs and later
    # BLOCKs must end as BLOCK; an empty or unreadable verdict must never read as MERGE (codex review of
    # d14ffa86b, 2026-11-02: a real probe printed state=MERGE with verdicts ['BLOCK']).
    latest: dict[str, dict[str, Any]] = {}
    for row in reviews:
        who = row["reviewer_session"]
        prior = latest.get(who)
        if prior is None or (_parse(row["observed_at"]) or datetime.min.replace(tzinfo=timezone.utc)) >= (
                _parse(prior["observed_at"]) or datetime.min.replace(tzinfo=timezone.utc)):
            latest[who] = row
    effective = list(latest.values())
    verdicts = [str(r["verdict"]).upper() for r in effective]
    if not effective:
        state = UNKNOWN
    elif any(v in ("BLOCK", "CHANGES", "CHANGES_REQUESTED", "REJECT") for v in verdicts):
        state = "BLOCK"
    elif all(v == "MERGE" for v in verdicts):
        state = "MERGE"
    else:
        state = UNKNOWN          # an unrecognised verdict is not a merge
    sessions = sorted(latest)
    review = {
        "state": state,
        "verdicts": verdicts,
        "all_verdicts": [r["verdict"] for r in reviews],
        "reviewers": sessions,
        "independent_reviewers": len(sessions),
        "records": effective,
        "head_sha": head_sha if effective else None,
        "as_of": _newest(r["observed_at"] for r in effective),
        "source": "coordinator_ledger" if reviews else "none",
        "gap": None if reviews else ("stale_review_for_other_head" if stale_reviews else "no_review_record"),
        "evidence_class": EVIDENCE_CLASS,
    }
    if ci is None:
        ci = {"state": UNKNOWN, "head_sha": None, "as_of": None, "source": "none",
              "workflows": [], "evidence_class": EVIDENCE_CLASS,
              "gap": "stale_ci_for_other_head" if stale_ci else "no_ci_observation"}
    return {"review": review, "ci": ci}


# ------------------------------------------------------------------------- claim board view
def read_claims(claims_dir: Path) -> tuple[list[dict[str, Any]], Optional[str]]:
    try:
        files = sorted(claims_dir.glob("*.json"))
    except OSError as exc:
        return [], f"claims_unreadable:{type(exc).__name__}"
    if not files:
        return [], "claims_absent"
    out = []
    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict):
            out.append(doc)
    return out, None


#: States that mean the work is over. An ended or done claim is history, not a current agent
#: (codex review of d14ffa86b: 257 "agents", 112 of them DONE).
ENDED_STATES = frozenset({"merged", "done", "ended", "abandoned", "closed", "released", "complete", "completed"})


def is_live(doc: Mapping[str, Any]) -> bool:
    if doc.get("ended_at"):
        return False
    state = str(doc.get("_state") or doc.get("status") or doc.get("state") or "").strip().lower()
    return state not in ENDED_STATES


def agent_rows(claims: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    seen: set[str] = set()
    for doc in claims:
        if not is_live(doc):
            continue
        session = str(doc.get("session") or "")
        key = session or str(doc.get("claim_id") or "")
        if key in seen:            # one row per session: the newest claim it holds
            continue
        seen.add(key)
        rows.append({
            "session": doc.get("session"),
            "task": doc.get("task"),
            "state": doc.get("_state") or doc.get("status") or doc.get("state") or doc.get("stage"),
            "branch": doc.get("branch"),
            "pr": doc.get("pr"),
            "head_sha": doc.get("head_sha") or doc.get("logged_sha"),
            "blocker": doc.get("blocker"),
            "next_action": doc.get("next_action") or doc.get("handoff"),
            "as_of": _iso(doc.get("heartbeat_at") or doc.get("claimed_at")),
            "source": "claims",
        })
    return rows


def build(ledger_path: Path, claims_dir: Path, prs: Iterable[Mapping[str, Any]], *,
          now: Optional[datetime] = None) -> dict[str, Any]:
    """The additive envelope plus one ``work`` object per PR row (see ``deploy_in_flight.project_pr``)."""
    captured_at = _iso(now or datetime.now(timezone.utc))
    events, ledger_gap = read_ledger(ledger_path)
    claims, claims_gap = read_claims(claims_dir)
    agents = agent_rows(claims)

    gaps = [g for g in (ledger_gap, claims_gap) if g]
    by_branch = {a["branch"]: a for a in agents if a.get("branch")}

    work: dict[int, dict[str, Any]] = {}
    for pr in prs:
        number = int(pr.get("number") or 0)
        head = str(pr.get("head_sha") or "")
        evidence = evidence_for_pr(events, number, head)
        owner = by_branch.get(str(pr.get("branch") or ""))
        local_head = str(owner.get("head_sha") or "") if owner else ""
        # A head difference is NOT proof of unpublished work: the claim's head is often stale (recorded
        # hours ago) while the push has since landed. Only an equal head is provable; anything else is
        # UNKNOWN with the claim's own head and its age exposed so a reader can judge (codex review).
        claim_head_at = (owner or {}).get("as_of")
        if not owner:
            publication = UNKNOWN
        elif local_head and head and local_head == head:
            publication = "published"
        else:
            publication = UNKNOWN
        review, ci = evidence["review"], evidence["ci"]
        work[number] = {
            "owner": (owner or {}).get("session") or UNKNOWN,
            "current_task": (owner or {}).get("task") or UNKNOWN,
            "publication_state": publication,
            "local_head": local_head or None,
            "claim_head_recorded_at": claim_head_at,
            "published_head": head or None,
            "review": review,
            "ci": ci,
            "blockers": [b for b in [(owner or {}).get("blocker")] if b],
            "next_action": (owner or {}).get("next_action") or UNKNOWN,
            "as_of": _newest([(owner or {}).get("as_of"), review.get("as_of"), ci.get("as_of")]) or captured_at,
            "source": "claims+coordinator_ledger" if owner and not gaps else ("claims" if owner else "none"),
        }

    as_of = _newest([a.get("as_of") for a in agents] + [e.get("observed_at") or e.get("ts") for e in events])
    return {
        "schema": SCHEMA,
        "status": "OK" if not gaps else ("PARTIAL" if agents or events else "UNAVAILABLE"),
        "as_of": as_of,
        "captured_at": captured_at,
        "source": "claims+coordinator_ledger",
        "gaps": gaps,
        "agents": agents,
        "work": work,
        "evidence_class": EVIDENCE_CLASS,
        "authority": "READ_ONLY_ADVISORY",
    }
