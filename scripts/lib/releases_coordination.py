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
import re
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


#: The claim board's own staleness default; a claim older than this is stale, not working.
WORKING_HEARTBEAT_HOURS = 2.0


def _fresh(claim: Mapping[str, Any], now: Optional[datetime]) -> bool:
    """True only when the claim's own heartbeat is inside the staleness threshold."""
    if not claim:
        return False
    beat = _parse(claim.get("as_of"))
    if beat is None:
        return False
    at = now or datetime.now(timezone.utc)
    if beat.tzinfo is None:
        beat = beat.replace(tzinfo=timezone.utc)
    delta = (at - beat).total_seconds()
    # A heartbeat in the FUTURE is not proof of work either: it is a clock skew or a forged record.
    # Bounded on both sides (codex review of 9a0ae89e, 2026-11-02).
    return 0 <= delta <= WORKING_HEARTBEAT_HOURS * 3600


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
    """Evidence is only attached when BOTH heads are real, non-empty and equal.

    An empty target head and an empty record head used to compare equal, so a row with no head and
    a ledger record with no head produced review MERGE and CI GREEN out of nothing (codex review of
    9a0ae89e, 2026-11-02).
    """
    if not str(head_sha or "").strip():
        # Only records that name this PR *and* this exact head count; anything else is a gap rather
        # than evidence attached to the current head.
        return {"review": {"state": UNKNOWN, "verdicts": [], "reviewers": [], "independent_reviewers": 0,
                           "records": [], "head_sha": None, "as_of": None, "source": "none",
                           "gap": "target_head_missing", "evidence_class": EVIDENCE_CLASS},
                "ci": {"state": UNKNOWN, "head_sha": None, "as_of": None, "source": "none",
                       "workflows": [], "evidence_class": EVIDENCE_CLASS, "gap": "target_head_missing"}}
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
        row_head = str(row.get("head_sha") or "").strip()
        if not row_head:
            continue                      # a record that names no head proves nothing
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


# ───────────────────────────────────────────── bounded local reads (codex, 2026-11-02)
#: Explicit limits: a worklog tail, the whole ledger, and a cap on how many files are opened.
WORKLOG_TAIL_BYTES = 64 * 1024
LEDGER_MAX_BYTES = 2 * 1024 * 1024
MAX_WORKLOGS = 64


def _safe_under(root: Path, path: Path) -> bool:
    """Refuse symlinks and anything that escapes the coordination root."""
    try:
        path.resolve().relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False
    return not path.is_symlink()


def read_board(board_path: Path, root: Path) -> tuple[dict[str, Any], Optional[str]]:
    """Primary agents from the BOARD's documented '## Agents' table, with the BOARD's own updated time."""
    if not _safe_under(root, board_path):
        return {"agents": [], "updated_at": None}, "board_unsafe_path"
    try:
        text = board_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"agents": [], "updated_at": None}, "board_absent"
    except OSError as exc:
        return {"agents": [], "updated_at": None}, f"board_unreadable:{type(exc).__name__}"
    updated = None
    for line in text.splitlines()[:6]:
        if line.lower().startswith("updated:"):
            updated = line.split(":", 1)[1].strip().split(" by ")[0].strip() or None
            break
    rows: list[dict[str, Any]] = []
    in_table = False
    for line in text.splitlines():
        if line.strip().lower().startswith("## agents"):
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if not in_table or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0].lower() == "session" or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append({
            "session": cells[0],
            "task": cells[1] or UNKNOWN,
            "branch_or_pr": cells[2] or UNKNOWN,
            "next_action": cells[3] or UNKNOWN,
            "state": "assigned",          # the BOARD says who was assigned, not who is executing now
            "as_of": updated,
            "source": "board",
        })
    return {"agents": rows, "updated_at": updated, "open_prs": parse_open_prs_table(text, updated)}, None


