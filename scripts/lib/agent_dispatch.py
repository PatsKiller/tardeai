"""Automatic agent dispatch — deterministic, no model, no grading (operator P0, 2026-11-04 ~13:10 ET).

Why this exists: after the no-idle mandate, 10 of 13 sessions sat idle for three hours because idle-avoidance
depended on the coordinator choosing to sweep. This module makes it mechanical: read each session's tmux pane, pick
the one next piece of work in a fixed order, send one concrete instruction, verify it went busy, and record what
happened.

It is built on the REPO port of the nudger (``scripts/agent_nudger.py``) — the copy with tests, a refusal list,
isolated ``--state``/``--ledger``, BLIND handling for a failed capture, and verified sends. The LIVE coordinator copy
(``coordination/coordinator/agent_nudger.py``) has diverged from it (see ``docs/ops/NUDGER_N8N_MIGRATION_PROPOSAL_20261103.md``
§1a); the detection semantics here are the repo port's, deliberately.

RAILS — the dispatcher never:
  * writes, creates or edits a claim, a review artifact, a review verdict, or a queue row's status;
  * pushes, merges, calls pr_merge_delegation, or changes any repository;
  * speaks for a reviewer: reviews are ASSIGNED by naming the PR, never authored.
It sends tmux keystrokes and writes exactly two kinds of file of its own: its ledger and its alert/report files.

Pure where it matters: every decision below is a function of data handed in, so tests are hermetic.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import time
from .agent_claim_board import AUXILIARY_CLAIM_DIR_SCHEMAS, ClaimView, overlapping_pairs, patterns_overlap
from . import merge_hold_paths
from .pr_merge_delegation import Refused as EvidenceRefused, collect_held_classes, effective_claim_states, text_id
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from scripts.check_shared_infra_pr import assess as assess_shared_infra
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

SCHEMA = "AgentDispatch@v1"

#: Busy markers across vendors (Claude Code, Codex, Cursor agent).
BUSY_RE = re.compile(r"esc to interrupt|Working \(|Thinking|Generating|Running…|to interrupt\)")
#: Text typed into the input box but never submitted (Claude '❯ text', Codex '› text').
UNSENT_RE = re.compile(r"^\s*[❯›] (?!Ask Codex to do anything)(\S.*)$")
#: Sessions this lane drives. Broker/order/execution names are excluded by the refusal list below, never by this regex.
SESSION_RE = re.compile(r"^(cc-deepseek|cc-anthropic|cx-|cu-|codex$)")
REFUSED_RE = re.compile(r"(?i)(broker|place_order|\borders?\b|execution|\bmbi\b|alpaca|schwab|moomoo)")

#: A row is work only in these two statuses. Every other status is silence (queue status_rules, 2026-11-04).
WORK_STATUSES = frozenset({"queued", "assigned"})
#: A claim older than this cannot hold a file against a new assignment.
CLAIM_LIVE_HOURS = 2.0
#: A session idle this long with no work available is an escalation, not a quiet fleet.
IDLE_ESCALATE_MINUTES = 15.0
#: How long to wait for a submitted instruction to make the pane busy.
BUSY_CONFIRM_SECONDS = 30.0
#: Most reviewers one PR may have at one head (independent verdicts already filed + handed out this cycle).
MAX_REVIEWERS_PER_PR = 2
#: Nothing in this lane may hang: every subprocess call and every wait is bounded (F3).
RUN_TIMEOUT_S = 15.0


class DispatchError(RuntimeError):
    """A refusal this lane makes on purpose (unsafe output path, unknown author, …)."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or now_utc()).isoformat(timespec="seconds").replace("+00:00", "Z")


# ── session state ────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PaneState:
    """What one session's screen says. `blind` is its own state: a failed capture is never a verdict."""

    session: str
    state: str  # busy | input_pending | idle | blind
    evidence: str = ""

    @property
    def idle(self) -> bool:
        return self.state == "idle"


def classify_pane(session: str, screen: str | None) -> PaneState:
    """Classify a captured pane. `None` means the capture failed → blind (never idle, never busy)."""
    if screen is None:
        return PaneState(session, "blind", "capture failed")
    tail = [ln for ln in screen.splitlines() if ln.strip()][-12:]
    joined = "\n".join(tail)
    if BUSY_RE.search(joined):
        return PaneState(session, "busy", "busy marker on screen")
    for ln in tail:
        m = UNSENT_RE.match(ln)
        if m:
            return PaneState(session, "input_pending", f"unsent input: {m.group(1)[:40]}")
    return PaneState(session, "idle", "no busy marker, no unsent input")


def selectable_sessions(names: Iterable[str]) -> list[str]:
    """The sessions this lane may drive: name matches the fleet regex and is not in the refusal list."""
    out = []
    for name in sorted({n for n in names if n}):
        if SESSION_RE.search(name) and not REFUSED_RE.search(name):
            out.append(name)
    return out


# ── claims and queue (read-only) ────────────────────────────────────────────────────────────────────────────────


@dataclass
class Claim:
    claim_id: str
    session: str
    branch: str
    paths: list[str]
    head_sha: str
    status: str
    age_h: float
    source_authors: tuple[str, ...] = ()
    takeover_of: tuple[dict[str, Any], ...] = ()

    @property
    def live(self) -> bool:
        return self.status == "active" and self.age_h <= CLAIM_LIVE_HOURS


