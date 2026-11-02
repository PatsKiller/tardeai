"""Green means every check on the exact head passed — not only branch protection's required set.

Branch protection names a few *required* checks. A PR can be green on all of them and still
be red somewhere else, and every merge path that reads only the required list will merge it.
That is what happened on 2026-11-01: PR #2465 merged with `secret-scan` red on four heads,
main went red at f96c6399f and the deploy poller refused to promote.

Callers today:

* ``work_pipeline_tier2.merge_preconditions`` (the Command Center merge applier, currently OFF);
* ``mergify_queue_monitor.classify_dequeue`` (requeue decisions — a red unrequired check is a real
  failure, not a flake to resubmit).

Still to wire, and each is a held path so it belongs in its own held change: the merge digest's
eligibility rule (``pr_merge_digest``), the Telegram approve path (``pr_merge_telegram``), and the
merge actor itself (``.mergify.yml``). Until those land, a red non-required check can still merge
through them.

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


def _latest_per_name(check_runs: CheckRuns) -> dict[str, Mapping[str, Any]]:
    latest: dict[str, Mapping[str, Any]] = {}
    for run in check_runs or []:
        name = str(run.get("name") or "").strip()
        if not name:
            continue
        prev = latest.get(name)
        if prev is None:
            latest[name] = run
            continue
        prev_skipped = str(prev.get("conclusion") or "") == SKIPPED_CONCLUSION
        new_skipped = str(run.get("conclusion") or "") == SKIPPED_CONCLUSION
        if prev_skipped and not new_skipped:
            latest[name] = run  # a real run supersedes a skip
        elif new_skipped and not prev_skipped:
            continue  # a skip never hides a failure: keep the run that actually reported
        elif str(run.get("started_at") or "") >= str(prev.get("started_at") or ""):
            latest[name] = run
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
    for name in sorted(latest):
        run = latest[name]
        # GitHub omits `status` on some payloads; an unknown status is pending, never completed.
        status = str(run.get("status") or "queued")
        conclusion = str(run.get("conclusion") or "")
        if status != "completed":
            failing.append(f"{name}: {status}")
        elif conclusion == SKIPPED_CONCLUSION:
            skipped.append(name)
        elif conclusion in OK_CONCLUSIONS:
            passing.append(name)
        else:
            failing.append(f"{name}: {conclusion or 'no conclusion'}")
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


PAGE_SIZE = 100
#: A head carries ~80 runs today; this is a runaway guard, not a real limit.
MAX_PAGES = 10


def check_runs_for(gh_json: GhJson, repo: str, sha: str) -> tuple[list[Mapping[str, Any]], int | None]:
    """Every check run on ``sha``, paged, plus the ``total_count`` GitHub reported."""
    runs: list[Mapping[str, Any]] = []
    total: int | None = None
    page = 1
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
    return runs, total


def all_checks_green(gh_json: GhJson, repo: str, sha: str, *, allow_empty: bool = False) -> dict[str, Any]:
    """Green only if every non-skipped check run on the exact ``sha`` is success or neutral.

    Fails closed if GitHub reports more runs than could be read: grading a partial page would let a
    red check sit on the unread page.
    """
    runs, total = check_runs_for(gh_json, repo, sha)
    result = evaluate(runs, allow_empty=allow_empty)
    result["sha"] = sha
    result["read"] = len(runs)
    if isinstance(total, int) and len(runs) < total:
        result["ok"] = False
        result["reason"] = f"could not read every check run: {len(runs)} of {total}"
    return result
