"""Independent acceptance for self-heal fixes (pure; no I/O).

Coordinator requirement 2026-10-16: "Acceptance is judged by an evaluator independent of the fixer: deterministic tests
plus CI on the PR head. The fixer's own claims never count."

The evaluator reads only facts the HARNESS produced — exit codes of test runs it executed itself, the diff guard's
refusals, and GitHub's check results for the PR head SHA. It never reads the backend's summary, its stdout, or anything
the model wrote about itself; a backend that says "all tests pass" while the harness saw a failure is rejected. Any
backend (Claude Code today, Codex once qualified) is judged by this same function, so qualification is comparable.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional

LOCAL_SCHEMA = "SelfHealLocalAcceptance@v1"
PR_SCHEMA = "SelfHealPrHeadAcceptance@v1"
FINAL_SCHEMA = "SelfHealAcceptance@v1"
SHIP_SCHEMA = "SelfHealShipCheck@v1"

#: The only fields of an iteration record the evaluator may read. Model output lives elsewhere and is never read.
FACT_FIELDS = ("red_first", "targeted_rc", "ci_rc", "refusals", "tests_run", "candidate", "guard", "test_runs")
#: The harness test runs that acceptance needs, each bound to the candidate commit (architect review 2026-10-16).
REQUIRED_RUNS = ("red_first", "targeted", "ci")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _runs_bound(facts: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Every required run happened in a fresh checkout of the candidate (red-first: of the base, with the candidate's
    test files overlaid from the commit object), and nothing in that checkout or its .git changed during the run."""
    cand = facts.get("candidate") or {}
    runs = {r.get("kind"): r for r in facts.get("test_runs") or [] if isinstance(r, Mapping)}
    why = []
    for kind in REQUIRED_RUNS:
        r = runs.get(kind)
        if not r or not r.get("run_id"):
            why.append(f"{kind}:missing")
            continue
        want = cand.get("base_sha") if kind == "red_first" else cand.get("commit_sha")
        if not want or r.get("checkout_sha") != want or r.get("head_after") != want:
            why.append(f"{kind}:not_bound_to_candidate")
        if kind == "red_first" and r.get("overlay_from") != cand.get("commit_sha"):
            why.append(f"{kind}:overlay_not_from_candidate")
        if r.get("integrity_ok") is not True:
            why.append(f"{kind}:checkout_or_git_mutated")
    return not why, why


def local_verdict(iteration: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic, harness-run evidence for one iteration: the regression test FAILED on the base commit, the
    changed tests passed with the fix, the PR-profile CI passed, and the diff guard refused nothing — every one of
    those judged on ONE immutable candidate commit (sha + tree), in fresh checkouts the tests could not write."""
    facts = {k: iteration.get(k) for k in FACT_FIELDS}
    cand = facts.get("candidate") or {}
    guard = facts.get("guard") or {}
    bound, unbound = _runs_bound(facts)
    checks = {
        "regression_test_present": bool(facts["tests_run"]),
        "red_on_base": facts["red_first"] is True,
        "green_with_fix": facts["targeted_rc"] == 0,
        "ci_pr_profile_green": facts["ci_rc"] == 0,
        "diff_guard_clean": not facts["refusals"],
        "candidate_commit_recorded": bool(_SHA.match(str(cand.get("commit_sha") or ""))
                                          and _SHA.match(str(cand.get("tree_sha") or ""))),
        "guard_judged_candidate_tree": bool(cand.get("tree_sha")) and guard.get("tree_sha") == cand.get("tree_sha"),
        "runs_bound_to_candidate": bound,
    }
    return {"schema": LOCAL_SCHEMA, "accepted": all(checks.values()), "checks": checks,
            "failed": sorted(k for k, v in checks.items() if not v), "unbound": unbound,
            # the binding: what was evaluated, exactly
            "commit_sha": cand.get("commit_sha"), "tree_sha": cand.get("tree_sha"), "base_sha": cand.get("base_sha"),
            "test_run_ids": {r.get("kind"): r.get("run_id") for r in facts.get("test_runs") or []
                             if isinstance(r, Mapping)},
            "guard_verdict": {"tree_sha": guard.get("tree_sha"), "clean": not facts["refusals"],
                              "codes": sorted({str(x.get("code")) for x in facts["refusals"] or []})}}


def ship_verdict(local: Optional[Mapping[str, Any]], *, commit_sha: str, tree_sha: str,
                 prepush_refusals: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Immediately before the push (or the local branch update): the commit about to ship IS the evaluated commit,
    its tree is the evaluated tree, and the diff guard re-run on that tree refused nothing. Any mismatch refuses."""
    lv = local or {}
    refusals = list(prepush_refusals or [])
    checks = {
        "local_accepted": bool(lv.get("accepted")),
        "commit_is_evaluated": bool(commit_sha) and commit_sha == lv.get("commit_sha"),
        "tree_is_evaluated": bool(tree_sha) and tree_sha == lv.get("tree_sha"),
        "prepush_guard_clean": not refusals,
    }
    return {"schema": SHIP_SCHEMA, "accepted": all(checks.values()), "checks": checks,
            "failed": sorted(k for k, v in checks.items() if not v), "commit_sha": commit_sha, "tree_sha": tree_sha,
            "prepush_codes": sorted({str(r.get("code")) for r in refusals})}


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
    if expected_head is not None and head != expected_head:
        verdict = "head_moved"  # exact full-SHA equality: the PR head must BE the evaluated commit
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
    same = bool(local and pr and local.get("commit_sha") and (pr or {}).get("head") == local.get("commit_sha"))
    return {"schema": FINAL_SCHEMA, "accepted": lv and pv == "pass" and same, "local_accepted": lv, "pr_head_ci": pv,
            "pr_head_is_evaluated_commit": same, "evaluated_commit": (local or {}).get("commit_sha"),
            "basis": "harness-run tests + GitHub checks on the PR head SHA; backend claims are not read"}