def load_claims(claims_dir: Path, *, now: datetime | None = None) -> list[Claim]:
    """Read every claim status and predecessor; missing evidence cannot release holds."""
    ref = now or now_utc()
    directory = Path(claims_dir)
    try:
        if not directory.is_dir():
            raise DispatchError("claim board unavailable")
        paths = sorted(p for p in directory.iterdir() if p.suffix == ".json")
    except OSError as exc:
        raise DispatchError("claim board unreadable") from exc
    records = []
    try:
        records.extend((path.name, json.loads(path.read_text(encoding="utf-8"))) for path in paths)
        history = directory / "claims_history.jsonl"
        if history.exists():
            with history.open(encoding="utf-8") as stream:
                for number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    archived = json.loads(line)
                    if not isinstance(archived, dict):
                        raise ValueError("invalid claim archive")
                    if archived.get("schema") == "AgentClaimArchive@v1":
                        records.append((f"claims_history.jsonl:{number}", archived.get("claim")))
    except (OSError, ValueError, TypeError) as exc:
        raise DispatchError("claim evidence or archive unreadable") from exc
    out: list[Claim] = []
    for label, d in records:
        try:
            if isinstance(d, dict) and d.get("schema") in AUXILIARY_CLAIM_DIR_SCHEMAS:
                continue
            if not isinstance(d, dict) or not d.get("claim_id"):
                raise ValueError("invalid claim record")
            if d.get("status") not in {"active", "done", "abandoned"}:
                raise ValueError("invalid canonical claim status")
            hb = d.get("heartbeat_at") or d.get("started_at")
            stamp = datetime.fromisoformat(str(hb).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("claim timestamp lacks timezone")
            age = (ref - stamp).total_seconds() / 3600
            raw_paths = d.get("paths") or []
            if not isinstance(raw_paths, list) or any(not isinstance(p, str) for p in raw_paths):
                raise ValueError("invalid claim paths")
            authors = {str(d.get("session") or "")}

            def predecessors(rows):
                if not isinstance(rows, list):
                    raise ValueError("invalid claim predecessors")
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError("invalid claim predecessor")
                    if row.get("session"):
                        authors.add(str(row["session"]))
                    predecessors(row.get("takeover_of") or [])

            predecessors(d.get("takeover_of") or [])
            out.append(
                Claim(
                    claim_id=str(d["claim_id"]),
                    session=str(d.get("session") or ""),
                    branch=str(d.get("branch") or ""),
                    paths=list(raw_paths),
                    head_sha=str(d.get("head_sha") or ""),
                    status=str(d.get("status") or ""),
                    age_h=age,
                    source_authors=tuple(sorted(authors - {""})),
                    takeover_of=tuple(d.get("takeover_of") or []),
                )
            )
        except (OSError, ValueError, TypeError) as exc:
            raise DispatchError(f"claim evidence unreadable: {label}") from exc
    return out


def row_paths(row: dict[str, Any]) -> list[str]:
    """A queue row's file claims: `paths` when present, else the single `path`/`file` keys some rows carry."""
    raw = row.get("paths") or []
    paths = [raw] if isinstance(raw, str) else [str(p) for p in raw]
    for key in ("path", "file"):
        if row.get(key):
            paths.append(str(row[key]))
    return [p.strip() for p in paths if p and p.strip()]


def row_workable(
    row: dict[str, Any], session: str, claims: Sequence[Claim], *, now: datetime | None = None
) -> tuple[bool, str]:
    """Is this queue row the session's to work right now? Returns (ok, reason-when-not)."""
    if str(row.get("owner") or "") != session:
        return False, "not owned by this session"
    return row_hold(row, claims, now=now, own_session=session)


def row_hold(
    row: dict[str, Any], claims: Sequence[Claim], *, now: datetime | None = None, own_session: str = ""
) -> tuple[bool, str]:
    """The row's own eligibility — status, a future ``takeable_at``, and any LIVE claim on its paths.

    R7 (codex at fffe2c9cb): the unowned-row branch checked only owner, status and the per-cycle target count, so a
    row held until 2099, or one whose exact path another session was already working under a live claim, was offered
    to an idle session anyway. Leaving ``owner`` blank must not bypass a recorded hold, so the hold checks live here
    and both branches — owned rows and unowned rows — go through them.
    """
    if str(row.get("status") or "") not in WORK_STATUSES:
        return False, f"status {row.get('status')!r} is silence"
    takeable = row.get("takeable_at")
    if takeable:
        try:
            when = datetime.fromisoformat(str(takeable).replace("Z", "+00:00"))
            if when > (now or now_utc()):
                return False, f"held until {takeable}"
        except ValueError:
            return False, "takeable_at unparseable"
    wanted = set(row_paths(row))
    if wanted:
        for claim in claims:
            if own_session and claim.session == own_session:
                continue  # a session's own live claim on its own row is the normal case, not a hold
            matches = overlapping_pairs(wanted, claim.paths) if claim.live else []
            if matches:
                return False, f"{matches[0][0]} held by {claim.session} ({claim.claim_id})"
    return True, ""


# ── PRs, verdicts and the merge pump ────────────────────────────────────────────────────────────────────────────


@dataclass
class PullRequest:
    number: int
    head_sha: str
    head_ref: str
    merge_state: str
    draft: bool
    commit_shas: tuple[str, ...] = ()
    updated_at: str = ""
    files: tuple[str, ...] = ()
    changed_files: int | None = None
    checks_green: bool | None = None
    prior_paths: tuple[str, ...] = ()
    rename_evidence_complete: bool = True
    title: str = ""
    body: str = ""
    labels: tuple[str, ...] = ()
    metadata_complete: bool = True
    shared_checks_green: bool | None = None

    @property
    def scope_files(self) -> tuple[str, ...]:
        """Both names of a rename retain their authority and custody requirements."""
        return tuple(dict.fromkeys([*self.files, *self.prior_paths]))

    @property
    def files_complete(self) -> bool:
        return (
            self.rename_evidence_complete
            and type(self.changed_files) is int
            and self.changed_files >= 0
            and self.changed_files == len(self.files)
        )

    @property
    def clean(self) -> bool:
        return self.merge_state.upper() == "CLEAN" and not self.draft

    @property
    def review_eligible(self) -> bool:
        """A review is a prerequisite for readiness; drafts and CI/conflict gates do not bar it."""
        return bool(self.head_sha) and self.files_complete

    @property
    def shas(self) -> tuple[str, ...]:
        """The head plus every commit it carries — the set a claim's head_sha must be in to be current."""
        return tuple(dict.fromkeys([self.head_sha, *self.commit_shas]))


def registration_authorship(art: dict[str, Any]) -> dict[str, Any]:
    """Keep the canonical registration's source sessions, never Git display names.

    This is a conservative read-only projection, not the merger's custody evaluator.
    A malformed latest registration replaces older qualification rather than borrowing it.
    """
    raw = art.get("authors")
    sessions: set[str] = set()
    valid = isinstance(raw, list) and bool(raw)
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            valid = False
            continue
        session = row.get("session")
        if not text_id(row.get("actor")) or not text_id(session) or not text_id(row.get("claim_id")):
            valid = False
            continue
        if session in sessions:
            valid = False
        sessions.add(session)
    registrar = art.get("registered_by")
    commits = art.get("source_commit_shas")
    valid = (
        valid
        and art.get("authors_and_coauthors_complete") is True
        and art.get("identity_provenance") == "manual_coordinator_claim_and_source_check"
        and isinstance(registrar, dict)
        and text_id(registrar.get("actor"))
        and text_id(registrar.get("session"))
        and isinstance(art.get("source_authorship_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", art["source_authorship_sha256"]) is not None
        and isinstance(commits, list)
        and bool(commits)
        and all(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) for sha in commits)
    )
    return {
        "authorship_completion_head": art.get("head_sha"),
        "registered_author_sessions": tuple(sorted(sessions)),
        "registered_authorship_valid": bool(valid),
    }


def source_author_sessions(pr: PullRequest, here: Sequence[dict[str, Any]], branch_authors=None) -> set[str]:
    """Both claim ancestry and this exact head's latest registered coauthors are excluded."""
    authors = author_set(branch_authors)
    for entry in here:
        if entry.get("authorship_completion_head") == pr.head_sha:
            authors.update(entry.get("registered_author_sessions", ()))
    return authors


def registered_authorship_status(pr: PullRequest, here: Sequence[dict[str, Any]]) -> bool | None:
    """None permits a first draft review; existing malformed registrations fail closed."""
    registered = [e for e in here if "authorship_completion_head" in e]
    if not registered:
        return None
    return all(
        e.get("authorship_completion_head") == pr.head_sha and e.get("registered_authorship_valid") is True
        for e in registered
    )


def verdicts_at_head(artifacts: Iterable[dict[str, Any]]) -> dict[tuple[int, str], list[dict[str, Any]]]:
    """Index the latest verdict per reviewer/head in supplied observation order."""
    index: dict[tuple[int, str], dict[str, dict[str, Any]]] = {}
    completion: dict[tuple[int, str], dict[str, Any]] = {}
    for art in artifacts:
        if not isinstance(art, dict):
            continue
        try:
            pr = int(art.get("pr"))
        except (TypeError, ValueError):
            continue
        head = str(art.get("head_sha") or "")
        if not head:
            continue
        if art.get("schema") == "PrMergeReviewEvidence@v1":
            # The latest canonical registration owns this HEAD's completion evidence. Missing/false values
            # replace prior true values; another head or a standalone review cannot lend an attestation.
            completion[(pr, head)] = {
                **registration_authorship(art),
                "engineering_completion_head": head,
                "section17_completion_head": head,
                "section17_review_completed": art.get("section17_review_completed") is True,
                "shared_infra_completion_head": head,
                "shared_infra_isolated_reviewed": art.get("shared_infra_isolated_reviewed") is True,
                "engineering_tests_completed": art.get("engineering_tests_completed") is True,
                "engineering_docs_completed": art.get("engineering_docs_completed") is True,
            }
        rows = art.get("reviews") if isinstance(art.get("reviews"), list) else [art]
        for row in rows:
            if not isinstance(row, dict):
                continue
            verdict = str(row.get("verdict") or "").upper()
            reviewer = str(row.get("reviewer_session") or row.get("reviewer") or "")
            if verdict in ("MERGE", "BLOCK") and reviewer:
                index.setdefault((pr, head), {})[reviewer] = {"verdict": verdict, "reviewer": reviewer}
    result = {}
    for key, rows in index.items():
        entries = list(rows.values())
        for entry in entries:
            entry.update(completion.get(key, {}))
        result[key] = entries
    return result


AUTHORITY_PATH = Path(__file__).resolve().parents[2] / "config" / "agent_standing_authority.json"
SHARED_INFRA_PATH = AUTHORITY_PATH.with_name("shared_infra_paths.json")


def review_requirements(path: Path | None = None) -> tuple[int, int, tuple[str, ...]]:
    """Read the operator's bar; unknown authority holds every path and stops dispatch."""
    try:
        doc = json.loads(Path(path or AUTHORITY_PATH).read_text(encoding="utf-8"))
        if (
            not isinstance(doc, dict)
            or doc.get("schema") != "AgentStandingAuthority@v1"
            or doc.get("status") != "ACTIVE"
        ):
            raise ValueError("authority is not active")
        block = doc["capabilities"]["coordinator_merge"]
        ordinary, held = block["ordinary_reviews"], block["held_reviews"]
        globs = block["excluded_globs"]
        reserved = doc.get("reserved_paths") or []
        if (
            type(ordinary) is not int
            or type(held) is not int
            or ordinary < 1
            or held < 2
            or not isinstance(globs, list)
            or not globs
            or not isinstance(reserved, list)
            or any(not isinstance(g, str) or not g.strip() for g in [*globs, *reserved])
        ):
            raise ValueError("authority requirements incomplete")
        return ordinary, max(ordinary, held), tuple(dict.fromkeys([*globs, *reserved]))
    except (OSError, ValueError, TypeError, KeyError):
        return 1, 2, ("**",)


def required_reviews(
    files: Sequence[str], requirements: tuple[int, int, tuple[str, ...]] | None = None
) -> tuple[int, bool]:
    """``(how many independent MERGEs, is it held)`` for one change; an unreadable file list is HELD (fail closed)."""
    ordinary, held, exclusions = requirements or review_requirements()
    if not files or exclusions == ("**",):
        return held, True
    try:
        classes, _metadata = collect_held_classes(files, merge_hold_paths.load(), merge_hold_paths)
    except (EvidenceRefused, OSError, ValueError, TypeError):
        return held, True  # unknown classification never earns the ordinary bar
    return (held, True) if classes else (ordinary, False)


def author_set(value: str | Iterable[str] | None) -> set[str]:
    """Accept legacy single-author inputs without discarding a transferred source's authors."""
    if isinstance(value, str):
        return {value} if value else set()
    return {str(v) for v in value or () if v}


def work_allowed(paths: Sequence[str], requirements=None) -> bool:
    """Autonomous work never enters operator-reserved source. No grant is inferred here."""
    _ordinary, _held, globs = requirements or review_requirements()
    paths = [str(raw).strip().lstrip("/") for raw in paths if str(raw).strip()]
    if globs == ("**",) or not paths:
        return False
    for path in paths:
        if ".." in path.split("/") or REFUSED_RE.search(path):
            return False
        try:
            # Concrete file/page names use path matching; conservative claim intersection is for target globs.
            # Treating the concrete "a.tsx" as a directory beneath "*/AGENTS.md" otherwise refuses unrelated work.
            if any(
                fnmatch.fnmatchcase(path, g) or (any(c in path for c in "*?[") and patterns_overlap(path, g))
                for g in globs
            ):
                return False
        except ValueError:
            return False
    return True


def shared_infra_status(pr: PullRequest) -> dict[str, Any]:
    """The canonical pure assessor over the running release's base registry and both rename names."""
    try:
        patterns = json.loads(SHARED_INFRA_PATH.read_text(encoding="utf-8"))["paths"]
        if (
            not isinstance(patterns, list)
            or any(not isinstance(p, str) for p in patterns)
            or not pr.metadata_complete
            or not isinstance(pr.title, str)
            or not isinstance(pr.body, str)
            or not isinstance(pr.labels, (tuple, list))
            or any(not isinstance(label, str) or not label for label in pr.labels)
        ):
            raise ValueError("shared infrastructure metadata unavailable")
        return assess_shared_infra(list(pr.scope_files), pr.title, pr.body, patterns)
    except (OSError, ValueError, TypeError, KeyError):
        return {"shared_infra": None, "ok": False}


def _custody_states(claims: Sequence[Claim]) -> tuple[dict[str, str], bool]:
    """Canonical lifecycle resolution over this read-only snapshot, never age-based release.

    All original takeover links survive loading, including links of completed successors.
    No shared-path exemption is inferred from ambient configuration: omitting that optional
    exemption conservatively refuses ambiguous sibling scopes, rather than inventing custody.
    """
    if len({c.claim_id for c in claims}) != len(claims):
        return {}, False  # contradictory snapshots cannot prove which custody remains
    docs = [
        {"claim_id": c.claim_id, "status": c.status, "paths": c.paths, "takeover_of": list(c.takeover_of)}
        for c in claims
    ]
    views = [ClaimView(doc, c.status, c.age_h * 3600, Path(c.claim_id)) for c, doc in zip(claims, docs)]
    board = SimpleNamespace(stale_after=timedelta(hours=CLAIM_LIVE_HOURS), views=lambda: (views, []))
    try:
        return effective_claim_states(docs, board), True
    except (EvidenceRefused, ValueError, TypeError, KeyError):
        return {}, False


def merge_ready(
    prs: Sequence[PullRequest],
    verdicts: dict[tuple[int, str], list[dict[str, Any]]],
    claims: Sequence[Claim],
    author_of: dict[int, str | Iterable[str]],
) -> dict[str, list[dict[str, Any]]]:
    """Split the open PRs into {ready, one_step}. Report only — the lead's helper remains the only merger."""
    ready: list[dict[str, Any]] = []
    one_step: list[dict[str, Any]] = []
    by_branch = {c.branch: c for c in sorted(claims, key=lambda c: -c.age_h)}
    requirements = review_requirements()
    states, states_valid = _custody_states(claims)
    for pr in prs:
        if not pr.clean:
            continue
        here = verdicts.get((pr.number, pr.head_sha), [])
        authors = source_author_sessions(pr, verdicts.get((pr.number, pr.head_sha), []), author_of.get(pr.number))
        blocks = [e for e in here if e["verdict"] == "BLOCK" and e["reviewer"] and e["reviewer"] not in authors]
        merges = [e for e in here if e["verdict"] == "MERGE" and e["reviewer"] and e["reviewer"] not in authors]
        need, held = required_reviews(pr.scope_files, requirements)
        shared = shared_infra_status(pr)
        reviewers = {e["reviewer"] for e in merges}
        claim = by_branch.get(pr.head_ref)
        released = [
            c
            for c in claims
            if c.branch == pr.head_ref
            and c.session in authors
            and c.status == "done"
            and c.head_sha
            and c.head_sha in pr.shas
        ]
        try:
            covered = {path for path in pr.scope_files if any(overlapping_pairs([path], c.paths) for c in released)}
            active_holders = [
                c
                for c in claims
                if states.get(c.claim_id) in {"live", "unresolved"} and overlapping_pairs(pr.scope_files, c.paths)
            ]
            claim_current = bool(released) and covered == set(pr.scope_files) and not active_holders and states_valid
        except ValueError:
            claim_current = False
            active_holders = []
        author = ", ".join(sorted(authors))
        base = {
            "pr": pr.number,
            "head": pr.head_sha,
            "branch": pr.head_ref,
            "author": author,
            "merge_state": pr.merge_state,
        }
        if not author:
            # R5 (codex at fffe2c9cb): an unresolved author made independence unprovable and could still render a
            # ready entry with author="". "Ready to merge" is a claim about custody; without the author it is a guess.
            one_step.append(
                {
                    **base,
                    "step": "author unknown — independence cannot be shown, so readiness cannot be claimed",
                    "verdicts": sorted(reviewers),
                }
            )
        elif blocks:
            one_step.append(
                {
                    **base,
                    "step": "a BLOCK verdict stands at this head — resolve it, then re-review",
                    "verdicts": [e["reviewer"] for e in blocks],
                }
            )
        elif reviewers and len(reviewers) < need:
            one_step.append(
                {
                    **base,
                    "step": f"needs {need} independent MERGE verdicts"
                    f"{' (held path)' if held else ''} — {len(reviewers)} at this head",
                    "verdicts": sorted(reviewers),
                    "held": held,
                    "needed": need,
                }
            )
        elif merges and not states_valid:
            one_step.append(
                {
                    **base,
                    "step": "claim takeover evidence invalid — custody remains unresolved",
                    "verdicts": sorted(reviewers),
                }
            )
        elif merges and claim_current:
            if requirements[2] == ("**",):
                step = "authority unavailable — readiness cannot be established"
            elif not pr.files_complete:
                step = "changed-file list incomplete — held paths cannot be ruled out"
            elif pr.checks_green is not True:
                step = "exact-head checks are not all measured green"
            elif held and not any(
                e.get("engineering_completion_head") == pr.head_sha
                and e.get("engineering_tests_completed") is True
                and e.get("engineering_docs_completed") is True
                for e in merges
            ):
                step = "held engineering completion unproven — register tests and documentation at this exact head"
            elif not any(
                e.get("section17_completion_head") == pr.head_sha and e.get("section17_review_completed") is True
                for e in merges
            ):
                step = "section-17 review unproven — register completed authority-boundary review at this exact head"
            elif registered_authorship_status(pr, here) is not True:
                step = "registered source authorship unproven — qualify all authors and coauthors at this exact head"
            elif type(shared.get("shared_infra")) is not bool:
                step = "shared-infrastructure classification or metadata unavailable — readiness cannot be established"
            elif shared["shared_infra"] and (
                shared.get("ok") is not True
                or pr.shared_checks_green is not True
                or not ({"shared-infra", "solo"} & {label.lower() for label in pr.labels})
                or not any(
                    e.get("shared_infra_completion_head") == pr.head_sha
                    and e.get("shared_infra_isolated_reviewed") is True
                    for e in merges
                )
            ):
                step = "shared-infrastructure evidence unproven — qualify metadata, label, check and isolated review at this exact head"
            else:
                ready.append({**base, "verdicts": sorted(reviewers)})
                continue
            one_step.append({**base, "step": step, "verdicts": sorted(reviewers)})
        elif merges and not claim_current:
            step = (
                "current source holder is not released — finish its genuine custody before merge"
                if active_holders
                else "released author claims must cover every changed path at a source commit — "
                "create a claim at the head if custody is missing, then release it with its handoff"
            )
            one_step.append(
                {
                    **base,
                    "step": step,
                    "claim_head": claim.head_sha if claim else None,
                    "verdicts": [e["reviewer"] for e in merges],
                }
            )
        elif claim_current:
            one_step.append({**base, "step": "needs one independent MERGE verdict at this exact head", "verdicts": []})
        else:
            one_step.append(
                {
                    **base,
                    "step": "needs a current author claim and one independent MERGE verdict",
                    "claim_head": claim.head_sha if claim else None,
                    "verdicts": [],
                }
            )
    return {"ready": sorted(ready, key=lambda r: r["pr"]), "one_step": sorted(one_step, key=lambda r: r["pr"])}


def render_merge_ready(ready: dict[str, list[dict[str, Any]]], *, generated_at: str) -> str:
    lines = [
        "# MERGE_READY — written by scripts/agent_dispatch.py (report only; the lead's helper is the only merger)",
        "",
        f"Generated {generated_at}. This file assigns nothing and merges nothing.",
        "",
        f"## Ready to merge ({len(ready['ready'])})",
        "",
    ]
    if not ready["ready"]:
        lines.append("_None: no CLEAN PR has both an exact-head MERGE verdict and a current author claim._")
    for r in ready["ready"]:
        lines.append(
            f"- **#{r['pr']}** `{r['branch']}` head `{r['head'][:9]}` — MERGE at this head from "
            f"{', '.join(r['verdicts'])}; author claim is current."
        )
    lines += ["", f"## One step away ({len(ready['one_step'])})", ""]
    if not ready["one_step"]:
        lines.append("_None._")
    for r in ready["one_step"]:
        lines.append(
            f"- **#{r['pr']}** `{r['branch']}` head `{r['head'][:9]}` — {r['step']}"
            + (f" (claim head `{str(r.get('claim_head'))[:9]}`)" if r.get("claim_head") else "")
            + (f"; MERGE from {', '.join(r['verdicts'])}" if r["verdicts"] else "")
        )
    lines.append("")
    return "\n".join(lines)


# ── work selection (a → e) ──────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Assignment:
    session: str
    kind: str  # queue | review | merge_prep | unowned_queue | chore
    target: str  # row id, PR number, claim id …
    instruction: str
    why: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "session": self.session,
            "kind": self.kind,
            "target": self.target,
            "instruction": self.instruction,
            "why": self.why,
        }


