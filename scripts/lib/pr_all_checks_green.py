"""One merge rule: every check on the exact head is green, not just the required ones.

Branch protection names a few *required* checks. A PR can be green on all of them and still
be red somewhere else, and every merge path that reads only the required list will merge it.
That is what happened on 2026-11-01: PR #2465 merged with `secret-scan` red on four heads,
main went red at f96c6399f and the deploy poller refused to promote.

This module is the one place that decides "green". Every merge path calls it with the head SHA
it is about to merge, so a red non-required check blocks exactly like a red required one.

A check is green when its conclusion is `success` or `neutral`. `skipped` never blocks and is
reported separately. `cancelled`, `timed_out`, `failure`, `action_required`, `stale` and
anything still running all block. When a check name appears more than once, the latest run wins.

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
        if prev is None or str(run.get("started_at") or "") >= str(prev.get("started_at") or ""):
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
        status = str(run.get("status") or "completed")
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


def check_runs_for(gh_json: GhJson, repo: str, sha: str) -> list[Mapping[str, Any]]:
    """Every check run on ``sha``, via the caller's ``gh api`` reader."""
    doc = gh_json(f"repos/{repo}/commits/{sha}/check-runs?per_page=100") or {}
    runs = doc.get("check_runs") if isinstance(doc, Mapping) else None
    return list(runs or [])


def all_checks_green(gh_json: GhJson, repo: str, sha: str, *, allow_empty: bool = False) -> dict[str, Any]:
    """Green only if every non-skipped check run on the exact ``sha`` is success or neutral."""
    result = evaluate(check_runs_for(gh_json, repo, sha), allow_empty=allow_empty)
    result["sha"] = sha
    return result
