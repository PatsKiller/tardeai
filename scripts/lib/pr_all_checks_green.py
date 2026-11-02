"""Green means every check on the exact head passed — not only branch protection's required set.

Branch protection names a few *required* checks. A PR can be green on all of them and still
be red somewhere else, and every merge path that reads only the required list will merge it.
That is what happened on 2026-11-01: PR #2465 merged with `secret-scan` red on four heads,
main went red at f96c6399f and the deploy poller refused to promote.

Callers wired today:

* ``pr_merge_digest.classify_pr`` — digest eligibility;
* ``pr_merge_telegram.pr_check_rollup_green`` — the Telegram approve/notify gate;
* ``mergify_queue_monitor.fetch_head_check_conclusions`` + ``classify_dequeue`` — a red check of any
  kind is a real failure, never a flake to requeue.

``.mergify.yml`` carries the same rule on every queue entry rule and queue merge condition, as
negated regexes that exclude Mergify's own checks (``-check-failure~=`` / ``-check-pending~=``).
Not yet wired, each named rather than implied: ``work_pipeline_tier2.merge_preconditions`` (the
Command Center merge applier, OFF today), ``pr_merge_telegram._bootstrap_gh_merge`` (OI-097) and
``scripts/agent_merge_pr.sh``.

A check is green when its conclusion is `success` or `neutral`. `skipped` never blocks, but a skip
never replaces a run that actually reported. Anything else — including a missing status, which is
pending rather than completed — blocks. When a check name appears more than once, the latest
non-skipped run wins.

AUTHORITY: READ_ONLY_ADVISORY. This module reads check runs; it never merges.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

OK_CONCLUSIONS = frozenset({"success", "neutral"})
SKIPPED_CONCLUSION = "skipped"
NO_RUNS_REASON = "no check runs on the head"
#: Keep the failing list readable in a Telegram page or an error detail.
DESCRIBE_LIMIT = 300

CheckRuns = Iterable[Mapping[str, Any]]
GhJson = Callable[[str], Any]


def _suite_of(run: Mapping[str, Any]) -> str:
    """The check suite or workflow that produced a run, so equal job names never merge.

    Generic job names ("shard 0", "test") repeat across workflows; grouped by name alone, a green
    run in one workflow could stand in for a red one in another.
    """
    suite = run.get("check_suite")
    if isinstance(suite, Mapping):
        return str(suite.get("id") or "")
    return str(run.get("check_suite_id") or run.get("workflow") or run.get("workflowName") or "")


def _label(name: str, suite: str) -> str:
    return f"{name} [{suite}]" if suite else name


def _latest_per_name(check_runs: CheckRuns) -> dict[tuple[str, str], Mapping[str, Any]]:
    """One entry per (check name, check suite): the run that actually reported wins over a skip."""
    latest: dict[tuple[str, str], Mapping[str, Any]] = {}
    for run in check_runs or []:
        name = str(run.get("name") or "").strip()
        if not name:
            continue
        key = (name, _suite_of(run))
        prev = latest.get(key)
        if prev is None:
            latest[key] = run
            continue
        prev_skipped = str(prev.get("conclusion") or "") == SKIPPED_CONCLUSION
        new_skipped = str(run.get("conclusion") or "") == SKIPPED_CONCLUSION
        if prev_skipped and not new_skipped:
            latest[key] = run  # a real run supersedes a skip
        elif new_skipped and not prev_skipped:
            continue  # a skip never hides a failure: keep the run that actually reported
        elif str(run.get("started_at") or "") >= str(prev.get("started_at") or ""):
            latest[key] = run
    return latest


def evaluate(check_runs: CheckRuns, *, allow_empty: bool = False) -> dict[str, Any]:
    """Decide green/not green for one head's check runs.

    ``allow_empty`` exists for a repository with no check runs at all; a merge gate must leave
    it False, because "no checks" is not evidence that anything passed.
    """
    latest = _latest_per_name(check_runs)
    if not latest:
        return {
            "ok": bool(allow_empty),
            "passing": [],
            "failing": [],
            "skipped": [],
            "checked": 0,
            "reason": None if allow_empty else NO_RUNS_REASON,
        }
    passing: list[str] = []
    failing: list[str] = []
    skipped: list[str] = []
    for key in sorted(latest):
        name, suite = key
        label = _label(name, suite)
        run = latest[key]
        # GitHub omits `status` on some payloads; an unknown status is pending, never completed.
        status = str(run.get("status") or "queued").lower()
        conclusion = str(run.get("conclusion") or "").lower()
        if status != "completed":
            failing.append(f"{label}: {status}")
        elif conclusion == SKIPPED_CONCLUSION:
            skipped.append(label)
        elif conclusion in OK_CONCLUSIONS:
            passing.append(label)
        else:
            failing.append(f"{label}: {conclusion or 'no conclusion'}")
    return {
        "ok": not failing,
        "passing": passing,
        "failing": failing,
        "skipped": skipped,
        "checked": len(latest),
        "reason": None,
    }


def describe(result: Mapping[str, Any]) -> str:
    """One plain sentence naming what blocks, bounded for an error detail or a page."""
    if result.get("ok"):
        return "green: " + (", ".join(result.get("passing") or []) or "no checks recorded")
    detail = "; ".join(result.get("failing") or []) or str(result.get("reason") or "not green")
    text = "not green: " + detail
    return text if len(text) <= DESCRIBE_LIMIT else text[: DESCRIBE_LIMIT - 1] + "…"


def normalize_rollup(rollup: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalize ``statusCheckRollup`` rows (CheckRun or StatusContext) to ``evaluate``'s shape.

    GitHub returns CheckRun rows with ``name``/``status``/``conclusion`` and StatusContext rows with
    ``context``/``state``; both carry timestamps. Case is normalized because the API is inconsistent.
    """
    runs: list[dict[str, Any]] = []
    for row in rollup or []:
        name = str(row.get("name") or row.get("context") or "").strip()
        if not name:
            continue
        state = str(row.get("state") or "").upper()
        status = str(row.get("status") or "").lower()
        conclusion = str(row.get("conclusion") or "").lower() or (state.lower() if state else "")
        if not status:
            # A rollup row that carries a conclusion IS a completed run; StatusContext rows carry only
            # `state`. Treating a conclusion-only CheckRun as pending made every fixture look red.
            status = "completed" if conclusion else "queued"
        run = {"name": name, "status": status, "conclusion": conclusion,
               "started_at": str(row.get("startedAt") or row.get("started_at") or "")}
        workflow = row.get("workflowName") or row.get("workflow")
        if workflow:
            run["workflowName"] = str(workflow)
        runs.append(run)
    return runs