def _row_instruction(session: str, row: dict[str, Any], coord: str) -> str:
    acc = row.get("acceptance")
    if isinstance(acc, dict):
        acceptance = " ".join(
            f"{k.capitalize()}: {str(acc.get(k) or '').strip()}"
            for k in ("what", "expected", "actual", "evidence")
            if acc.get(k)
        )
    else:
        acceptance = str(acc or "").strip()
    acceptance = acceptance[:600] + (" …" if len(acceptance) > 600 else "")
    return (
        f"Dispatcher: your next queue row is {row.get('id')} [{row.get('severity') or '?'}] — "
        f"{row.get('page') or 'no page'}" + (f" · check {row.get('check')}" if row.get("check") else "") + ". "
        f"Acceptance: {acceptance or 'see the queue file'}. "
        f"Work it now: claim the files, fix the root cause, produce red-then-green evidence, then report the head "
        f"sha to {coord}/inbox/<lead>/ and take your next row. If it no longer reproduces at the current head, "
        f"close it with the measurement that shows it gone."
    )


def _review_instruction(session: str, pr: PullRequest, coord: str) -> str:
    return (
        f"Dispatcher: review PR #{pr.number} whole-head now — head {pr.head_sha}, branch {pr.head_ref}, "
        f"mergeState {pr.merge_state}. You did not author it. Read the diff, run its tests, mutate the fix back to "
        f"show the tests fail without it, then file MERGE or BLOCK with findings at this exact head in "
        f"{coord}/review-evidence/ as .md + .machine.json (the canonical line is 'Adversarial-review: MERGE "
        f"reviewer={session} head={pr.head_sha}'), and report the verdict to {coord}/inbox/<lead>/. "
        f"Do not push, do not merge, do not edit the author's branch."
    )


