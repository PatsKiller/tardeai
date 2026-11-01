#!/usr/bin/env python3
"""ci_queue_janitor.py — list (and, only with --apply, cancel) GitHub Actions runs that can no longer matter.

Why (2026-10-31): the hosted-runner queue reached ~315 active runs and main's required aggregate
`cio-hardening` waited 48-104 min for a runner after its shards passed. A pull_request run is dead
weight when its PR is closed or merged, or when the PR's head has moved past the run's commit.
Workflow `concurrency` only cancels an older run of the same workflow when a newer one arrives on
the same ref; a closed PR never sends one, and a stale queued run can still hold its group and keep
the newer run `pending` (seen today on cio-full-suite-sharded, 15 of 15 superseded active runs).

What it may cancel — nothing else:
  * event == pull_request, status queued / in_progress / pending / waiting / requested, AND
  * the PR is no longer open (closed or merged), OR its current head SHA differs from the run's.

What it never touches:
  * any run that is not a pull_request run: push (main), schedule, workflow_dispatch, dynamic
    (CodeQL). A cancelled main run counts as red (main-red-alert opens a ci-main-red issue), and
    the deploy poller's promote needs every main workflow green;
  * any run whose head SHA is main's current head;
  * Mergify merge-queue branches (mergify/...);
  * runs whose head repository is gone (deleted fork): the branch cannot be re-checked.

Default is a dry run that prints what it would cancel. --apply re-checks every run right before
cancelling it, by branch (`pulls?state=open&head=<owner>:<branch>`) and, when known, by PR number:
it skips the run if an open PR's head is the run's SHA, and skips a "closed" run if ANY open PR
exists for the branch (the open-PR list spans pages, so a PR closing mid-listing can shift another
PR off the list; a PR may also be reopened). A re-check that errors skips that run and continues. Operator-run tool: it is not
scheduled (AGENTS.md §17, §24.5 — no scheduled remote write). It uses the caller's `gh` login.

Usage:
  python3 scripts/ci_queue_janitor.py                 # dry run, table + summary
  python3 scripts/ci_queue_janitor.py --json          # dry run, machine-readable
  python3 scripts/ci_queue_janitor.py --apply         # operator only: request the cancels
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Callable, Iterable

DEFAULT_REPO = "PatsKiller/tardeai"
ACTIVE_STATUSES = ("queued", "in_progress", "pending", "waiting", "requested")
PROTECTED_BRANCH_PREFIXES = ("mergify/",)

KEEP_NOT_PR = "keep:not-a-pull_request-run"
KEEP_MAIN_HEAD = "keep:main-head-sha"
KEEP_MERGE_QUEUE = "keep:merge-queue-branch"
KEEP_CURRENT = "keep:current-pr-head"
KEEP_NO_REPO = "keep:head-repository-gone"
CANCEL_CLOSED = "cancel:pr-closed-or-merged"
CANCEL_SUPERSEDED = "cancel:superseded-by-newer-pr-head"


@dataclass(frozen=True)
class Decision:
    run_id: int
    workflow: str
    event: str
    status: str
    head_repo: str
    head_branch: str
    head_sha: str
    created_at: str
    pr_number: int | None
    pr_head_sha: str | None
    action: str  # "cancel" | "keep"
    reason: str


def _head_repo(run: dict) -> str:
    return ((run.get("head_repository") or {}).get("full_name") or "").lower()


def classify(runs: Iterable[dict], open_prs: Iterable[dict], main_head_sha: str) -> list[Decision]:
    """Pure: decide keep/cancel for each active run. No I/O.

    `runs` are GitHub workflow-run objects; `open_prs` are GitHub pull objects (state=open).
    PRs are keyed by (head repo, head branch) so a fork branch with the same name never matches.
    """
    by_head: dict[tuple[str, str], dict] = {}
    for pr in open_prs:
        head = pr.get("head") or {}
        key = (((head.get("repo") or {}).get("full_name") or "").lower(), head.get("ref") or "")
        by_head[key] = pr
    out: list[Decision] = []
    for run in runs:
        if run.get("status") not in ACTIVE_STATUSES:
            continue
        sha = run.get("head_sha") or ""
        branch = run.get("head_branch") or ""
        pr = by_head.get((_head_repo(run), branch))
        pr_no = pr.get("number") if pr else None
        pr_sha = ((pr or {}).get("head") or {}).get("sha")
        if run.get("event") != "pull_request":
            action, reason = "keep", KEEP_NOT_PR
        elif main_head_sha and sha == main_head_sha:
            action, reason = "keep", KEEP_MAIN_HEAD
        elif branch.startswith(PROTECTED_BRANCH_PREFIXES):
            action, reason = "keep", KEEP_MERGE_QUEUE
        elif not _head_repo(run):
            # A deleted fork leaves no head repository: the branch cannot be looked up, so never guess.
            action, reason = "keep", KEEP_NO_REPO
        elif pr is None:
            action, reason = "cancel", CANCEL_CLOSED
        elif pr_sha != sha:
            action, reason = "cancel", CANCEL_SUPERSEDED
        else:
            action, reason = "keep", KEEP_CURRENT
        out.append(
            Decision(
                run_id=int(run.get("id") or 0),
                workflow=str(run.get("name") or ""),
                event=str(run.get("event") or ""),
                status=str(run.get("status") or ""),
                head_repo=_head_repo(run),
                head_branch=branch,
                head_sha=sha,
                created_at=str(run.get("created_at") or ""),
                pr_number=pr_no,
                pr_head_sha=pr_sha,
                action=action,
                reason=reason,
            )
        )
    return out


def summarize(decisions: list[Decision]) -> dict:
    by_reason = Counter(d.reason for d in decisions)
    by_wf = Counter(d.workflow for d in decisions if d.action == "cancel")
    return {
        "active_runs": len(decisions),
        "would_cancel": sum(1 for d in decisions if d.action == "cancel"),
        "by_reason": dict(sorted(by_reason.items())),
        "cancel_by_workflow": dict(by_wf.most_common()),
    }


# ── I/O (gh CLI; the caller's login) ───────────────────────────────────────────────────────────


def _gh_json(args: list[str]) -> object:
    proc = subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True)
    return json.loads(proc.stdout or "null")


def _gh_paginate(path: str, key: str | None, max_pages: int = 50) -> list[dict]:
    # Explicit &page=N (gh < 2.48 has no --slurp). `path` already carries per_page=100.
    items: list[dict] = []
    for page_no in range(1, max_pages + 1):
        page = _gh_json([f"{path}&page={page_no}"]) or {}
        batch = page.get(key, []) if key else page
        items.extend(batch)
        if len(batch) < 100:
            break
    return items


def fetch_state(repo: str) -> tuple[list[dict], list[dict], str]:
    """Runs are read BEFORE pulls: a PR head can only move forward after the run list is read, so a
    run is never judged superseded by a PR state older than the run itself."""
    runs: list[dict] = []
    for status in ACTIVE_STATUSES:
        runs.extend(_gh_paginate(f"repos/{repo}/actions/runs?status={status}&per_page=100", "workflow_runs"))
    seen: set[int] = set()
    uniq = [r for r in runs if not (r["id"] in seen or seen.add(r["id"]))]
    prs = _gh_paginate(f"repos/{repo}/pulls?state=open&per_page=100", None)
    main_sha = str((_gh_json([f"repos/{repo}/commits/main"]) or {}).get("sha") or "")
    return uniq, prs, main_sha


def apply_cancels(
    repo: str,
    decisions: list[Decision],
    *,
    get_pr: Callable[[int], dict] | None = None,
    find_open_prs: Callable[[str, str], list] | None = None,
    cancel: Callable[[int], None] | None = None,
) -> dict:
    """Cancel each `cancel` decision only after a fresh re-check of the PR(s) for its branch.

    `find_open_prs(owner, branch)` returns the open PRs whose head is <owner>:<branch>. Any error
    in the re-check or the cancel is recorded for that run, which is skipped; the loop continues.
    """
    get_pr = get_pr or (lambda n: _gh_json([f"repos/{repo}/pulls/{n}"]))  # type: ignore[assignment]
    find_open_prs = find_open_prs or (  # type: ignore[assignment]
        lambda owner, branch: (
            _gh_json(
                [
                    "-X",
                    "GET",
                    f"repos/{repo}/pulls",
                    "-f",
                    "state=open",
                    "-f",
                    f"head={owner}:{branch}",
                    "-f",
                    "per_page=100",
                ]
            )
            or []
        )
    )
    cancel = cancel or (lambda rid: _gh_json(["-X", "POST", f"repos/{repo}/actions/runs/{rid}/cancel"]))  # type: ignore[assignment]
    done: list[int] = []
    skipped: list[dict] = []
    failed: list[dict] = []
    for d in decisions:
        if d.action != "cancel":
            continue
        try:
            why = _recheck_reason_to_keep(d, get_pr, find_open_prs)
        except Exception as exc:  # re-check failed: never cancel blind
            failed.append({"run_id": d.run_id, "stage": "recheck", "error": str(exc)[:200]})
            continue
        if why:
            skipped.append({"run_id": d.run_id, "why": why})
            continue
        try:
            cancel(d.run_id)
            done.append(d.run_id)
        except Exception as exc:  # already finished, permission, etc. — report, never retry here
            failed.append({"run_id": d.run_id, "stage": "cancel", "error": str(exc)[:200]})
    return {"cancel_requested": done, "skipped_recheck": skipped, "failed": failed}


def _recheck_reason_to_keep(
    d: Decision,
    get_pr: Callable[[int], dict],
    find_open_prs: Callable[[str, str], list],
) -> str | None:
    """Return why the run must be kept now, or None if the cancel still stands."""
    owner = d.head_repo.split("/", 1)[0] if d.head_repo else ""
    if not owner or not d.head_branch:
        return "no head repository/branch to re-check"
    open_prs = find_open_prs(owner, d.head_branch) or []
    if any(((pr.get("head") or {}).get("sha")) == d.head_sha for pr in open_prs):
        return "an open PR's head is this run's SHA"
    if d.reason == CANCEL_CLOSED and open_prs:
        return "the branch has an open PR (reopened, or missed by the paged listing)"
    if d.pr_number is not None:
        fresh = get_pr(d.pr_number) or {}
        if fresh.get("state") == "open" and ((fresh.get("head") or {}).get("sha")) == d.head_sha:
            return "the PR head is this run's SHA"
    return None


def _table(decisions: list[Decision]) -> str:
    rows = [d for d in decisions if d.action == "cancel"]
    lines = [f"{'run_id':>12}  {'status':11}  {'workflow':38}  {'pr':>5}  {'run_sha':9}  {'pr_head':9}  reason"]
    for d in sorted(rows, key=lambda x: (x.pr_number or 0, x.created_at)):
        lines.append(
            f"{d.run_id:>12}  {d.status:11}  {d.workflow[:38]:38}  {str(d.pr_number or '-'):>5}  "
            f"{d.head_sha[:9]:9}  {(d.pr_head_sha or '-')[:9]:9}  {d.reason}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, fetch: Callable[[str], tuple] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--apply", action="store_true", help="operator only: request the cancels (default: dry run)")
    ap.add_argument("--json", action="store_true", help="print decisions + summary as JSON")
    args = ap.parse_args(argv)

    runs, prs, main_sha = (fetch or fetch_state)(args.repo)
    decisions = classify(runs, prs, main_sha)
    summary = summarize(decisions)
    summary["mode"] = "apply" if args.apply else "dry-run"
    summary["main_head_sha"] = main_sha
    if args.json:
        print(json.dumps({"summary": summary, "decisions": [asdict(d) for d in decisions]}, indent=2))
    else:
        print(_table(decisions))
        print(json.dumps(summary, indent=2))
    if args.apply:
        result = apply_cancels(args.repo, decisions)
        print(json.dumps({"apply": result}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
