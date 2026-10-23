#!/usr/bin/env python3
"""agent_claim.py — the multi-vendor agent claim board CLI (operator-approved 2026-10-22).

Before an agent (Claude, Codex, Cursor — equal peers, no master) edits files, it claims them; before it
commits, ``check`` tells it whether another live session holds them. Store and semantics:
``scripts/lib/agent_claim_board.py`` and ``docs/ops/AGENT_CLAIM_BOARD.md``.

  claim      --task T --paths P [P ...] [--branch B] [--pr N] [--note X]
             refuse (exit 1) if any live claim of another session overlaps a path/glob; prints the holder,
             branch and since. A stale claim (no heartbeat for 2 h) is taken over and recorded.
  heartbeat  CLAIM_ID [--pr N] [--note X]          refresh; refused once taken over
  stage      CLAIM_ID building|pr_open [--pr N]    declare a lifecycle stage (owner only); ci_green, merged and
             released are observed, never declared
  sync       --dry-run | --apply [--json]          auto-advance stages from GitHub (GET only) + release receipts;
             --apply writes the lifecycle cache files (lifecycle/<claim_id>.json)
  precommit  --paths P [P ...]                     the pre-commit gate: warn-only below AGENTS.md 20.0.0 ACTIVE;
             from 20.0.0 ACTIVE exit 10 (hook: 1) when a staged file is held by another live session or not covered by
             one of this session's claims. TRADEAI_CLAIM_OVERRIDE=<reason> bypasses and is logged to the history
  release    CLAIM_ID [--status done|abandoned] [--note X]
  list       [--json] [--all]                      live + stale by default; --all adds done/abandoned
  check      --paths P [P ...] [--no-gh] [--warn-only] [--exclude-branch B]
             exit 0 clear, 1 conflict (live claim of another session, or an open draft PR changing the
             path); --warn-only prints the same and exits 0 (the pre-commit hook mode)
  compact    --dry-run | --apply [--lane-receipt]  archive done/stale > 7 days to claims_history.jsonl, then
             remove the claim files (the archive is the durable copy)

Lifecycle: claimed -> building -> pr_open -> ci_green -> merged -> released (live) | abandoned. A claim frees its
files at merged and stays on the board until released. --no-gh (or AGENT_CLAIM_NO_GH=1) never calls GitHub.

Identity: --vendor/--session/--agent, else AGENT_CLAIM_VENDOR / AGENT_CLAIM_SESSION / AGENT_CLAIM_AGENT, else a
best-effort environment hint. Claims dir: --claims-dir, else TRADEAI_AGENT_CLAIMS_DIR, else
~/trade-ai-releases/persistent-state/data/coordination/claims/.

Exit codes: 0 ok · 1 conflict / refused claim · 2 usage or ownership error.
AUTHORITY: READ_ONLY_ADVISORY — coordination files only; no broker, DB, Telegram, scheduler or remote write
(``gh pr list`` is a read).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import agent_claim_board as B  # noqa: E402
from scripts.lib import agent_task_board as TB  # noqa: E402

LANE_ID = "agent-claim-compact"
PRECOMMIT_BLOCK = 10  # precommit: the gate blocked (distinct from 1, a Python crash); the hook maps it to exit 1
SCRIPT = "scripts/agent_claim.py"


def _observer(a: argparse.Namespace) -> B.LC.LifecycleObserver:
    no_gh = (
        getattr(a, "no_gh_global", False) or getattr(a, "no_gh", False) or os.environ.get("AGENT_CLAIM_NO_GH") == "1"
    )
    gh = None if no_gh else B.LC.GitHubReader(timeout_s=a.gh_call_timeout)
    return B.LC.LifecycleObserver(gh, B.LC.ReleaseReader())


def _board(a: argparse.Namespace, *, observe: bool = True) -> B.ClaimBoard:
    return B.ClaimBoard(
        a.claims_dir,
        stale_after_hours=a.stale_hours,
        compact_after_days=a.compact_days,
        observer=_observer(a) if observe else None,
    )


def _session(a: argparse.Namespace) -> str | None:
    return a.session or B.detect_session()


def _print_conflicts(rows: list[dict], *, stream=None, prefix: str = "CONFLICT") -> None:
    stream = stream or sys.stderr
    for r in rows:
        held = ", ".join(sorted({o["held"] for o in r.get("overlaps") or []}))
        mine = ", ".join(sorted({o["path"] for o in r.get("overlaps") or []}))
        if r.get("source") == "draft_pr":
            print(
                f"{prefix}: {mine} — open draft PR #{r.get('pr')} on branch {r.get('branch')} changes {held}"
                + (f" ({r['url']})" if r.get("url") else ""),
                file=stream,
            )
        else:
            print(
                f"{prefix}: {mine} — held by {r.get('vendor')}/{r.get('agent') or '-'} session {r.get('session')}"
                f" on branch {r.get('branch') or '?'} since {r.get('started_at')} (last heartbeat"
                f" {r.get('heartbeat_at')}; claim {r.get('claim_id')}; task: {r.get('task')})",
                file=stream,
            )


# --------------------------------------------------------------------------------------------- git (read-only)


def _git(args: list[str], cwd: str | Path | None = None, timeout: float = 10) -> str | None:
    """Local read-only git; None on any failure."""
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def _toplevel(cwd: str | Path | None = None) -> str | None:
    return _git(["rev-parse", "--show-toplevel"], cwd)


def _head(cwd: str | Path | None = None) -> str | None:
    return _git(["rev-parse", "HEAD"], cwd)


def _commits_since(base: str | None, head: str, cwd: str | Path | None) -> list[tuple[str, str]]:
    """(sha, subject) of commits in base..head, oldest first (max 50). Just head when base is unknown/unrelated."""
    if base == head:
        return []
    out = None
    if base and _git(["merge-base", "--is-ancestor", base, head], cwd) is not None:
        out = _git(["log", "--reverse", "--max-count=50", "--format=%H %s", f"{base}..{head}"], cwd)
    if out is None:
        out = _git(["log", "-1", "--format=%H %s", head], cwd)
    rows = []
    for ln in (out or "").splitlines():
        sha, _, subj = ln.partition(" ")
        if sha:
            rows.append((sha, subj))
    return rows


def _create_worklog(board: B.ClaimBoard, doc: dict, a: argparse.Namespace, carried: str | None = None) -> None:
    wl = board.worklog(doc["claim_id"])
    if wl.exists():
        return
    wl.create(
        doc,
        goal=getattr(a, "goal", None),
        request=getattr(a, "request", None),
        plan=list(getattr(a, "plan", None) or []),
        worktree=doc.get("worktree"),
    )


def cmd_claim(a: argparse.Namespace) -> int:
    board = _board(a)
    session = _session(a)
    if not session:
        print("error: --session (or AGENT_CLAIM_SESSION) is required to claim", file=sys.stderr)
        return 2
    if a.add:  # extend an existing claim
        try:
            cid = _resolve_claim(board, a)
            doc = board.extend(cid, a.add, session=session)
        except B.ClaimConflict as exc:
            _print_conflicts(exc.conflicts)
            print("refused: the added paths are claimed by another live session.", file=sys.stderr)
            return 1
        except (B.ClaimError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(doc, indent=2, sort_keys=True) if a.json else f"{cid} paths: {', '.join(doc['paths'])}")
        return 0
    if not a.task or not a.paths:
        print("error: claim needs --task and --paths (or --add <paths> to extend a claim)", file=sys.stderr)
        return 2
    branch = a.branch or B.current_branch()
    try:
        doc = board.claim(
            vendor=a.vendor or B.detect_vendor(),
            session=session,
            agent=a.agent or None,
            task=a.task,
            paths=a.paths,
            branch=branch,
            pr=a.pr,
            note=a.note,
            worktree=_toplevel(),
            head_sha=_head(),
        )
    except B.ClaimConflict as exc:
        _print_conflicts(exc.conflicts)
        print(
            "refused: the paths above are claimed by another live session. Coordinate, or wait for release.",
            file=sys.stderr,
        )
        return 1
    except (B.ClaimError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        _create_worklog(board, doc, a)
    except (OSError, B.WL.WorklogError) as exc:
        print(f"WARN: worklog not created ({type(exc).__name__}: {exc})", file=sys.stderr)
    if not getattr(a, "plan", None):
        print(
            f"next: add your plan -- python3 scripts/agent_claim.py plan '<step>'  (worklog {B.WL.path_for(board.dir, doc['claim_id'])})",
            file=sys.stderr,
        )
    if a.json:
        print(json.dumps(doc, indent=2, sort_keys=True))
    else:
        print(doc["claim_id"])
        for t in doc.get("takeover_of") or []:
            print(
                f"TAKEOVER: stale claim {t['claim_id']} ({t.get('vendor')}/{t.get('session')}, last heartbeat"
                f" {t.get('heartbeat_at')}) recorded in takeover_of",
                file=sys.stderr,
            )
    return 0


def cmd_heartbeat(a: argparse.Namespace) -> int:
    board = _board(a, observe=False)
    head, top = _head(), _toplevel()
    try:
        prev = board.get(a.claim_id).doc
        doc = board.heartbeat(
            a.claim_id, session=_session(a), pr=a.pr, note=a.note, branch=a.branch, head_sha=head, worktree=top
        )
        if head and head != prev.get("logged_sha"):  # commits since the last logged SHA go to the worklog
            wl = board.worklog(a.claim_id)
            if wl.exists():
                for sha, subj in _commits_since(prev.get("logged_sha"), head, top):
                    wl.change(f"commit {sha[:12]} {subj}")
            board.heartbeat(a.claim_id, session=_session(a), logged_sha=head)
    except B.ClaimConflict as exc:
        _print_conflicts(exc.conflicts)
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    except (B.ClaimError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(doc, indent=2, sort_keys=True) if a.json else f"{doc['claim_id']} heartbeat {doc['heartbeat_at']}")
    return 0


def cmd_stage(a: argparse.Namespace) -> int:
    try:
        doc = _board(a, observe=False).stage(a.claim_id, a.stage, session=_session(a), pr=a.pr, note=a.note)
    except (B.ClaimError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(doc, indent=2, sort_keys=True) if a.json else f"{doc['claim_id']} {a.stage} {doc['stages'][a.stage]}"
    )
    return 0


def cmd_sync(a: argparse.Namespace) -> int:
    board = _board(a)
    try:
        res = board.sync(apply=a.apply)
    except OSError as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if res.get("github_warning"):
        print(f"WARN: {res['github_warning']}", file=sys.stderr)
    if a.json:
        print(json.dumps(res, indent=2, sort_keys=True))
    else:
        print(f"{res['mode']}: observed {res['observed']} claim(s); {len(res['changes'])} stage change(s)")
        for c in res["changes"]:
            print(
                f"  {c['claim_id']}: {c['from']} -> {c['to']}" + ("  (files released)" if c["locks_released"] else "")
            )
    return 0


def cmd_precommit(a: argparse.Namespace) -> int:
    try:
        return _precommit(a)
    except Exception as exc:  # noqa: BLE001 - rc 3 = the gate could not run; the hook decides by policy state
        print(f"agent-claim: precommit gate crashed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 3


def _precommit(a: argparse.Namespace) -> int:
    branch = a.exclude_branch if a.exclude_branch is not None else B.current_branch()
    res = B.precommit_gate(
        _board(a),
        a.paths,
        session=_session(a),
        vendor=a.vendor or B.detect_vendor(),
        branch=branch,
        agents_md=Path(a.agents_md) if a.agents_md else ROOT / "AGENTS.md",
        override=os.environ.get(B.ENV_OVERRIDE),
    )
    for line in res["messages"]:
        print(line, file=sys.stderr)
    if a.json:
        print(json.dumps(res, indent=2, sort_keys=True))
    return PRECOMMIT_BLOCK if res["exit_code"] else 0


def _resolve_claim(board: B.ClaimBoard, a: argparse.Namespace) -> str:
    """--claim, else this session's one active claim (on the current branch when there are several)."""
    if getattr(a, "claim", None):
        return a.claim
    session = _session(a)
    branch = B.current_branch()
    mine = [
        v for v in board.views()[0] if v.doc.get("status") == "active" and session and v.doc.get("session") == session
    ]
    if len(mine) > 1 and branch:
        on_branch = [v for v in mine if v.doc.get("branch") == branch]
        mine = on_branch or mine
    if len(mine) == 1:
        return mine[0].claim_id
    if not mine:
        raise B.ClaimError(f"no active claim of session {session!r}; pass --claim <claim_id>")
    mine.sort(key=lambda v: v.doc.get("started_at") or "")
    raise B.ClaimError(
        "several active claims of this session: " + ", ".join(v.claim_id for v in mine) + "; pass --claim <claim_id>"
    )