def _merge_prep_instruction(session: str, pr: PullRequest, claim: Claim | None, coord: str) -> str:
    head = pr.head_sha
    return (
        f"Dispatcher: PR #{pr.number} is CLEAN with an exact-head MERGE verdict but cannot merge — the author "
        f"claim does not carry this head. Re-stamp the claim: run agent_claim.py heartbeat for claim "
        f"{claim.claim_id if claim else '<none>'} from the worktree whose HEAD is {head} "
        f"(branch {pr.head_ref}), then report the claim id and head to {coord}/inbox/<lead>/. Do not push or merge."
    )


def _chore_instruction(session: str, claim: Claim, coord: str, *, open_pr: bool = False) -> str:
    prefix = (
        f"Dispatcher: chore — claim {claim.claim_id} on branch {claim.branch} has not been heartbeated for "
        f"{claim.age_h:.1f}h. "
    )
    if session != claim.session:
        return (
            prefix + f"It belongs to {claim.session or 'an unresolved owner'}, not {session}. Do not impersonate "
            f"the owner or perform owner-only maintenance on its record. Notify the owner and {coord}/inbox/<lead>/; "
            f"ask the lead to authorize canonical takeover if the owner cannot continue. First read the handoff "
            f"with agent_claim.py takeover {claim.claim_id} (read-only). Only after authorization, run "
            f"agent_claim.py takeover {claim.claim_id} --claim from the actual source worktree, then verify the "
            f"returned new claim belongs to your own session before resuming maintenance. A refusal stops the route. "
            + ("The branch has an OPEN PR: preserve its work and PR state. " if open_pr else "")
            + "Completed source records cannot be re-stamped; never fabricate their ownership or release."
        )
    if open_pr:
        return (
            prefix + "Its branch has an OPEN PR. Do NOT release unfinished work as done or abandoned. Resume the "
            "repair or publish its existing checkpoint, heartbeat from the actual source head, and hand it off "
            f"with agent_claim.py handoff naming the exact next step; report to {coord}/inbox/<lead>/. "
            "Completed, published work needs genuine released custody for merge; a completed claim cannot be re-stamped."
        )
    return (
        prefix + "No open PR depends on it. Either resume your own work (heartbeat from its worktree) or close "
        f"it with agent_claim.py release --status abandoned and a summary, then report to {coord}/inbox/<lead>/ so "
        "the board is honest."
    )


