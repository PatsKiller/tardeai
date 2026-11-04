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

import hashlib
import json
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
    for claim in claims:
        if claim.session != session and claim.live and wanted & set(claim.paths):
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
        claim = by_branch.get(pr.head_ref)
        claim_current = bool(claim and claim.head_sha and claim.head_sha in pr.shas)
        base = {"pr": pr.number, "head": pr.head_sha, "branch": pr.head_ref,
                "author": author_of.get(pr.number, ""), "merge_state": pr.merge_state}
        if blocks:
            one_step.append({**base, "step": "a BLOCK verdict stands at this head — resolve it, then re-review",
                             "verdicts": [e["reviewer"] for e in blocks]})
        elif merges and claim_current:
            ready.append({**base, "verdicts": [e["reviewer"] for e in merges]})
        elif merges and not claim_current:
            one_step.append({**base, "step": "author must re-stamp the claim's head_sha to this head",
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
            f"show the tests fail without it, then file MERGE or BLOCK with findings at this exact head in {coord}/inbox/<lead>/ "
            f"(the canonical line is 'Adversarial-review: MERGE reviewer={session} head={pr.head_sha}') and the companion JSON. "
            f"Do not push, do not merge, do not edit the author's branch.")


def _merge_prep_instruction(session: str, pr: PullRequest, claim: Claim | None, coord: str) -> str:
    head = pr.head_sha
    return (f"Dispatcher: PR #{pr.number} is CLEAN with an exact-head MERGE verdict but cannot merge — the author "
            f"claim does not carry this head. Re-stamp the claim: run agent_claim.py heartbeat for claim "
            f"{claim.claim_id if claim else '<none>'} from the worktree whose HEAD is {head} "
            f"(branch {pr.head_ref}), then report the claim id and head to {coord}/inbox/<lead>/. Do not push or merge.")


def _chore_instruction(session: str, claim: Claim, coord: str) -> str:
    return (f"Dispatcher: chore — claim {claim.claim_id} on branch {claim.branch} has not been heartbeated for "
            f"{claim.age_h:.1f}h. Either resume it (heartbeat from its worktree) or close it with agent_claim.py "
            f"release --status done|abandoned and a summary, then report to {coord}/inbox/<lead>/ so the board is honest.")


def select_work(session: str, *, queue: Sequence[dict[str, Any]], claims: Sequence[Claim],
                prs: Sequence[PullRequest], verdicts: dict[tuple[int, str], list[dict[str, Any]]],
                author_of: dict[int, str], coord: str, now: datetime | None = None,
                reviewed_pairs: set[tuple[int, str]] | None = None,
                review_counts: dict[int, int] | None = None,
                taken: dict[tuple[str, str], int] | None = None,
                prior_review_sessions: dict[int, set[str]] | None = None) -> Assignment | None:
    """The one next thing for this session, in the operator's order (a)…(e). None means "nothing to do".

    `reviewed_pairs` is (pr number, reviewer session) pairs already dispatched this cycle, so two sessions are not
    sent the same PR by the same scan.
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
        if counts.get(pr.number, 0) >= MAX_REVIEWERS_PER_PR:
            continue
        if session in prior.get(pr.number, set()):
            continue  # an earlier cycle already sent this reviewer this PR
        if not free("review", str(pr.number)):
            continue
        verdicts_here = verdicts.get((pr.number, pr.head_sha), [])
        if any(v["verdict"] == "MERGE" for v in verdicts_here):
            continue
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
        if str(row.get("status") or "") not in WORK_STATUSES:
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
        return Assignment(session, "chore", claim.claim_id, _chore_instruction(session, claim, coord),
                          f"claim is {claim.age_h:.1f}h stale")
    return None


# ── submit and the ledger ──────────────────────────────────────────────────────────────────────────────────────


@dataclass
class SubmitResult:
    submitted: bool
    busy_after: bool
    attempts: int
    detail: str


def safe_output_path(target: Path, *, coord: Path, protected: Sequence[Path] = ()) -> Path:
    """Refuse an output path that could write one of the lane's own inputs (F2).

    The dispatcher writes exactly three files. If any of them resolves to the queue, a claims directory, the review
    evidence or the coordinator's inbox — through a symlink, a "../" path or a typo — a bug in this lane would edit
    the very records it is supposed to read. Refuse before sending or writing; a refusal is a refusal, never a
    best-effort write.
    """
    target = Path(target)
    if target.is_symlink():
        raise DispatchError(f"refusing to write {target}: it is a symlink")
    real = target.resolve(strict=False)
    forbidden = [Path(p).resolve(strict=False) for p in protected]
    forbidden += [(Path(coord) / name).resolve(strict=False)
                  for name in ("AUDIT_FIX_QUEUE.json", "inbox", "review-evidence", "claims")]
    for bad in forbidden:
        if real == bad or bad in real.parents:
            raise DispatchError(f"refusing to write {target}: resolves inside a protected input ({bad})")
    parent = real.parent
    if parent.exists() and parent.is_symlink():
        raise DispatchError(f"refusing to write {target}: its directory is a symlink out of the tree")
    return real


def _tail_hash(screen: str) -> str:
    tail = "\n".join(ln for ln in (screen or "").splitlines() if ln.strip())[-1200:]
    return hashlib.sha256(tail.encode()).hexdigest()


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

    Two properties the reviewer required (F3), because a submit that "confirms" the wrong thing is worse than none:
    * **wall-clock bounded** — every wait is measured with a monotonic clock against a deadline, and every subprocess
      call carries its own timeout, so a wedged tmux cannot extend a cycle past its budget;
    * **evidence is new** — the pane is captured before the paste and again after Enter, and busy only counts when the
      capture both carries a busy marker and differs from the pre-paste capture. A pane that was already busy (a
      stale spinner) is therefore not mistaken for the result of this dispatch.
    One retry, then the caller logs ``dispatch_failed``.
    """
    buffer_name = "dispatch-" + hashlib.sha256(f"{session}:{text}:{time.time()}".encode()).hexdigest()[:12]

    def _capture() -> str | None:
        proc = run(["tmux", "capture-pane", "-p", "-t", session], capture_output=True, text=True,
                   timeout=RUN_TIMEOUT_S)
        return (proc.stdout or "") if getattr(proc, "returncode", 1) == 0 else None

    def _paste_and_enter() -> bool:
        load = run(["tmux", "load-buffer", "-b", buffer_name, "-"], input=text, capture_output=True, text=True,
                   timeout=RUN_TIMEOUT_S)
        if getattr(load, "returncode", 1) != 0:
            return False
        paste = run(["tmux", "paste-buffer", "-b", buffer_name, "-t", session, "-d"],
                    capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
        if getattr(paste, "returncode", 1) != 0:
            return False
        sleep(0.6)  # let the compositor register the paste before Enter
        enter = run(["tmux", "send-keys", "-t", session, "Enter"], capture_output=True, text=True,
                    timeout=RUN_TIMEOUT_S)
        return getattr(enter, "returncode", 1) == 0

    attempts = 0
    for attempt in (1, 2):
        attempts = attempt
        before = _capture()
        if not _paste_and_enter():
            continue
        deadline = monotonic() + busy_confirm_seconds
        while monotonic() < deadline:
            sleep(min(poll_every, max(0.0, deadline - monotonic())))
            screen = _capture()
            if screen is None:
                continue
            if BUSY_RE.search(screen) and _tail_hash(screen) != _tail_hash(before or ""):
                return SubmitResult(True, True, attempts, "busy confirmed on a new capture after the paste")
    return SubmitResult(attempts > 0, False, attempts, "no new busy marker within the confirm window")


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