def parse_open_prs_table(text: str, updated_at: Optional[str]) -> dict[int, dict[str, Any]]:
    """The BOARD's `## Open PRs` rows, keyed by PR number.

    Columns are `| PR | state | owner | what is needed |`; the PR cell starts with `#<n>`. This is the
    documented fallback for a PR whose owner has no worklog to read (codex, 2026-11-02) - it supplies
    next/owner CONTEXT only, never a review verdict or any merge authority.
    """
    rows: dict[int, dict[str, Any]] = {}
    in_table = False
    for line in text.splitlines():
        if line.strip().lower().startswith("## open prs"):
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if not in_table or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        head = cells[0]
        m = re.match(r"^#(\d+)\b", head)
        if not m:
            continue
        rows[int(m.group(1))] = {
            "state_text": cells[1] or UNKNOWN,
            "owner": cells[2] or UNKNOWN,
            "what_is_needed": cells[3] or UNKNOWN,
            "as_of": updated_at,
            "source": "board",
        }
    return rows


def read_worklog(worklog_path: Path, root: Path) -> tuple[dict[str, Any], Optional[str]]:
    """Blocker/next from a claim's worklog TAIL, bounded; a truncated read says so."""
    if not _safe_under(root, worklog_path):
        return {"blocker": None, "next_action": None}, "worklog_unsafe_path"
    try:
        size = worklog_path.stat().st_size
        with open(worklog_path, "rb") as f:
            if size > WORKLOG_TAIL_BYTES:
                f.seek(size - WORKLOG_TAIL_BYTES)
            text = f.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return {"blocker": None, "next_action": None}, "worklog_absent"
    except OSError as exc:
        return {"blocker": None, "next_action": None}, f"worklog_unreadable:{type(exc).__name__}"
    # Reuse the CANONICAL parser rather than inventing one (codex, 2026-11-02): the handoff lives in
    # "## Handoff" as "- Next step:", not as a "next:" token, and blockers live in "## Blockers", not in
    # any line containing the word "blocker". `summarize()` owns that format; we only bound the read.
    try:
        from . import agent_claim_worklog as _wl
    except ImportError:  # pragma: no cover - scripts/ on sys.path
        import lib.agent_claim_worklog as _wl  # type: ignore
    try:
        summary = _wl.summarize(text)
    except Exception:  # noqa: BLE001 - an unparseable worklog is a gap, not a crash
        summary = {}
    next_action = (summary.get("next_step") or None)
    blocker_lines = []
    try:
        _h, sections = _wl.parse(text)
        blocker_lines = [ln.lstrip("-*+ ").strip() for ln in _wl._strip_placeholder(sections.get("Blockers") or [])[:5]]
        # "(empty)"/"(none)" are placeholders the canonical renderer writes into an unused section.
        blocker_lines = [ln for ln in blocker_lines if ln.lower() not in ("(empty)", "(none)", "none", "empty")]
    except Exception:  # noqa: BLE001
        blocker_lines = []
    gap = "worklog_truncated" if size > WORKLOG_TAIL_BYTES else None
    return {"blocker": (blocker_lines[0][:300] if blocker_lines else None),
            "blockers": [b[:300] for b in blocker_lines],
            "next_action": next_action,
            "truncated": bool(gap)}, gap