def select_work(
    session: str,
    *,
    queue: Sequence[dict[str, Any]],
    claims: Sequence[Claim],
    prs: Sequence[PullRequest],
    verdicts: dict[tuple[int, str], list[dict[str, Any]]],
    author_of: dict[int, str | Iterable[str]],
    coord: str,
    now: datetime | None = None,
    reviewed_pairs: set[tuple[int, str]] | None = None,
    review_counts: dict[tuple[int, str], int] | None = None,
    taken: dict[tuple[str, str], int] | None = None,
    prior_review_sessions: dict[tuple[int, str], set[str]] | None = None,
) -> Assignment | None:
    """The one next thing for this session, in the operator's order (a)…(e). None means "nothing to do".

    `reviewed_pairs` is (pr number, reviewer session) pairs already dispatched this cycle, so two sessions are not
    sent the same PR by the same scan.

    F4 round 2 (cx-openai-3): the review-history cap is HEAD-SPECIFIC. A dispatch recorded against an older head must
    neither spend the two-reviewer budget at the new head nor bar that reviewer from reviewing the new revision — the
    revision is new work, and the old verdicts belong to the old tree.
    """
    reviewed = reviewed_pairs or set()
    counts = review_counts or {}
    handed = taken if taken is not None else {}
    prior = prior_review_sessions or {}
    ref = now or now_utc()
    requirements = review_requirements()

    def free(kind: str, target: str, *, allow: int = 1) -> bool:
        """Has this cycle already given this target away `allow` times?"""
        return handed.get((kind, target), 0) < allow

    # (a) its own workable rows, in queue order (the queue lists them in priority order)
    for row in queue:
        ok, _why = row_workable(row, session, claims, now=ref)
        if (
            ok
            and work_allowed([*row_paths(row), str(row.get("page") or "")], requirements)
            and free("queue", str(row.get("id")))
        ):
            return Assignment(
                session, "queue", str(row.get("id")), _row_instruction(session, row, coord), "own queued row"
            )

    # (b) a review of a CLEAN PR it did not author and that has no MERGE verdict at its head yet.
    # Newest activity first: a live PR is the work, and an ancient CLEAN PR is the triage list (board row 26), not
    # somewhere to spend five sessions. At most MAX_REVIEWERS_PER_PR independent reviewers per head.
    for pr in sorted(prs, key=lambda p: (p.updated_at or "", p.number), reverse=True):
        if not pr.review_eligible or not work_allowed(pr.scope_files, requirements):
            continue
        need, held = required_reviews(pr.scope_files, requirements)
        if not held:
            continue  # D51: cloud owns ordinary reviews; leads route exceptional P0/P1 work explicitly.
        authors = source_author_sessions(pr, verdicts.get((pr.number, pr.head_sha), []), author_of.get(pr.number))
        if registered_authorship_status(pr, verdicts.get((pr.number, pr.head_sha), [])) is False:
            continue  # Existing invalid author evidence cannot establish independent review eligibility.
        if not authors:
            continue  # F5: an unknown author means independence cannot be shown — fail closed, assign nobody
        if session in authors:
            continue
        if (pr.number, session) in reviewed:
            continue
        verdicts_here = verdicts.get((pr.number, pr.head_sha), [])
        if any(v["verdict"] == "BLOCK" and v["reviewer"] not in authors for v in verdicts_here):
            continue  # an exact-head code BLOCK needs a repair, never a redundant third review
        filed = {v["reviewer"] for v in verdicts_here if v["reviewer"] and v["reviewer"] not in authors}
        spent = filed | (prior.get((pr.number, pr.head_sha), set()) - authors)
        if max(counts.get((pr.number, pr.head_sha), 0), len(spent)) >= MAX_REVIEWERS_PER_PR:
            continue
        if session in filed:
            continue
        if session in prior.get((pr.number, pr.head_sha), set()):
            continue  # an earlier cycle already sent this reviewer THIS head
        if not free("review", str(pr.number)):
            continue
        merges_here = {
            v["reviewer"]
            for v in verdicts_here
            if v["verdict"] == "MERGE" and v["reviewer"] and v["reviewer"] not in authors
        }
        if len(merges_here) >= need:
            continue  # the bar is met; a held PR with one MERGE still needs its second reviewer
        others = [v for v in verdicts_here if v["verdict"] == "BLOCK" and v["reviewer"] == session]
        if others:
            continue
        return Assignment(
            session,
            "review",
            str(pr.number),
            _review_instruction(session, pr, coord),
            "complete held PR lacks a prerequisite independent review",
        )

    # (c) merge-prep: a CLEAN PR with a MERGE verdict whose author claim is stale on the head
    for pr in sorted(prs, key=lambda p: p.number):
        authors = source_author_sessions(pr, verdicts.get((pr.number, pr.head_sha), []), author_of.get(pr.number))
        if (
            not pr.clean
            or session not in authors
            or not pr.files_complete
            or not work_allowed(pr.scope_files, requirements)
        ):
            continue
        if not any(
            v["verdict"] == "MERGE" and v["reviewer"] and v["reviewer"] not in authors
            for v in verdicts.get((pr.number, pr.head_sha), [])
        ):
            continue
        claim = next((c for c in claims if c.branch == pr.head_ref and c.live and c.session == session), None)
        if claim and claim.head_sha and claim.head_sha not in pr.shas and free("merge_prep", str(pr.number)):
            return Assignment(
                session,
                "merge_prep",
                str(pr.number),
                _merge_prep_instruction(session, pr, claim, coord),
                "MERGE verdict at head but the author claim carries a different head",
            )

    # (d) the oldest unowned row — offered to whoever is idle first, by queue order
    for row in queue:
        if row.get("owner"):
            continue
        ok, _why = row_hold(row, claims, now=ref)  # R7: a blank owner does not bypass a hold or a live claim
        if not ok or not work_allowed([*row_paths(row), str(row.get("page") or "")], requirements):
            continue
        if not free("unowned_queue", str(row.get("id"))):
            continue
        return Assignment(
            session,
            "unowned_queue",
            str(row.get("id")),
            f"Dispatcher: unowned queue row {row.get('id')} — {row.get('page') or ''}. Claim it "
            f"(agent_claim.py claim, then set owner via your report), fix it with red-then-green "
            f"evidence, and report the head to {coord}/inbox/<lead>/.",
            "no owner on the row",
        )

    # (e) a chore: a stale claim that no live session is progressing
    stale = [
        c for c in claims if c.status == "active" and c.age_h > CLAIM_LIVE_HOURS and work_allowed(c.paths, requirements)
    ]
    if stale:
        claim = next((c for c in sorted(stale, key=lambda c: -c.age_h) if free("chore", c.claim_id)), None)
        if claim is None:
            return None
        open_pr = any(p.head_ref == claim.branch for p in prs)
        return Assignment(
            session,
            "chore",
            claim.claim_id,
            _chore_instruction(session, claim, coord, open_pr=open_pr),
            f"claim is {claim.age_h:.1f}h stale",
        )
    return None