def _worklog_cmd(a: argparse.Namespace, fn) -> int:
    board = _board(a, observe=False)
    try:
        cid = _resolve_claim(board, a)
        v = board.get(cid)
        if v.doc.get("session") != _session(a) and not a.force:
            raise B.ClaimError(
                f"claim {cid} belongs to session {v.doc.get('session')!r}; --force writes another session's worklog"
            )
        out = fn(board.worklog(cid))
    except (B.ClaimError, B.WL.WorklogError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{cid} {out}")
    return 0


def cmd_plan(a: argparse.Namespace) -> int:
    return _worklog_cmd(a, lambda w: (w.plan(a.step), f"plan + {a.step}")[1])


def cmd_done(a: argparse.Namespace) -> int:
    return _worklog_cmd(a, lambda w: f"done ✓ {w.done(a.step)}")


def cmd_note(a: argparse.Namespace) -> int:
    return _worklog_cmd(
        a, lambda w: (w.note(a.text, change=a.change), "change noted" if a.change else "decision noted")[1]
    )


def cmd_blocker(a: argparse.Namespace) -> int:
    return _worklog_cmd(a, lambda w: (w.blocker(a.text), "blocker noted")[1])


def cmd_handoff(a: argparse.Namespace) -> int:
    return _worklog_cmd(
        a,
        lambda w: (
            w.handoff(next_step=a.next, verify=a.verify, worktree=a.worktree, branch=a.branch),
            "handoff updated",
        )[1],
    )


def cmd_takeover(a: argparse.Namespace) -> int:
    """Print the Handoff section first; with --claim, take the work over: new claim on the same paths and branch whose
    worklog carries the old one forward, and a 'taken over by' line in both."""
    board = _board(a)
    try:
        v = board.get(a.claim_id)
    except B.ClaimError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    old = v.doc
    wl_old = board.worklog(a.claim_id)
    text = wl_old.read() if wl_old.exists() else ""
    print(B.WL.handoff_text(text) if text else "## Handoff\n(no worklog for this claim)\n")
    wt = old.get("worktree")
    print("## Where the work is")
    print(f"- branch: {old.get('branch') or '?'}  · claim head SHA {str(old.get('head_sha') or '?')[:12]}")
    if wt and Path(wt).is_dir():
        print(f"- worktree: cd {wt}   (live HEAD {str(_head(wt) or '?')[:12]})")
    elif old.get("branch"):
        print(
            f"- worktree {wt or '?'} is not on this host: git worktree add ~/wt-takeover-{old['claim_id'][-8:]} {old['branch']}"
        )
    print(f"- worklog: {wl_old.path}")
    if not a.claim:
        print("\n(read only) re-run with --claim to take this work over", file=sys.stderr)
        return 0
    session = _session(a)
    if not session:
        print("error: --session (or AGENT_CLAIM_SESSION) is required to take over", file=sys.stderr)
        return 2
    vendor = a.vendor or B.detect_vendor()
    try:
        doc = board.claim(
            vendor=vendor,
            session=session,
            agent=a.agent or None,
            task=a.task or f"takeover of {a.claim_id}: {old.get('task')}",
            paths=old.get("paths") or [],
            branch=old.get("branch"),
            pr=old.get("pr"),
            note=f"takeover of {a.claim_id}",
            worktree=wt if wt and Path(wt).is_dir() else _toplevel(),
            head_sha=_head(wt) if wt and Path(wt).is_dir() else _head(),
        )
    except B.ClaimConflict as exc:
        _print_conflicts(exc.conflicts)
        print(
            "refused: the claim is still live and holds these files. Ask its owner to release it (or wait until it "
            "goes stale / its PR merges), then take over.",
            file=sys.stderr,
        )
        return 1
    except (B.ClaimError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    t = B.iso(board.now())
    prev = f"{old.get('vendor')}/{old.get('session')} (claim {a.claim_id})"
    line = f"taken over by {vendor}/{session} at {t} from {prev}"
    try:
        new_wl = board.worklog(doc["claim_id"])
        if text:
            new_wl.carry_forward(text, doc, line)
        else:
            _create_worklog(board, doc, a)
            new_wl.status(line)
        if wl_old.exists():
            wl_old.status(f"{line} -> new claim {doc['claim_id']}")
    except (OSError, B.WL.WorklogError) as exc:
        print(f"WARN: worklog carry-forward failed ({type(exc).__name__}: {exc})", file=sys.stderr)
    print(f"\n{doc['claim_id']}  ({line})")
    return 0


def _local_only_branches(cwd: str | Path | None, *, days: int, limit: int) -> list[dict]:
    """Local branches with commits on no remote, committed in the last ``days`` days (newest first, ``limit``)."""
    out = _git(
        [
            "for-each-ref",
            "refs/heads",
            "--sort=-committerdate",
            f"--count={limit * 4}",
            "--format=%(refname:short)%09%(objectname)%09%(committerdate:unix)",
        ],
        cwd,
    )
    if out is None:
        return []
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    worktrees: dict[str, str] = {}
    wl = _git(["worktree", "list", "--porcelain"], cwd) or ""
    cur = None
    for ln in wl.splitlines():
        if ln.startswith("worktree "):
            cur = ln[9:]
        elif ln.startswith("branch refs/heads/") and cur:
            worktrees[ln[18:]] = cur
    rows = []
    for ln in out.splitlines():
        try:
            name, sha, ts = ln.split("\t")
        except ValueError:
            continue
        if float(ts or 0) < cutoff:
            break
        n = _git(["rev-list", "--count", sha, "--not", "--remotes"], cwd)
        if n and n != "0":
            rows.append({"branch": name, "head_sha": sha, "unpushed_commits": int(n), "worktree": worktrees.get(name)})
        if len(rows) >= limit:
            break
    return rows


def _open_pr_branches(timeout_s: float) -> tuple[set[str] | None, str | None]:
    try:
        p = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--limit", "300", "--json", "headRefName"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"gh unavailable ({type(exc).__name__}): open PRs not checked"
    if p.returncode != 0:
        return None, f"gh exited {p.returncode}: open PRs not checked"
    try:
        return {r.get("headRefName") for r in json.loads(p.stdout or "[]")}, None
    except ValueError:
        return None, "gh returned unparseable JSON: open PRs not checked"


def cmd_status(a: argparse.Namespace) -> int:
    """First command of any new session (Claude, Codex, Cursor): what is in flight, what can be taken over, what
    local work is at risk."""
    board = _board(a)
    if not a.no_observe:
        board.refresh_claims(write=False)
    view = board.board(include_finished=False)
    rows = view["claims"]
    in_flight = [r for r in rows if r["state"] == "live" and r["stage"] not in ("released", "abandoned")]
    takeable = [r for r in rows if r["state"] in ("stale", "done") or r.get("taken_over_by")]
    cwd = a.repo or None
    local = _local_only_branches(cwd, days=a.days, limit=a.limit)
    open_prs, warn = (
        (None, "GitHub not consulted (--no-gh)") if a.no_gh_global else _open_pr_branches(a.gh_call_timeout)
    )
    at_risk = []
    for r in local:
        r["open_pr"] = None if open_prs is None else r["branch"] in open_prs
        if not r["open_pr"]:
            at_risk.append(r)

    def live_head(r: dict) -> str | None:
        wt = r.get("worktree")
        if wt and Path(wt).is_dir():
            return _head(wt)
        return _git(["rev-parse", "--verify", "-q", f"refs/heads/{r['branch']}"], cwd) if r.get("branch") else None

    for r in in_flight + takeable:
        r["live_head_sha"] = live_head(r)
    out = {
        "schema": "AgentClaimStatus@v1",
        "at": view["as_of"],
        "claims_dir": view["claims_dir"],
        "in_flight": in_flight,
        "takeover_candidates": takeable,
        "local_only_at_risk": at_risk,
        "local_only_scanned_days": a.days,
        "github_warning": warn or view["lifecycle"].get("warning"),
    }
    if a.json:
        print(json.dumps(out, indent=2, sort_keys=True, default=str))
        return 0

    def line(r: dict) -> str:
        w = r.get("worklog") or {}
        plan = f"{w.get('plan_done', 0)}/{w.get('plan_total', 0)}" if w.get("exists") else "no worklog"
        return (
            f"- {r['claim_id']}  [{r['stage']}]  {r.get('vendor')}/{r.get('agent') or r.get('session')}  "
            f"age {_age(r.get('age_minutes'))}  branch {r.get('branch') or '?'}  "
            f"head {str(r.get('live_head_sha') or r.get('worktree_head_sha') or r.get('head_sha') or '?')[:12]}\n"
            f"    task: {r.get('task')}\n    worktree: {r.get('worktree') or '?'}   plan {plan}\n"
            f"    handoff: {w.get('next_step') or '(not set)'}"
        )

    print(f"# Agent board status  {out['at']}  ({out['claims_dir']})")
    print(f"\n## In flight ({len(in_flight)})")
    print("\n".join(line(r) for r in in_flight) or "(none)")
    print(f"\n## Stale or can be taken over ({len(takeable)})  -> agent_claim.py takeover <claim_id>")
    print("\n".join(line(r) + f"\n    why: {r['state']}" for r in takeable) or "(none)")
    print(f"\n## Local-only work at risk ({len(at_risk)}): commits on no remote and no open PR, last {a.days} d")
    for r in at_risk:
        print(
            f"- {r['branch']}  {r['unpushed_commits']} unpushed  head {r['head_sha'][:12]}  worktree {r['worktree'] or '-'}"
            + ("" if r["open_pr"] is False else "  (open PRs not checked)")
        )
    if not at_risk:
        print("(none)")
    if out["github_warning"]:
        print(f"\nWARN: {out['github_warning']}", file=sys.stderr)
    return 0


def _age(minutes: float | None) -> str:
    if minutes is None:
        return "?"
    return (
        f"{minutes:.0f}m" if minutes < 120 else (f"{minutes / 60:.1f}h" if minutes < 2880 else f"{minutes / 1440:.0f}d")
    )


def _tasks(a: argparse.Namespace) -> TB.TaskBoard:
    return TB.TaskBoard(_board(a))


def _print_task(t: dict, *, full: bool = False) -> None:
    own = t.get("owner") or {}
    print(
        f"{t['task_id']}  [{t['status']}] P{t.get('priority')} {t.get('kind')}  {t.get('title')}"
        + (f"  — {own.get('vendor')}/{own.get('agent') or own.get('session')}" if own else "")
    )
    if full:
        for k in ("areas", "depends_on", "acceptance", "children"):
            if t.get(k):
                print(f"  {k}: " + "; ".join(map(str, t[k])))
        for k in ("operator_quote", "estimate", "actual", "claim_id", "handoff", "parent", "taken_at", "done_at"):
            if t.get(k):
                print(f"  {k}: {t[k]}")
        for ev in t.get("history") or []:
            print(
                f"  · {ev.get('at')} {ev.get('event')} "
                + " ".join(f"{k}={v}" for k, v in ev.items() if k not in ("at", "event"))
            )


def cmd_task(a: argparse.Namespace) -> int:
    tb = _tasks(a)
    who = f"{a.vendor or B.detect_vendor()}/{_session(a)}"
    try:
        if a.task_cmd == "add":
            t = tb.add(
                task_id=a.id,
                title=a.title,
                kind=a.kind,
                areas=a.areas,
                depends_on=a.depends_on or [],
                priority=a.priority,
                acceptance=a.acceptance or [],
                operator_quote=a.quote,
                estimate=a.estimate,
                created_by=who,
            )
            print(json.dumps(t, indent=2, sort_keys=True) if a.json else t["task_id"])
        elif a.task_cmd == "split":
            kids = tb.split(a.task_id, [TB.parse_part(p) for p in a.part], by=who)
            for k in kids:
                print(k["task_id"])
        elif a.task_cmd == "list":
            view = tb.board()
            rows = [r for r in view["tasks"] if not a.status or r["column"] == a.status or r["status"] == a.status]
            if a.json:
                print(json.dumps({**view, "tasks": rows}, indent=2, sort_keys=True))
            else:
                for r in rows:
                    blocked = f"  blocked by {', '.join(r['blocked_by'])}" if r["blocked_by"] else ""
                    own = r.get("owner") or {}
                    print(
                        f"{r['task_id']}  {r['column']:<11} P{r['priority']} {r['kind']:<6} {r['title']}"
                        + (f"  — {own.get('vendor')}/{own.get('agent') or own.get('session')}" if own else "")
                        + blocked
                    )
                if not rows:
                    print("no tasks")
        elif a.task_cmd == "show":
            t = tb.get(a.task_id)
            if a.json:
                print(json.dumps(t, indent=2, sort_keys=True))
            else:
                _print_task(t, full=True)
        elif a.task_cmd == "done":
            t = tb.done(a.task_id, session=_session(a), summary=a.summary, force=a.force, actual_cost=a.cost)
            print(f"{t['task_id']} done {t['done_at']} (actual {t['actual']})")
            print(
                "next: open/finish the PR; the claim moves on to merged/released by itself. Then: agent_claim.py next",
                file=sys.stderr,
            )
        elif a.task_cmd == "release":
            t = tb.release(a.task_id, session=_session(a), handoff=a.handoff, force=a.force)
            print(f"{t['task_id']} back on the board (free); hand-off: {t['handoff']}")
    except (TB.TaskError, B.ClaimError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_take(a: argparse.Namespace) -> int:
    a.kind = None
    return cmd_next(a)


def cmd_next(a: argparse.Namespace) -> int:
    session = _session(a)
    if not session:
        print("error: --session (or AGENT_CLAIM_SESSION) is required", file=sys.stderr)
        return 2
    try:
        got = _tasks(a).next(
            vendor=a.vendor or B.detect_vendor(),
            session=session,
            agent=a.agent or None,
            kind=a.kind,
            branch=a.branch or B.current_branch(),
            worktree=_toplevel(),
            head_sha=_head(),
            task_id=getattr(a, "task_id", None),
        )
    except B.ClaimConflict as exc:
        _print_conflicts(exc.conflicts)
        print("refused: the task's areas overlap a live claim of another session.", file=sys.stderr)
        return 1
    except (TB.TaskError, B.ClaimError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if got is None:
        print("no free task: everything is taken, blocked by a dependency or overlaps a live claim")
        return 3
    t, claim = got
    if a.json:
        print(json.dumps({"task": t, "claim": claim}, indent=2, sort_keys=True))
        return 0
    _print_task(t, full=True)
    print(f"\nclaim {claim['claim_id']}  worklog {B.WL.path_for(Path(_board(a).dir), claim['claim_id'])}")
    print(
        "do: stage building -> work (plan/done/note) -> PR -> stage pr_open --pr N -> task done "
        f"{t['task_id']} -> release --summary. Carry the id into the branch, the PR title and the commit trailer "
        f"'Design-Task: {t['task_id']}'",
        file=sys.stderr,
    )
    return 0


def cmd_release(a: argparse.Namespace) -> int:
    session = _session(a)
    try:
        doc = _board(a).release(
            a.claim_id,
            session=session,
            status=a.status,
            note=a.note,
            pr=a.pr,
            force=a.force,
            released_by=session,
            summary=a.summary,
            require_summary=True,
        )
    except (B.ClaimError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(doc, indent=2, sort_keys=True) if a.json else f"{doc['claim_id']} {doc['status']} {doc['ended_at']}"
    )
    return 0


def cmd_list(a: argparse.Namespace) -> int:
    board = _board(a)
    if not a.no_observe:
        board.refresh_claims(write=False)
    view = board.board(include_finished=a.all)
    if a.json:
        print(json.dumps(view, indent=2, sort_keys=True))
        return 0
    rows = view["claims"]
    if view["unreadable"]:
        print(f"WARN: unreadable claim files: {', '.join(view['unreadable'])}", file=sys.stderr)
    if not rows:
        print(
            f"no claims ({'dir ' + view['claims_dir'] + ' absent' if not view['dir_present'] else view['claims_dir']})"
        )
        return 0
    heads = [
        "STATE",
        "STAGE",
        "CI",
        "VENDOR",
        "AGENT/SESSION",
        "BRANCH",
        "PR",
        "SINCE",
        "HB AGE",
        "TASK",
        "PATHS",
        "CLAIM",
    ]
    table = []
    for r in rows:
        hb = r["heartbeat_age_minutes"]
        table.append(
            [
                r["state"],
                r["stage"] + ("" if r["locks_held"] or r["stage"] == "abandoned" else " (files free)"),
                ((r.get("ci") or {}).get("state") or "-"),
                r["vendor"] or "-",
                (r["agent"] or r["session"] or "-")[:28],
                (r["branch"] or "-")[:40],
                str(r["pr_number"] or r["pr"] or "-"),
                (r["started_at"] or "-")[:16],
                "-" if hb is None else f"{hb:.0f}m",
                (r["task"] or "")[:40],
                ",".join(r["paths"])[:60],
                r["claim_id"],
            ]
        )
    widths = [max(len(h), *(len(row[i]) for row in table)) for i, h in enumerate(heads)]
    print("  ".join(h.ljust(w) for h, w in zip(heads, widths)))
    for row in table:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)))
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    board = _board(a)
    session = _session(a)
    branch = a.exclude_branch if a.exclude_branch is not None else B.current_branch()
    try:
        rows = board.conflicts(a.paths, session=session, branch=branch)
        if rows and board.refresh_claims([r["claim_id"] for r in rows]):
            rows = board.conflicts(a.paths, session=session, branch=branch)  # merged holders free their files
    except (B.ClaimError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 0 if a.warn_only else 2
    warning = None
    if not a.no_gh:
        pr_rows, warning = B.draft_pr_conflicts(a.paths, exclude_branch=branch, timeout_s=a.gh_timeout)
        rows += pr_rows
    if warning:
        print(f"WARN: {warning}", file=sys.stderr)
    out = {
        "schema": B.CHECK_SCHEMA,
        "at": B.iso(board.now()),
        "paths": list(a.paths),
        "exclude_session": session,
        "exclude_branch": branch,
        "draft_prs_consulted": (not a.no_gh) and warning is None,
        "warning": warning,
        "conflict": bool(rows),
        "conflicts": rows,
    }
    if a.json:
        print(json.dumps(out, indent=2, sort_keys=True))
    if rows:
        _print_conflicts(rows, prefix="WARN" if a.warn_only else "CONFLICT")
        if a.warn_only:
            print(
                "agent-claim (warn-only until AGENTS.md 19.1.0): commit continues; coordinate with the holder.",
                file=sys.stderr,
            )
            return 0
        return 1
    if not a.json and not a.quiet:
        print("clear: no live claim of another session and no open draft PR overlaps these paths")
    return 0


def cmd_compact(a: argparse.Namespace) -> int:
    started = datetime.now(timezone.utc)
    board = _board(a)
    try:
        res = board.compact(apply=a.apply)
    except OSError as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        if a.apply and a.lane_receipt:
            _receipt(ok=False, started=started, summary={}, error=type(exc).__name__, history=board.history)
        return 2
    print(json.dumps(res, indent=2, sort_keys=True))
    if a.apply and a.lane_receipt:  # never from a dry run
        _receipt(
            ok=True,
            started=started,
            history=board.history,
            summary={k: res[k] for k in ("eligible", "archived", "removed")} | {"skipped": len(res["skipped"])},
        )
    return 0


def _receipt(*, ok: bool, started: datetime, summary: dict, history: Path, error: str | None = None) -> None:
    from scripts.lib import lane_last_receipt as R

    R.write_lane_receipt(
        LANE_ID,
        ok=ok,
        exit_code=0 if ok else 2,
        started_at=started,
        script=SCRIPT,
        summary=summary,
        error=error,
        output={
            "produced_count": int(summary.get("archived") or 0),
            "attempted_count": int(summary.get("eligible") or 0),
            "skipped_reasons": {},
            "empty_reason": None if summary.get("eligible") else "nothing_eligible",
            "output_evidence": [{"kind": "file", "ref": str(history)}],
        },
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent_claim.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--claims-dir", default=None, help="default: TRADEAI_AGENT_CLAIMS_DIR or persistent-state")
    p.add_argument("--stale-hours", type=float, default=None, help=f"default {B.DEFAULT_STALE_HOURS:g}")
    p.add_argument("--compact-days", type=float, default=B.DEFAULT_COMPACT_DAYS)
    p.add_argument("--vendor", default=None, help="claude | codex | cursor | any label (all equal)")
    p.add_argument("--session", default=None)
    p.add_argument("--agent", default=None)
    p.add_argument(
        "--no-gh", dest="no_gh_global", action="store_true", help="never call GitHub (stages from receipts only)"
    )
    p.add_argument("--gh-call-timeout", type=float, default=B.LC.GH_TIMEOUT_S, help="seconds per GitHub GET")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("claim")
    c.add_argument("--task", default=None)
    c.add_argument("--paths", nargs="+", default=None)
    c.add_argument("--add", nargs="+", default=None, help="extend this session's claim with more paths")
    c.add_argument("--claim", default=None, help="with --add: the claim to extend (default: this session's one)")
    c.add_argument("--branch", default=None)
    c.add_argument("--pr", default=None)
    c.add_argument("--note", default=None)
    c.add_argument("--goal", default=None, help="worklog Goal (default: the task)")
    c.add_argument("--request", default=None, help="the operator request, quoted verbatim in the worklog Goal")
    c.add_argument("--plan", nargs="*", default=None, help="initial plan steps")
    c.add_argument("--json", action="store_true")
    c.set_defaults(fn=cmd_claim)

    h = sub.add_parser("heartbeat")
    h.add_argument("claim_id")
    h.add_argument("--pr", default=None)
    h.add_argument("--note", default=None)
    h.add_argument("--branch", default=None)
    h.add_argument("--json", action="store_true")
    h.set_defaults(fn=cmd_heartbeat)

    for name, fn, arg, hlp in (
        ("plan", cmd_plan, "step", "add a plan step (checkbox) to the worklog"),
        ("done", cmd_done, "step", "check off a plan step (exact text or a unique substring)"),
        ("note", cmd_note, "text", "record a decision and why (--change: a change made)"),
        ("blocker", cmd_blocker, "text", "record a blocker and what is needed from whom"),
    ):
        w = sub.add_parser(name, help=hlp)
        w.add_argument(arg)
        w.add_argument("--claim", default=None, help="claim id (default: this session's one active claim)")
        w.add_argument("--force", action="store_true", help="write another session's worklog")
        if name == "note":
            w.add_argument("--change", action="store_true", help="record under Changes made instead of Decisions")
        w.set_defaults(fn=fn)

    ho = sub.add_parser("handoff", help="set the Handoff section: next step, verify, worktree, branch")
    ho.add_argument("--claim", default=None)
    ho.add_argument("--next", default=None, help="the exact next step")
    ho.add_argument("--verify", default=None, help="how to verify")
    ho.add_argument("--worktree", default=None)
    ho.add_argument("--branch", default=None)
    ho.add_argument("--force", action="store_true")
    ho.set_defaults(fn=cmd_handoff)

    to = sub.add_parser("takeover", help="print a claim's Handoff first; --claim takes the work over")
    to.add_argument("claim_id")
    to.add_argument("--claim", action="store_true", help="claim the same paths/branch and carry the worklog forward")
    to.add_argument("--task", default=None)
    to.set_defaults(fn=cmd_takeover)

    ss = sub.add_parser("status", help="what is in flight, what can be taken over, local-only work at risk")
    ss.add_argument("--json", action="store_true")
    ss.add_argument("--no-observe", action="store_true")
    ss.add_argument("--repo", default=None, help="git repo to scan for local-only branches (default: cwd)")
    ss.add_argument("--days", type=int, default=14, help="local-only scan window (days of commit age)")
    ss.add_argument("--limit", type=int, default=40)
    ss.set_defaults(fn=cmd_status)

    tk = sub.add_parser("task", help="the task board: add, split, list, show, done, release")
    tsub = tk.add_subparsers(dest="task_cmd", required=True)
    ta = tsub.add_parser("add")
    ta.add_argument(
        "--id", default=None, help="design task id DSN-<YYYYMMDD>-<slug>-P<n>-T<m> (default: generated T-...)"
    )
    ta.add_argument("--title", required=True)
    ta.add_argument("--kind", required=True, choices=list(TB.KINDS))
    ta.add_argument("--areas", nargs="+", required=True, help="files, directories or globs the task will touch")
    ta.add_argument("--depends-on", nargs="*", default=None)
    ta.add_argument("--priority", type=int, default=TB.DEFAULT_PRIORITY, help="1 is highest")
    ta.add_argument("--acceptance", nargs="*", default=None, help="acceptance criteria (seed the worklog Plan)")
    ta.add_argument("--quote", default=None, help="the operator request, verbatim")
    ta.add_argument("--estimate", default=None, help="time/cost estimate, free text (e.g. '2h', '$3')")
    ta.add_argument("--json", action="store_true")
    tp = tsub.add_parser("split")
    tp.add_argument("task_id")
    tp.add_argument("--part", action="append", required=True, help="'title | area1,area2 | acc1; acc2'")
    tl = tsub.add_parser("list")
    tl.add_argument("--status", default=None, help="free | taken | in_progress | done | split")
    tl.add_argument("--json", action="store_true")
    tw = tsub.add_parser("show")
    tw.add_argument("task_id")
    tw.add_argument("--json", action="store_true")
    td = tsub.add_parser("done")
    td.add_argument("task_id")
    td.add_argument("--summary", default=None)
    td.add_argument("--cost", default=None, help="actual cost, free text")
    td.add_argument("--force", action="store_true")
    tr = tsub.add_parser("release")
    tr.add_argument("task_id")
    tr.add_argument("--handoff", required=True, help="the exact next step for whoever picks it up")
    tr.add_argument("--force", action="store_true")
    tk.set_defaults(fn=cmd_task)

    nx = sub.add_parser("next", help="pick, claim and start the highest-priority free task")
    nx.add_argument("--kind", default=None, choices=list(TB.KINDS))
    nx.add_argument("--branch", default=None)
    nx.add_argument("--json", action="store_true")
    nx.set_defaults(fn=cmd_next)

    tkk = sub.add_parser("take", help="take one specific task (claims its areas; refused on overlap)")
    tkk.add_argument("task_id")
    tkk.add_argument("--branch", default=None)
    tkk.add_argument("--json", action="store_true")
    tkk.set_defaults(fn=cmd_take)

    st = sub.add_parser("stage", help="declare building or pr_open (owner only)")
    st.add_argument("claim_id")
    st.add_argument("stage", choices=list(B.LC.DECLARABLE))
    st.add_argument("--pr", default=None)
    st.add_argument("--note", default=None)
    st.add_argument("--json", action="store_true")
    st.set_defaults(fn=cmd_stage)

    sy = sub.add_parser("sync", help="auto-advance stages from GitHub + release receipts")
    gs = sy.add_mutually_exclusive_group(required=True)
    gs.add_argument("--dry-run", action="store_true")
    gs.add_argument("--apply", action="store_true")
    sy.add_argument("--json", action="store_true")
    sy.set_defaults(fn=cmd_sync)

    pc = sub.add_parser("precommit", help="pre-commit gate (warn-only below AGENTS.md 20.0.0 ACTIVE)")
    pc.add_argument("--paths", nargs="+", required=True)
    pc.add_argument("--exclude-branch", default=None, help="own branch (default: current git branch)")
    pc.add_argument("--agents-md", default=None, help="AGENTS.md to read the policy state from (default: repo root)")
    pc.add_argument("--json", action="store_true")
    pc.set_defaults(fn=cmd_precommit)

    r = sub.add_parser("release")
    r.add_argument("claim_id")
    r.add_argument("--status", choices=["done", "abandoned"], default="done")
    r.add_argument("--note", default=None)
    r.add_argument("--pr", default=None)
    r.add_argument("--force", action="store_true", help="release another session's claim; recorded as released_by")
    r.add_argument("--summary", default=None, help="final summary line for the worklog (required when it exists)")
    r.add_argument("--json", action="store_true")
    r.set_defaults(fn=cmd_release)

    ls = sub.add_parser("list")
    ls.add_argument("--json", action="store_true")
    ls.add_argument("--all", action="store_true", help="include done/abandoned")
    ls.add_argument("--no-observe", action="store_true", help="show cached stages only (no GitHub, no receipts)")
    ls.set_defaults(fn=cmd_list)

    k = sub.add_parser("check")
    k.add_argument("--paths", nargs="+", required=True)
    k.add_argument("--exclude-branch", default=None, help="own branch (default: current git branch)")
    k.add_argument("--no-gh", action="store_true", help="skip the open-draft-PR fallback")
    k.add_argument("--gh-timeout", type=float, default=15.0)
    k.add_argument("--warn-only", action="store_true", help="report conflicts, exit 0 (pre-commit mode)")
    k.add_argument("--json", action="store_true")
    k.add_argument("--quiet", action="store_true")
    k.set_defaults(fn=cmd_check)

    m = sub.add_parser("compact")
    g = m.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    m.add_argument("--lane-receipt", action="store_true", help=f"write the {LANE_ID} LaneRunReceipt (timer runs)")
    m.set_defaults(fn=cmd_compact)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return int(a.fn(a))


if __name__ == "__main__":
    sys.exit(main())
