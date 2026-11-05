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
from dataclasses import dataclass, field
from datetime import datetime, timezone
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

    @property
    def live(self) -> bool:
        return self.status == "active" and self.age_h <= CLAIM_LIVE_HOURS


def load_claims(claims_dir: Path, *, now: datetime | None = None) -> list[Claim]:
    """Read claim JSON files. Unreadable files are skipped, never guessed at."""
    ref = now or now_utc()
    out: list[Claim] = []
    for path in sorted(Path(claims_dir).glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or not d.get("claim_id"):
            continue
        hb = str(d.get("heartbeat_at") or d.get("started_at") or "")
        try:
            age = (ref - datetime.fromisoformat(hb.replace("Z", "+00:00"))).total_seconds() / 3600
        except ValueError:
            age = 1e9
        out.append(Claim(
            claim_id=str(d["claim_id"]), session=str(d.get("session") or ""),
            branch=str(d.get("branch") or ""), paths=[str(p) for p in (d.get("paths") or [])],
            head_sha=str(d.get("head_sha") or ""), status=str(d.get("status") or ""), age_h=age,
        ))
    return out


def row_paths(row: dict[str, Any]) -> list[str]:
    """A queue row's file claims: `paths` when present, else the single `path`/`file` keys some rows carry."""
    paths = [str(p) for p in (row.get("paths") or [])]
    for key in ("path", "file"):
        if row.get(key):
            paths.append(str(row[key]))
    return [p.strip() for p in paths if p and p.strip()]


def row_workable(row: dict[str, Any], session: str, claims: Sequence[Claim], *, now: datetime | None = None) -> tuple[bool, str]:
    """Is this queue row the session's to work right now? Returns (ok, reason-when-not)."""
    if str(row.get("owner") or "") != session:
        return False, "not owned by this session"
    return row_hold(row, claims, now=now, own_session=session)


def row_hold(row: dict[str, Any], claims: Sequence[Claim], *, now: datetime | None = None,
             own_session: str = "") -> tuple[bool, str]:
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
            if claim.live and wanted & set(claim.paths):
                return False, f"{sorted(wanted & set(claim.paths))[0]} held by {claim.session} ({claim.claim_id})"
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

    @property
    def clean(self) -> bool:
        return self.merge_state.upper() == "CLEAN" and not self.draft

    @property
    def shas(self) -> tuple[str, ...]:
        """The head plus every commit it carries — the set a claim's head_sha must be in to be current."""
        return tuple(dict.fromkeys([self.head_sha, *self.commit_shas]))


def verdicts_at_head(artifacts: Iterable[dict[str, Any]]) -> dict[tuple[int, str], list[dict[str, Any]]]:
    """Index review artifacts by (pr, head_sha) keeping only MERGE/BLOCK verdicts, with the reviewer named.

    Accepts both shapes in the tree: a companion file (``pr``, ``head_sha``, ``verdict``, ``reviewer_session``) and a
    registered evidence file (``pr``, ``head_sha``, ``reviews``: [{``verdict``/``verdict``, ``reviewer_session``}]).
    """
    index: dict[tuple[int, str], list[dict[str, Any]]] = {}
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
        rows = art.get("reviews") if isinstance(art.get("reviews"), list) else []
        entries = [{
            "verdict": str(r.get("verdict") or "").upper(),
            "reviewer": str(r.get("reviewer_session") or r.get("reviewer") or ""),
        } for r in rows if isinstance(r, dict)]
        if not entries and art.get("verdict"):
            entries = [{"verdict": str(art.get("verdict")).upper(),
                        "reviewer": str(art.get("reviewer_session") or art.get("reviewer") or "")}]
        merged = [e for e in entries if e["verdict"] in ("MERGE", "BLOCK")]
        if merged:
            index.setdefault((pr, head), []).extend(merged)
    return index


AUTHORITY_PATH = Path(__file__).resolve().parents[2] / "config" / "agent_standing_authority.json"


def review_requirements(path: Path | None = None) -> tuple[int, int, tuple[str, ...]]:
    """``(ordinary_reviews, held_reviews, excluded_globs)`` from the standing authority.

    claude-lead's review of this head: ``merge_ready`` called a held PR Ready on ONE MERGE while the config says
    ``held_reviews: 2``, and the review picker then skipped it because it already had a MERGE — so a held PR could never
    collect its second reviewer. The numbers belong to the operator's file, not to this module: unreadable config falls
    back to the published defaults rather than silently lowering the bar.
    """
    try:
        doc = json.loads(Path(path or AUTHORITY_PATH).read_text(encoding="utf-8"))
        block = (doc.get("capabilities") or {}).get("coordinator_merge") or {}
        ordinary = int(block.get("ordinary_reviews", 1))
        held = int(block.get("held_reviews", 2))
        globs = tuple(str(g) for g in (block.get("excluded_globs") or ()))
        return max(1, ordinary), max(1, held), globs
    except (OSError, ValueError, TypeError):
        return 1, 2, ()


def required_reviews(files: Sequence[str], requirements: tuple[int, int, tuple[str, ...]] | None = None) -> tuple[int, bool]:
    """``(how many independent MERGEs, is it held)`` for one change; an unreadable file list is HELD (fail closed)."""
    ordinary, held, globs = requirements or review_requirements()
    if not files:
        return held, True
    touched = any(fnmatch.fnmatchcase(f, g) for f in files for g in globs)
    return (held, True) if touched else (ordinary, False)


def merge_ready(prs: Sequence[PullRequest], verdicts: dict[tuple[int, str], list[dict[str, Any]]],
                claims: Sequence[Claim], author_of: dict[int, str]) -> dict[str, list[dict[str, Any]]]:
    """Split the open PRs into {ready, one_step}. Report only — the lead's helper remains the only merger."""
    ready: list[dict[str, Any]] = []
    one_step: list[dict[str, Any]] = []
    by_branch = {c.branch: c for c in claims if c.status == "active"}
    for pr in prs:
        if not pr.clean:
            continue
        here = verdicts.get((pr.number, pr.head_sha), [])
        blocks = [e for e in here if e["verdict"] == "BLOCK" and e["reviewer"] and e["reviewer"] != author_of.get(pr.number, "")]
        merges = [e for e in here if e["verdict"] == "MERGE"]
        merges = [e for e in merges if e["reviewer"] and e["reviewer"] != author_of.get(pr.number, "")]
        need, held = required_reviews(pr.files)
        reviewers = {e["reviewer"] for e in merges}
        claim = by_branch.get(pr.head_ref)
        claim_current = bool(claim and claim.head_sha and claim.head_sha in pr.shas)
        author = author_of.get(pr.number, "")
        base = {"pr": pr.number, "head": pr.head_sha, "branch": pr.head_ref,
                "author": author, "merge_state": pr.merge_state}
        if not author:
            # R5 (codex at fffe2c9cb): an unresolved author made independence unprovable and could still render a
            # ready entry with author="". "Ready to merge" is a claim about custody; without the author it is a guess.
            one_step.append({**base, "step": "author unknown — independence cannot be shown, so readiness cannot be "
                                             "claimed", "verdicts": sorted(reviewers)})
        elif blocks:
            one_step.append({**base, "step": "a BLOCK verdict stands at this head — resolve it, then re-review",
                             "verdicts": [e["reviewer"] for e in blocks]})
        elif reviewers and len(reviewers) < need:
            one_step.append({**base, "step": f"needs {need} independent MERGE verdicts"
                                              f"{' (held path)' if held else ''} — {len(reviewers)} at this head",
                             "verdicts": sorted(reviewers), "held": held, "needed": need})
        elif merges and claim_current:
            ready.append({**base, "verdicts": [e["reviewer"] for e in merges]})
        elif merges and not claim_current:
            # A DONE claim cannot be re-stamped (the CLI has no such move); the author creates a claim AT this head.
            step = ("the author claim is not active at this head — create a claim at the head and release it, then "
                    "the evidence names that claim" if claim is None else
                    "author must re-stamp the claim's head_sha to this head")
            one_step.append({**base, "step": step,
                             "claim_head": claim.head_sha if claim else None,
                             "verdicts": [e["reviewer"] for e in merges]})
        elif claim_current:
            one_step.append({**base, "step": "needs one independent MERGE verdict at this exact head",
                             "verdicts": []})
        else:
            one_step.append({**base, "step": "needs a current author claim and one independent MERGE verdict",
                             "claim_head": claim.head_sha if claim else None, "verdicts": []})
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
        lines.append(f"- **#{r['pr']}** `{r['branch']}` head `{r['head'][:9]}` — MERGE at this head from "
                     f"{', '.join(r['verdicts'])}; author claim is current.")
    lines += ["", f"## One step away ({len(ready['one_step'])})", ""]
    if not ready["one_step"]:
        lines.append("_None._")
    for r in ready["one_step"]:
        lines.append(f"- **#{r['pr']}** `{r['branch']}` head `{r['head'][:9]}` — {r['step']}"
                     + (f" (claim head `{str(r.get('claim_head'))[:9]}`)" if r.get("claim_head") else "")
                     + (f"; MERGE from {', '.join(r['verdicts'])}" if r["verdicts"] else ""))
    lines.append("")
    return "\n".join(lines)


# ── work selection (a → e) ──────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Assignment:
    session: str
    kind: str            # queue | review | merge_prep | unowned_queue | chore
    target: str          # row id, PR number, claim id …
    instruction: str
    why: str

    def as_dict(self) -> dict[str, Any]:
        return {"session": self.session, "kind": self.kind, "target": self.target,
                "instruction": self.instruction, "why": self.why}


def _row_instruction(session: str, row: dict[str, Any], coord: str) -> str:
    acc = row.get("acceptance")
    if isinstance(acc, dict):
        acceptance = " ".join(f"{k.capitalize()}: {str(acc.get(k) or '').strip()}"
                              for k in ("what", "expected", "actual", "evidence") if acc.get(k))
    else:
        acceptance = str(acc or "").strip()
    acceptance = acceptance[:600] + (" …" if len(acceptance) > 600 else "")
    return (f"Dispatcher: your next queue row is {row.get('id')} [{row.get('severity') or '?'}] — "
            f"{row.get('page') or 'no page'}"
            + (f" · check {row.get('check')}" if row.get("check") else "") + ". "
            f"Acceptance: {acceptance or 'see the queue file'}. "
            f"Work it now: claim the files, fix the root cause, produce red-then-green evidence, then report the head "
            f"sha to {coord}/inbox/<lead>/ and take your next row. If it no longer reproduces at the current head, "
            f"close it with the measurement that shows it gone.")


def _review_instruction(session: str, pr: PullRequest, coord: str) -> str:
    return (f"Dispatcher: review PR #{pr.number} whole-head now — head {pr.head_sha}, branch {pr.head_ref}, "
            f"mergeState {pr.merge_state}. You did not author it. Read the diff, run its tests, mutate the fix back to "
            f"show the tests fail without it, then file MERGE or BLOCK with findings at this exact head in "
            f"{coord}/review-evidence/ as .md + .machine.json (the canonical line is 'Adversarial-review: MERGE "
            f"reviewer={session} head={pr.head_sha}'), and report the verdict to {coord}/inbox/<lead>/. "
            f"Do not push, do not merge, do not edit the author's branch.")


def _merge_prep_instruction(session: str, pr: PullRequest, claim: Claim | None, coord: str) -> str:
    head = pr.head_sha
    return (f"Dispatcher: PR #{pr.number} is CLEAN with an exact-head MERGE verdict but cannot merge — the author "
            f"claim does not carry this head. Re-stamp the claim: run agent_claim.py heartbeat for claim "
            f"{claim.claim_id if claim else '<none>'} from the worktree whose HEAD is {head} "
            f"(branch {pr.head_ref}), then report the claim id and head to {coord}/inbox/<lead>/. Do not push or merge.")


def _chore_instruction(session: str, claim: Claim, coord: str, *, open_pr: bool = False) -> str:
    if open_pr:
        # R1 (cc-deepseek-2 at fffe2c9cb): "release --status done" on a claim whose branch still has an OPEN PR is the
        # move that permanently unmerges it — the merge gate needs a live claim at the PR head and a done claim cannot
        # be re-stamped. A chore on an open-PR branch is a resume-or-hand-off, never a release.
        return (f"Dispatcher: chore — claim {claim.claim_id} on branch {claim.branch} has not been heartbeated for "
                f"{claim.age_h:.1f}h, and its branch has an OPEN PR. Do NOT release it as done or abandoned: the merge "
                f"gate needs a live claim at the PR head, and a done claim cannot be re-stamped. Heartbeat it from the "
                f"worktree whose HEAD is the PR head, or hand it off with agent_claim.py handoff naming the exact next "
                f"step, then report to {coord}/inbox/<lead>/.")
    return (f"Dispatcher: chore — claim {claim.claim_id} on branch {claim.branch} has not been heartbeated for "
            f"{claim.age_h:.1f}h and no open PR depends on it. Either resume it (heartbeat from its worktree) or close "
            f"it with agent_claim.py release --status abandoned and a summary, then report to {coord}/inbox/<lead>/ so "
            f"the board is honest.")


def select_work(session: str, *, queue: Sequence[dict[str, Any]], claims: Sequence[Claim],
                prs: Sequence[PullRequest], verdicts: dict[tuple[int, str], list[dict[str, Any]]],
                author_of: dict[int, str], coord: str, now: datetime | None = None,
                reviewed_pairs: set[tuple[int, str]] | None = None,
                review_counts: dict[tuple[int, str], int] | None = None,
                taken: dict[tuple[str, str], int] | None = None,
                prior_review_sessions: dict[tuple[int, str], set[str]] | None = None) -> Assignment | None:
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

    def free(kind: str, target: str, *, allow: int = 1) -> bool:
        """Has this cycle already given this target away `allow` times?"""
        return handed.get((kind, target), 0) < allow

    # (a) its own workable rows, in queue order (the queue lists them in priority order)
    for row in queue:
        ok, _why = row_workable(row, session, claims, now=ref)
        if ok and free("queue", str(row.get("id"))):
            return Assignment(session, "queue", str(row.get("id")),
                              _row_instruction(session, row, coord), "own queued row")

    # (b) a review of a CLEAN PR it did not author and that has no MERGE verdict at its head yet.
    # Newest activity first: a live PR is the work, and an ancient CLEAN PR is the triage list (board row 26), not
    # somewhere to spend five sessions. At most MAX_REVIEWERS_PER_PR independent reviewers per head.
    for pr in sorted(prs, key=lambda p: (p.updated_at or "", p.number), reverse=True):
        if not pr.clean:
            continue
        author = author_of.get(pr.number) or ""
        if not author:
            continue  # F5: an unknown author means independence cannot be shown — fail closed, assign nobody
        if author == session:
            continue
        if (pr.number, session) in reviewed:
            continue
        if counts.get((pr.number, pr.head_sha), 0) >= MAX_REVIEWERS_PER_PR:
            continue
        if session in prior.get((pr.number, pr.head_sha), set()):
            continue  # an earlier cycle already sent this reviewer THIS head
        if not free("review", str(pr.number)):
            continue
        verdicts_here = verdicts.get((pr.number, pr.head_sha), [])
        need, _held = required_reviews(pr.files)
        merges_here = {v["reviewer"] for v in verdicts_here if v["verdict"] == "MERGE" and v["reviewer"]}
        if len(merges_here) >= need:
            continue  # the bar is met; a held PR with one MERGE still needs its second reviewer
        others = [v for v in verdicts_here if v["verdict"] == "BLOCK" and v["reviewer"] == session]
        if others:
            continue
        return Assignment(session, "review", str(pr.number),
                          _review_instruction(session, pr, coord), "PR is CLEAN and lacks an exact-head review")

    # (c) merge-prep: a CLEAN PR with a MERGE verdict whose author claim is stale on the head
    for pr in sorted(prs, key=lambda p: p.number):
        if not pr.clean or author_of.get(pr.number) != session:
            continue
        if not any(v["verdict"] == "MERGE" for v in verdicts.get((pr.number, pr.head_sha), [])):
            continue
        claim = next((c for c in claims if c.branch == pr.head_ref and c.status == "active"), None)
        if claim and claim.head_sha and claim.head_sha not in pr.shas and free("merge_prep", str(pr.number)):
            return Assignment(session, "merge_prep", str(pr.number),
                              _merge_prep_instruction(session, pr, claim, coord),
                              "MERGE verdict at head but the author claim carries a different head")

    # (d) the oldest unowned row — offered to whoever is idle first, by queue order
    for row in queue:
        if row.get("owner"):
            continue
        ok, _why = row_hold(row, claims, now=ref)  # R7: a blank owner does not bypass a hold or a live claim
        if not ok:
            continue
        if not free("unowned_queue", str(row.get("id"))):
            continue
        return Assignment(session, "unowned_queue", str(row.get("id")),
                          f"Dispatcher: unowned queue row {row.get('id')} — {row.get('page') or ''}. Claim it "
                          f"(agent_claim.py claim, then set owner via your report), fix it with red-then-green "
                          f"evidence, and report the head to {coord}/inbox/<lead>/.", "no owner on the row")

    # (e) a chore: a stale claim that no live session is progressing
    stale = [c for c in claims if c.status == "active" and c.age_h > CLAIM_LIVE_HOURS]
    if stale:
        claim = next((c for c in sorted(stale, key=lambda c: -c.age_h) if free("chore", c.claim_id)), None)
        if claim is None:
            return None
        open_pr = any(p.head_ref == claim.branch for p in prs)
        return Assignment(session, "chore", claim.claim_id, _chore_instruction(session, claim, coord, open_pr=open_pr),
                          f"claim is {claim.age_h:.1f}h stale")
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
                raise DispatchError(f"refusing to write {target}: it is the same file as the protected input "
                                    f"{candidate} (hardlink alias)")
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
    top = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if top.returncode != 0:
        return False
    try:
        rel = path.resolve().relative_to(Path(top.stdout.strip()).resolve()).as_posix()
    except ValueError:
        return False
    ls = subprocess.run(["git", "-C", str(top.stdout.strip()), "ls-files", "--error-unmatch", "--", rel],
                        capture_output=True, text=True)
    return ls.returncode == 0


def open_output(target: Path, *, append: bool = False):
    """Open one of this lane's own outputs through an identity-checked handle (R1, codex at fffe2c9cb).

    ``safe_output_path`` is a precheck, and a precheck is not a fence: the file can be replaced between the check and
    the write (codex swapped MERGE_READY.md for a symlink into the queue during the first send and the report truncated
    the queue). The write therefore opens without following symlinks, and a file with more than one link is refused
    outright — that catches a hardlink alias at ANY depth, where the precheck only walks two.

    Callers get a text handle; the checks happened on the very inode that will be written.
    """
    # No O_TRUNC: truncation is a WRITE, and the whole point is to inspect the handle before any byte changes. A
    # hardlink alias opened with O_TRUNC would empty the protected file first and refuse afterwards.
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_APPEND if append else 0)
    try:
        fd = os.open(str(target), flags, 0o644)
    except OSError as exc:
        raise DispatchError(f"refusing to write {target}: {exc}") from exc
    try:
        st = os.fstat(fd)
        if st.st_nlink != 1:
            raise DispatchError(f"refusing to write {target}: it has {st.st_nlink} links (an alias of another file)")
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
            return SubmitResult(False, False, attempt, "pre-paste capture failed: refusing to send to a pane I cannot see")
        admitted = classify_pane(session, before)
        if admitted.state != "idle":
            return SubmitResult(False, False, attempt,
                                f"refusing to send: pane is {admitted.state} at send time ({admitted.evidence})")
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


def ledger_line(*, session: str, assignment: Assignment, result: SubmitResult, cycle_id: str, ts: str | None = None,
                target_head: str = "") -> str:
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
    lines = ["# DISPATCH_IDLE_ALERT — nobody has work and sessions are waiting", "",
             f"Generated {generated_at} by scripts/agent_dispatch.py. This file assigns nothing; it asks the lead for a decision.",
             "",
             "The dispatcher found no work to hand out in this cycle (no queued/assigned rows, no CLEAN PR needing a "
             "review, no merge-prep, no unowned row, no chore) while these sessions were idle:", ""]
    lines += [f"- **{s}** idle {m:.0f} min" for s, m in over]
    lines += ["", "The lead must do one of: add work (a queue row, a review, a decision), or close the idle sessions. "
                  "An idle session inside this window is not a worker fault — it is an empty worklist."]
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