# ── submit and the ledger ──────────────────────────────────────────────────────────────────────────────────────


@dataclass
class SubmitResult:
    submitted: bool
    busy_after: bool
    attempts: int
    detail: str


def _protected_files(protected: Sequence[Path]) -> list[Path]:
    """The protected inputs as FILES, so an alias can be compared by inode rather than by path string.

    F2 round 2 (cx-openai-3): a path-string check is defeated by a hardlink — ``ln MERGE_READY.md queue.json`` gives
    two names and ONE inode, so the resolved path of the output is innocent while writing it truncates the queue.
    """
    out: list[Path] = []
    for p in protected:
        p = Path(p)
        if p.is_dir():
            # Direct children and one level down (the fleet's claims/inbox layouts); bounded so a huge tree cannot
            # turn one dispatch cycle into a filesystem walk.
            for child in sorted(p.iterdir())[:5000] if p.exists() else []:
                out.append(child)
                if child.is_dir() and not child.is_symlink():
                    try:
                        out.extend(sorted(child.iterdir())[:5000])
                    except OSError:
                        continue
        else:
            out.append(p)
    return out


def _inode(path: Path) -> tuple[int, int] | None:
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def safe_output_path(target: Path, *, coord: Path, protected: Sequence[Path] = ()) -> Path:
    """Refuse an output path that could write one of the lane's own inputs (F2).

    The dispatcher writes exactly three files. If any of them resolves to the queue, a claims directory, the review
    evidence or the coordinator's inbox — through a symlink, a "../" path, a typo OR A HARDLINK — a bug in this lane
    would edit the very records it is supposed to read. Refuse before sending or writing; a refusal is a refusal,
    never a best-effort write.
    """
    target = Path(target)
    if target.is_symlink():
        raise DispatchError(f"refusing to write {target}: it is a symlink")
    real = target.resolve(strict=False)
    inputs = [Path(p) for p in protected]
    inputs += [Path(coord) / name for name in ("AUDIT_FIX_QUEUE.json", "inbox", "review-evidence", "claims")]
    forbidden = [p.resolve(strict=False) for p in inputs]
    for bad in forbidden:
        if real == bad or bad in real.parents:
            raise DispatchError(f"refusing to write {target}: resolves inside a protected input ({bad})")
    # Identity, not spelling: if the output already exists and shares an inode with an input, it IS that input.
    have = _inode(real)
    if have is not None:
        for candidate in _protected_files(inputs):
            if _inode(candidate) == have:
                raise DispatchError(
                    f"refusing to write {target}: it is the same file as the protected input "
                    f"{candidate} (hardlink alias)"
                )
    parent = real.parent
    if parent.exists() and parent.is_symlink():
        raise DispatchError(f"refusing to write {target}: its directory is a symlink out of the tree")
    if _tracked(real):
        # R1 (codex at fffe2c9cb): `--ledger` was otherwise unrestricted, and pointing it at a source file appended
        # to source. An output of this lane is never a tracked file of the repository.
        raise DispatchError(f"refusing to write {target}: it is a file tracked by git")
    return real


