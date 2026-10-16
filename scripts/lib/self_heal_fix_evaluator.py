"""Independent acceptance for self-heal fixes (pure; no I/O).

Coordinator requirement 2026-10-16: "Acceptance is judged by an evaluator independent of the fixer: deterministic tests
plus CI on the PR head. The fixer's own claims never count."

The evaluator reads only facts the HARNESS produced — exit codes of test runs it executed itself, the diff guard's
refusals, and GitHub's check results for the PR head SHA. It never reads the backend's summary, its stdout, or anything
the model wrote about itself; a backend that says "all tests pass" while the harness saw a failure is rejected. Any
backend (Claude Code today, Codex once qualified) is judged by this same function, so qualification is comparable.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

LOCAL_SCHEMA = "SelfHealLocalAcceptance@v1"
PR_SCHEMA = "SelfHealPrHeadAcceptance@v1"
FINAL_SCHEMA = "SelfHealAcceptance@v1"

#: The only fields of an iteration record the evaluator may read. Model output lives elsewhere and is never read.
FACT_FIELDS = ("red_first", "targeted_rc", "ci_rc", "refusals", "tests_run")


def local_verdict(iteration: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic, harness-run evidence for one iteration: the regression test FAILED on the base commit, the
    changed tests passed with the fix, the PR-profile CI passed in the worktree, and the diff guard refused nothing."""
    facts = {k: iteration.get(k) for k in FACT_FIELDS}
    checks = {
        "regression_test_present": bool(facts["tests_run"]),
        "red_on_base": facts["red_first"] is True,
        "green_with_fix": facts["targeted_rc"] == 0,
        "ci_pr_profile_green": facts["ci_rc"] == 0,
        "diff_guard_clean": not facts["refusals"],
    }
    return {"schema": LOCAL_SCHEMA, "accepted": all(checks.values()), "checks": checks,
            "failed": sorted(k for k, v in checks.items() if not v)}


_PASS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_FAIL = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE"}


def _state(check: Mapping[str, Any]) -> str:
    """Normalize a statusCheckRollup entry (CheckRun: status+conclusion; StatusContext: state)."""
    if check.get("__typename") == "StatusContext" or ("state" in check and "conclusion" not in check):
        st = str(check.get("state") or "").upper()
        return "pass" if st == "SUCCESS" else ("fail" if st in ("FAILURE", "ERROR") else "pending")
    if str(check.get("status") or "").upper() != "COMPLETED":
        return "pending"
    c = str(check.get("conclusion") or "").upper()
    return "pass" if c in _PASS else ("fail" if c in _FAIL else "pending")


def pr_head_verdict(pr: Mapping[str, Any], *, expected_head: Optional[str] = None,
                    required: Iterable[str] = ()) -> dict[str, Any]:
    """CI on the PR head SHA (``gh pr view --json headRefOid,statusCheckRollup``). pass only when every reported check
    passed, at least one check ran, the head is the SHA the harness pushed, and every ``required`` name is present."""
    head = str(pr.get("headRefOid") or "")
    rollup = [c for c in pr.get("statusCheckRollup") or [] if isinstance(c, dict)]
    states = {str(c.get("name") or c.get("context") or "?"): _state(c) for c in rollup}
    missing = sorted(set(required) - set(states))
    if expected_head and head and not head.startswith(expected_head[:12]) and not expected_head.startswith(head[:12]):
        verdict = "head_moved"
    elif any(v == "fail" for v in states.values()):
        verdict = "fail"
    elif not states or missing or any(v == "pending" for v in states.values()):
        verdict = "pending"
    else:
        verdict = "pass"
    return {"schema": PR_SCHEMA, "verdict": verdict, "head": head, "checks": states, "missing_required": missing}


def final_acceptance(local: Optional[Mapping[str, Any]], pr: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Accepted = harness-local evidence accepted AND CI green on the PR head. Never anything the fixer said."""
    lv = bool(local and local.get("accepted"))
    pv = (pr or {}).get("verdict")
    return {"schema": FINAL_SCHEMA, "accepted": lv and pv == "pass", "local_accepted": lv, "pr_head_ci": pv,
            "basis": "harness-run tests + GitHub checks on the PR head SHA; backend claims are not read"}