def agent_rows(claims: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    # ALL live claims are kept (codex independent review, 2026-11-02): de-duplicating by session here
    # dropped a session's NEWER claim, so a PR whose owner had moved branches lost its ownership. Every
    # active claim is needed for per-PR lookup; only the primary summary dedupes.
    for doc in claims:
        if not is_live(doc):
            continue
        session = str(doc.get("session") or "")
        if not session and not doc.get("claim_id"):
            continue
        rows.append({
            "session": doc.get("session"),
            "claim_id": doc.get("claim_id"),
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


def primary_claims(claims: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per session for the PRIMARY summary: the newest live claim it holds.

    Per-PR ownership keeps every claim (see ``agent_rows``); this is only the agent list, so a session
    working two branches does not appear twice.
    """
    newest: dict[str, dict[str, Any]] = {}
    for row in agent_rows(claims):
        key = str(row.get("session") or row.get("claim_id") or "")
        prior = newest.get(key)
        if prior is None or (_parse(row.get("as_of")) or datetime.min.replace(tzinfo=timezone.utc)) >= (
                _parse(prior.get("as_of")) or datetime.min.replace(tzinfo=timezone.utc)):
            newest[key] = row
    return list(newest.values())


def build(ledger_path: Path, claims_dir: Path, prs: Iterable[Mapping[str, Any]], *,
          now: Optional[datetime] = None) -> dict[str, Any]:
    """The additive envelope plus one ``work`` object per PR row (see ``deploy_in_flight.project_pr``)."""
    captured_at = _iso(now or datetime.now(timezone.utc))
    events, ledger_gap = read_ledger(ledger_path)
    claims, claims_gap = read_claims(claims_dir)
    live = agent_rows(claims)

    root = ledger_path.parent
    board, board_gap = read_board(root / "BOARD.md", root)
    gaps = [g for g in (ledger_gap, claims_gap, board_gap) if g]

    # PRIMARY list = the BOARD's documented current rows (never a hardcoded set). A BOARD row is
    # "assigned", not "working": execution state stays UNKNOWN unless a claim proves otherwise.
    by_session = {a["session"]: a for a in live if a.get("session")}
    agents = []
    for row in board["agents"]:
        claim = by_session.get(row["session"]) or {}
        agents.append({
            **row,
            "branch": claim.get("branch") or row["branch_or_pr"],
            "pr": claim.get("pr"),
            # An active claim can be stale: ownership and context persist, but "working" requires a
            # heartbeat inside the claim board's own staleness threshold (codex/cc6 review, 2026-11-02).
            "execution_state": "working" if _fresh(claim, now) else UNKNOWN,
            "claim_as_of": claim.get("as_of"),
            "source": "board" if not claim else "board+claims",
        })
    if not agents:            # no readable BOARD: fall back to live claims, and say so
        agents = [{**a, "execution_state": "working" if _fresh(a, now) else UNKNOWN,
                   "branch_or_pr": a.get("branch")} for a in primary_claims(claims)[:20]]
    # Per-PR ownership comes from the CLAIMS (they carry the claim id the worklog is keyed by), while the
    # primary agent list above is BOARD context. Mixing the two lost the worklog lookup.
    by_branch = {a["branch"]: a for a in live if a.get("branch")}

    work: dict[int, dict[str, Any]] = {}
    for pr in prs:
        number = int(pr.get("number") or 0)
        head = str(pr.get("head_sha") or "")
        evidence = evidence_for_pr(events, number, head)
        owner = by_branch.get(str(pr.get("branch") or ""))
        wl = None
        if owner and owner.get("claim_id"):
            wl, wl_gap = read_worklog(claims_dir / f"{owner['claim_id']}.worklog.md", claims_dir)
            if wl_gap and wl_gap not in gaps:
                gaps.append(wl_gap)
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
        # BOARD fallback: the Open PRs row supplies next/owner CONTEXT when the claim's worklog has none.
        # It never supplies a review verdict or any merge authority.
        board_pr = (board.get("open_prs") or {}).get(number) or {}
        if not ((wl or {}).get("next_action") or (owner or {}).get("next_action")) and board_pr.get("what_is_needed"):
            _next = board_pr["what_is_needed"]
            _next_source = "board_open_prs"
        else:
            _next = (wl or {}).get("next_action") or (owner or {}).get("next_action") or UNKNOWN
            _next_source = "worklog" if (wl or {}).get("next_action") else ("claims" if owner else "none")
        work[number] = {
            "owner": (owner or {}).get("session") or UNKNOWN,
            "current_task": (owner or {}).get("task") or UNKNOWN,
            "publication_state": publication,
            "local_head": local_head or None,
            "claim_head_recorded_at": claim_head_at,
            "published_head": head or None,
            "review": review,
            "ci": ci,
            "blockers": list(dict.fromkeys(
                ([b for b in [(owner or {}).get("blocker")] if b] if not wl else [])
                + list((wl or {}).get("blockers") or []))),
            "next_action": _next,
            "next_action_source": _next_source,
            "board_owner": board_pr.get("owner") if board_pr else None,
            # An ABSENT source means the row's as_of is null. Stamping the capture time would date a fact
            # nobody observed (cc6 review, 2026-11-02).
            "as_of": _newest([(owner or {}).get("as_of"), board_pr.get("as_of"), review.get("as_of"),
                              ci.get("as_of")]),
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