def _tracked(path: Path) -> bool:
    """True when ``path`` exists and git in its repository tracks it. Any failure means "not tracked" (fail open is
    safe here: the link-count and symlink checks above still stand)."""
    if not path.exists():
        return False
    top = subprocess.run(
        ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if top.returncode != 0:
        return False
    try:
        rel = path.resolve().relative_to(Path(top.stdout.strip()).resolve()).as_posix()
    except ValueError:
        return False
    ls = subprocess.run(
        ["git", "-C", str(top.stdout.strip()), "ls-files", "--error-unmatch", "--", rel], capture_output=True, text=True
    )
    return ls.returncode == 0


@dataclass
class CheckedOutput:
    """An output path plus the identities it had WHEN IT WAS CHECKED.

    Holding the parent's device/inode is what makes the later open a check on the real object rather than on a string:
    the write resolves the file name inside the directory inode we validated, not inside whatever that path names a
    moment later.
    """

    path: Path
    parent_inode: tuple[int, int] | None
    file_inode: tuple[int, int] | None


def prepare_output(target: Path, *, coord: Path, protected: Sequence[Path] = ()) -> CheckedOutput:
    """``safe_output_path`` plus the identities needed to verify the same object at write time."""
    real = safe_output_path(target, coord=coord, protected=protected)
    parent_inode = _inode(real.parent)
    file_inode = _inode(real) if real.exists() else None
    return CheckedOutput(real, parent_inode, file_inode)


def open_output(target: Path | CheckedOutput, *, append: bool = False):
    """Open one of this lane's own outputs through an identity-checked handle (R1, codex at fffe2c9cb).

    ``safe_output_path`` is a precheck, and a precheck is not a fence: the file can be replaced between the check and
    the write (codex swapped MERGE_READY.md for a symlink into the queue during the first send and the report truncated
    the queue). Three checks run on the object actually being written:

    * the parent directory is opened first and compared with the identity recorded when the path was checked, and the
      file name is resolved relative to THAT directory handle — so swapping the directory entry afterwards redirects
      nothing;
    * ``O_NOFOLLOW`` refuses a symlink, and a link count above 1 refuses a hardlink alias at ANY depth (the precheck
      only walks two);
    * no ``O_TRUNC`` until those checks pass — truncation is a write, and an alias opened with ``O_TRUNC`` would empty
      the protected file before the refusal.

    Passing a plain path still works (the identity checks then only cover symlink and link count); passing the
    ``CheckedOutput`` is what makes the parent and file identities binding.
    """
    checked = target if isinstance(target, CheckedOutput) else CheckedOutput(Path(target), None, None)
    path = checked.path
    # No O_TRUNC: truncation is a WRITE, and the whole point is to inspect the handle before any byte changes. A
    # hardlink alias opened with O_TRUNC would empty the protected file first and refuse afterwards.
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_APPEND if append else 0)
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        raise DispatchError(f"refusing to write {path}: cannot open its directory ({exc})") from exc
    try:
        if checked.parent_inode is not None:
            have = os.fstat(dir_fd)
            if (have.st_dev, have.st_ino) != checked.parent_inode:
                raise DispatchError(f"refusing to write {path}: its directory was replaced after the check")
        try:
            fd = os.open(path.name, flags, 0o644, dir_fd=dir_fd)
        except OSError as exc:
            raise DispatchError(f"refusing to write {path}: {exc}") from exc
    finally:
        os.close(dir_fd)
    try:
        st = os.fstat(fd)
        if st.st_nlink != 1:
            raise DispatchError(f"refusing to write {path}: it has {st.st_nlink} links (an alias of another file)")
        if checked.file_inode is not None and (st.st_dev, st.st_ino) != checked.file_inode:
            raise DispatchError(f"refusing to write {path}: the file was replaced after the check")
        if not append:
            os.ftruncate(fd, 0)  # now that the inode is known to be ours alone
        return os.fdopen(fd, "a" if append else "w", encoding="utf-8")
    except BaseException:
        os.close(fd)
        raise


def _tail(screen: str, limit: int = 1200) -> str:
    """The last ``limit`` characters of what the pane is actually showing (blank lines dropped)."""
    return "\n".join(ln for ln in (screen or "").splitlines() if ln.strip())[-limit:]


def _tail_hash(screen: str) -> str:
    return hashlib.sha256(_tail(screen).encode()).hexdigest()