def evaluate_rollup(rollup: Iterable[Mapping[str, Any]] | None, *, allow_empty: bool = False) -> dict[str, Any]:
    """``evaluate`` over a PR's ``statusCheckRollup`` (the checks on its current head).

    Fails closed at ``ROLLUP_LIMIT`` rows: the rollup is truncated at that size, and grading a
    truncated view would let a red check sit on the part we could not read.
    """
    rows = list(rollup or [])
    result = evaluate(normalize_rollup(rows), allow_empty=allow_empty)
    if len(rows) >= ROLLUP_LIMIT:
        result["ok"] = False
        result["reason"] = f"rollup reached its {ROLLUP_LIMIT}-row limit; every check could not be proven"
    return result


PAGE_SIZE = 100
#: `gh pr view --json statusCheckRollup` is capped; at the cap we cannot prove every check was read.
ROLLUP_LIMIT = 100
#: A head carries ~80 runs today; this is a runaway guard, not a real limit.
MAX_PAGES = 10


def check_runs_for(gh_json: GhJson, repo: str, sha: str) -> tuple[list[Mapping[str, Any]], int | None, bool]:
    """Every check run on ``sha``, paged, plus the ``total_count`` GitHub reported."""
    runs: list[Mapping[str, Any]] = []
    total: int | None = None
    page = 1
    exhausted = False
    while page <= MAX_PAGES:
        doc = gh_json(f"repos/{repo}/commits/{sha}/check-runs?per_page={PAGE_SIZE}&page={page}") or {}
        chunk = list((doc.get("check_runs") if isinstance(doc, Mapping) else None) or [])
        if total is None:
            reported = doc.get("total_count") if isinstance(doc, Mapping) else None
            total = reported if isinstance(reported, int) else None
        runs.extend(chunk)
        if len(chunk) < PAGE_SIZE:
            break  # a short page is the last page
        page += 1
    else:
        exhausted = True  # hit MAX_PAGES with a full last page
    return runs, total, exhausted


def all_checks_green(gh_json: GhJson, repo: str, sha: str, *, allow_empty: bool = False) -> dict[str, Any]:
    """Green only if every non-skipped check run on the exact ``sha`` is success or neutral.

    Fails closed if GitHub reports more runs than could be read: grading a partial page would let a
    red check sit on the unread page.
    """
    runs, total, exhausted = check_runs_for(gh_json, repo, sha)
    result = evaluate(runs, allow_empty=allow_empty)
    result["sha"] = sha
    result["read"] = len(runs)
    if isinstance(total, int) and len(runs) < total:
        result["ok"] = False
        result["reason"] = f"could not read every check run: {len(runs)} of {total}"
    elif exhausted and total is None:
        result["ok"] = False
        result["reason"] = f"could not confirm every check run was read ({len(runs)} in {MAX_PAGES} pages)"
    return result