def submit(
    session: str,
    text: str,
    *,
    run: Callable[..., Any],
    sleep: Callable[[float], None] = time.sleep,
    busy_confirm_seconds: float = BUSY_CONFIRM_SECONDS,
    poll_every: float = 3.0,
    monotonic: Callable[[], float] = time.monotonic,
) -> SubmitResult:
    """Paste and submit one instruction, then prove THIS paste made the pane busy.

    Multi-line text sent with ``send-keys -l`` silently does not submit (the fleet's well-known trap), so the text
    goes through a tmux buffer, is pasted, and Enter is pressed separately.

    Three properties the reviewer required (F3, round 2), because a submit that "confirms" the wrong thing is worse
    than none:
    * **bounded by the remaining budget** — each capture's own subprocess timeout is the time left before the
      deadline, not a fresh ``RUN_TIMEOUT_S``; a capture that returns after the deadline is DISCARDED, so two slow
      captures can never "confirm" busy at 36s inside a 30s window;
    * **the busy evidence is new** — a busy marker that was already in the pane before the paste is not evidence of
      this dispatch: the marker must be absent from the pre-paste tail, or more frequent in the new tail, AND the
      tail must have changed;
    * **``submitted`` is what actually happened** — it means an Enter was delivered after a paste that succeeded.
      Two failed ``load-buffer`` calls now report ``submitted=False`` instead of True-by-attempt.
    One retry, then the caller logs ``dispatch_failed``.
    """
    buffer_name = "dispatch-" + hashlib.sha256(f"{session}:{text}:{time.time()}".encode()).hexdigest()[:12]

    def _call(argv: list[str], **kwargs: Any) -> Any:
        """One transport call. A timeout or an OSError is a RESULT, never an exception that loses the receipt.

        R6 (codex at fffe2c9cb): ``subprocess.run(timeout=...)`` raises ``TimeoutExpired`` on expiry, and an
        uncaught raise escaped ``submit`` with no ``SubmitResult`` to ledger. Every call goes through here.
        """
        try:
            return run(argv, capture_output=True, text=True, **kwargs)
        except (subprocess.TimeoutExpired, OSError):
            return None

    def _capture(timeout: float = RUN_TIMEOUT_S) -> str | None:
        proc = _call(["tmux", "capture-pane", "-p", "-t", session], timeout=max(0.05, timeout))
        return (proc.stdout or "") if getattr(proc, "returncode", 1) == 0 else None

    def _paste_and_enter(deadline: float) -> bool:
        """Load, paste, Enter — each call bounded by the time left, so the attempt cannot outlive its window."""

        def _left() -> float:
            return max(0.05, min(RUN_TIMEOUT_S, deadline - monotonic()))

        if deadline - monotonic() <= 0:
            return False
        load = _call(["tmux", "load-buffer", "-b", buffer_name, "-"], input=text, timeout=_left())
        if getattr(load, "returncode", 1) != 0:
            return False
        paste = _call(["tmux", "paste-buffer", "-b", buffer_name, "-t", session, "-d"], timeout=_left())
        if getattr(paste, "returncode", 1) != 0:
            return False
        sleep(0.6)  # let the compositor register the paste before Enter
        if deadline - monotonic() <= 0:
            return False
        enter = _call(["tmux", "send-keys", "-t", session, "Enter"], timeout=_left())
        return getattr(enter, "returncode", 1) == 0

    attempts = 0
    entered = False
    for attempt in (1, 2):
        attempts = attempt
        # The attempt's window opens before ANY work for it, so the pre-paste capture and the paste itself are inside
        # the budget too — not just the confirm polls (F3 round 2, the letter of it).
        deadline = monotonic() + busy_confirm_seconds
        before = _capture(max(0.05, min(RUN_TIMEOUT_S, deadline - monotonic())))
        # R2 (codex at fffe2c9cb): the admission check happens HERE, at send time, not only at the first scan. A
        # failed capture is a refusal, not an empty baseline — sending blind is how an instruction lands in an
        # operator's unsent draft. A pane that picked up input or started working since the scan is refused too.
        if before is None:
            return SubmitResult(
                entered, False, attempt, "pre-paste capture failed: refusing to send to a pane I cannot see"
            )
        admitted = classify_pane(session, before)
        if admitted.state != "idle":
            return SubmitResult(
                entered,
                False,
                attempt,
                f"refusing to send: pane is {admitted.state} at send time ({admitted.evidence})",
            )
        if not _paste_and_enter(deadline):
            continue
        entered = True  # an Enter was delivered for a paste that succeeded
        before_tail = _tail(before or "")
        before_hits = len(BUSY_RE.findall(before_tail))
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            sleep(min(poll_every, remaining))
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            screen = _capture(min(RUN_TIMEOUT_S, remaining))
            if screen is None:
                continue
            if monotonic() > deadline:
                continue  # a late capture cannot confirm a window that has already closed
            tail = _tail(screen)
            hits = len(BUSY_RE.findall(tail))
            if hits and tail != before_tail and (before_hits == 0 or hits > before_hits):
                return SubmitResult(True, True, attempts, "busy confirmed on a new capture after the paste")
    return SubmitResult(entered, False, attempts, "no new busy marker within the confirm window")


def ledger_line(
    *,
    session: str,
    assignment: Assignment,
    result: SubmitResult,
    cycle_id: str,
    ts: str | None = None,
    target_head: str = "",
) -> str:
    record = {
        "schema": SCHEMA + "#Dispatch",
        "ts": ts or _iso(),
        "cycle_id": cycle_id,
        "session": session,
        "kind": assignment.kind,
        "target": assignment.target,
        "sent_sha256": hashlib.sha256(assignment.instruction.encode()).hexdigest(),
        "target_head": target_head,
        "submitted": bool(result.submitted),
        "busy_after_30s": bool(result.busy_after),
        "attempts": result.attempts,
        "detail": result.detail,
        "outcome": "dispatched" if (result.submitted and result.busy_after) else "dispatch_failed",
    }
    return json.dumps(record, ensure_ascii=False)


# ── escalation ────────────────────────────────────────────────────────────────────────────────────────────────


def idle_alert(sessions: Sequence[tuple[str, float]], *, generated_at: str) -> str | None:
    """The alert text when the fleet is quiet with nothing to hand out, else None.

    `sessions` is (session, idle-minutes). The threshold is the operator's: an idle session over 15 minutes with no
    work available is the lead's problem to solve (add work or close the session), not something to wait out.
    """
    over = sorted(((s, m) for s, m in sessions if m > IDLE_ESCALATE_MINUTES), key=lambda x: -x[1])
    if not over:
        return None
    lines = [
        "# DISPATCH_IDLE_ALERT — nobody has work and sessions are waiting",
        "",
        f"Generated {generated_at} by scripts/agent_dispatch.py. This file assigns nothing; it asks the lead for a decision.",
        "",
        "The dispatcher found no work to hand out in this cycle (no queued/assigned rows, no CLEAN PR needing a "
        "review, no merge-prep, no unowned row, no chore) while these sessions were idle:",
        "",
    ]
    lines += [f"- **{s}** idle {m:.0f} min" for s, m in over]
    lines += [
        "",
        "The lead must do one of: add work (a queue row, a review, a decision), or close the idle sessions. "
        "An idle session inside this window is not a worker fault — it is an empty worklist.",
    ]
    return "\n".join(lines) + "\n"


def plan_lines(assignments: Sequence[Assignment], panes: Sequence[PaneState], *, dispatchable: bool) -> list[str]:
    """Human-readable dry-run plan: who is idle, what each would be sent, and why."""
    lines = []
    by_session = {a.session: a for a in assignments}
    for pane in panes:
        a = by_session.get(pane.session)
        if pane.state == "blind":
            lines.append(f"{pane.session:20} BLIND     capture failed; no verdict, nothing sent")
        elif a is None:
            lines.append(f"{pane.session:20} {pane.state.upper():9} nothing to dispatch")
        else:
            lines.append(f"{pane.session:20} {pane.state.upper():9} {a.kind:13} {a.target:>8}  why: {a.why}")
            if dispatchable:
                for chunk in a.instruction.splitlines() or [a.instruction]:
                    lines.append(f"{'':42}> {chunk}")
            else:
                lines.append(f"{'':42}> {a.instruction}")
    return lines
